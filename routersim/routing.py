from enum import Enum
from collections import ChainMap, OrderedDict
from .observers import Event, EventType
from .messaging import FrameType
from .mpls import LabelStackOperation, CombinedAction
from copy import copy, deepcopy
import ipaddress


class RouteType(Enum):
    LOCAL = 1
    CONNECTED = 2
    STATIC = 5
    RSVP = 7
    ISIS = 15
    BGP = 170

    def __str__(self):
        return str(self.name)


class ForwardingAction:
    pass


class ForwardAction(ForwardingAction):

    @staticmethod
    def apply(pdu, router):
        return (pdu, None)


class ForwardingEntry:

    def __init__(self, prefix, interface, action='FORWARD'):
        self.prefix = prefix
        self.interface = interface
        self.action = action

    def __str__(self):
        return f"{self.prefix} via {self.interface} ({self.action})"


class Route:

    # TODO: Should we have hidden field for when interface goes up/down?
    # TODO: Should this be a tuple?
    def __init__(self, prefix, route_type, interface, next_hop_address,
                 metric=None, admin_cost=None, action="FORWARD"):
        self.prefix = prefix
        self.type = route_type
        self.interface = interface
        self.next_hop_ip = next_hop_address
        self.metric = metric
        self.recursive = None
        self.bypass = None
        self.action = action

        if metric is None:
            self.metric = route_type.value

        # only if needing to override
        self.admin_cost = admin_cost

    def __eq__(self, other):
        if self.prefix != other.prefix:
            return False
        if self.type != other.type:
            return False
        if self.interface != other.interface:
            return False
        if self.metric != other.metric:
            return False

        # Don't care about next hop ip?
        return True

    def __str__(self):
        return f"\t[{self.type}/{self.metric}] to {self.next_hop_ip} via {self.interface}"

    def seq_note(self):
        return self.__str__()

class BGPRoute(Route):

    def __init__(self, prefix, interface, next_hop_address,
                 as_path: list[str],
                 protocol_next_hop: ipaddress.IPv4Address):
        super().__init__(prefix, RouteType.BGP, interface, next_hop_address)
        self.as_path = as_path
        self.protocol_next_hop = protocol_next_hop
        self.recursive = None

    def __str__(self):
        if self.recursive is None:
            return f"\t[{self.type}/{self.metric}] to {self.next_hop_ip} via {self.interface}"
        elif isinstance(self.recursive, RSVPRoute):
            # TODO: CodeSmell! I'm assuming it's an RSVP route, so we need to re-order
            # some of these classes
            return f"\t[{self.type}/{self.metric}] to {self.recursive.next_hop_ip} via {self.recursive.interface}, label-switched-path {self.recursive.lsp_name}"
        else:
            return f"\t[{self.type}/{self.metric}] (pnh: {self.protocol_next_hop}) to {self.next_hop_ip} via {self.recursive.interface}"


class RSVPRoute(Route):

    def __init__(self, prefix, interface, next_hop_address,
                 lsp_name: str, action: LabelStackOperation, metric=None):
        super().__init__(prefix, RouteType.RSVP, interface, next_hop_address, metric=metric)
        self.lsp_name = lsp_name
        self.action = action
        self.bypass = None

    def __str__(self):
        return f"\t[{self.type}/{self.metric}] to {self.next_hop_ip} via {self.interface}, label-switched-path {self.lsp_name}, {self.action}"


class RoutingTables:

    def __init__(self, evt_manager=None, parent_logger=None):

        self.logger = parent_logger.getChild("routing")
        self.event_manager = evt_manager
        self.tables = {}

        self.tables['direct'] = {}
        self.tables['static'] = {}
        self.tables['isis'] = {}
        self.tables['bgp'] = {}

        self.tables['rsvp'] = {}
        self.tables['mpls'] = {}

        # This is basically inet.0
        self.inet = ChainMap(
            self.tables['direct'],
            self.tables['static'],
            self.tables['isis'],
            self.tables['bgp'],
        )

        self.inet3 = ChainMap(
            self.tables['rsvp']
        )

        self.recursive = ChainMap(
            self.tables['rsvp'],
            self.tables['direct'],
            self.tables['static'],
            self.tables['isis']
        )

        self.lsps = self.tables['rsvp']

        self.mpls = ChainMap(
            self.tables['mpls']
        )

    def __str__(self):
        return "routing"

    def table(self, table_name):
        return self.tables[table_name]

    # List of loopback addresses which
    # we will pass through
    def igp_shortest_path(self, dest_ip):
        return []

    def next_hop(self, dest, table='default'):
        # Iterate over the prefixes to find the longest match
        routes = self.tables[table][dest]
        if len(routes) > 0:
            return routes[0]
        else:
            return None

    # For now not assuming ECMP, but thinking will do that via a
    # sub-class called ECMPRoute
    def set_routes(self, routes, table_name, src=None):
        # This is super inefficient, but I like to first
        # write things in a way that makes sense to me
        table = self.tables[table_name]

        # In the case that we are setting the whole thing,
        # we can just clear it
        table.clear()

        visited = {}
        for route in routes:
            prefix = route.prefix

            if prefix not in table:
                self.add_route(route, table_name, src=src)
            else:
                if route in table[prefix]:
                    pass
                else:
                    # hm, should probably just provide mechanism to delete
                    # by the prefix
                    self.del_routes(table[prefix], table_name, src=src)
                    self.add_route(route, table_name, src=src)

            visited[prefix] = True

        prefixes = list(table.keys())
        for prefix in prefixes:
            if prefix not in visited:
                routes = copy(table[prefix])
                for route in routes:
                    self.del_route(route, table_name)

    def del_routes(self, routes, table_name, src=None):
        for route in routes:
            self.del_route(route, table_name, src)

    def del_route(self, route, table_name, src=None):
        prefix = route.prefix

        table = self.tables[table_name]

        if prefix in table:
            table[prefix].remove(route)

            if len(table[prefix]) == 0:
                del table[prefix]

            self.event_manager.observe(
                Event(
                    EventType.ROUTE_CHANGE,
                    src if src is not None else self,
                    f"Deleted {route.type} route to {route.prefix}",
                    object=route,
                    sub_type='ROUTE_DELETED',
                    target=table_name))
        else:
            self.logger.warn(f"{prefix} not in table {table_name}, can't delete")
#            raise Exception("Nothing to delete!")

    def add_route(self, route, table, src=None):
        # there can be multiple entries for same prefix
        # so need them to be prioritized, etc
        # we are doing super simple and assuming no overlap
        prefix = route.prefix
        if table not in self.tables:
            raise(KeyError(f"{table} is not a known table"))

        if prefix not in self.tables[table]:
            self.tables[table][prefix] = [route]

            # May support ECMP route later
            self.event_manager.observe(
                Event(
                    EventType.ROUTE_CHANGE,
                    src if src is not None else self,
                    f"Added {route.type} route to {route.prefix}",
                    object=route,
                    sub_type='ROUTE_ADDED',
                    target=table))

            if table == 'mpls':
                return
        else:
            self.tables[table][prefix].append(route)

        self.tables[table][prefix].sort(key=lambda x: x.metric)


    # Return from one of the tables which can be used to
    # return loopback addresses
    # Which for now we'll assume (incorrectly?) is the
    # only location which protocol next hops can be

    def recursive_lookup_ip(self, ip_address):
        return self.lookup_ip(ip_address, chain=self.recursive)

    def lookup_ip(self, ip_address, chain=None):
        # Right now this is exactly the same as the FIB lookup
        # Need to think about if this makes sense
        if chain is None:
            chain = self.inet

        prefixes = set()
        for table in chain.maps:
            #        for table_name in self.tables:
            prefixes.update(table.keys())

        prefixes = list(prefixes)
        # We keep calling this an address.. but it's acually a network
        # we  want from longest to shortest prefix, then by address
        prefixes = sorted(
            sorted(prefixes,
                   key=lambda address: address.prefixlen
                   ),
            key=lambda address: address.network_address
        )

        prefixes.reverse()

        as_network = ipaddress.ip_network(ip_address)

        route = None
        for prefix in prefixes:
            if as_network.overlaps(prefix):
                if isinstance(chain[prefix], list):
                    route = chain[prefix][0]
                else:
                    route = chain[prefix]

                route = copy(route)
                if route.recursive is not None:
                    route.interface = route.recursive.interface
                        
                # NOTE: This doesn't apply LSPs
                return route

        return None

    def print_routes(self):
        if len(self.inet) > 0:
            print("inet.0\n")
            self._print_routes(self.inet)
            print("\n\n")
        if len(self.inet3) > 0:
            print("inet.3\n")
            self._print_routes(self.inet3)
            print("\n\n")
        if len(self.mpls) > 0:
            print("mpls.3\n")
            self._print_routes(self.mpls)

    def _print_routes(self, chain):
        # Shows all known routes to each location
        # merged together

        prefixes = set()
        for table in chain.maps:
            prefixes.update(table.keys())

        prefixes = list(prefixes)
        prefixes.sort(key=lambda address: address.__str__())

        for prefix in prefixes:
            print(f"{prefix}")
            for table in chain.maps:
                #            for table_name in self.tables:
                #                table = self.tables[table_name]

                routes = table.get(prefix)
                if routes is not None:
                    for route in routes:
                        if route.type == RouteType.BGP:
                            bgproute = deepcopy(route)
                            bgproute.recursive = self.recursive_lookup_ip(bgproute.protocol_next_hop)

                            if bgproute.recursive.interface.is_up():
                                print(bgproute)

                            # This is such spaghetti
                            if bgproute.recursive.bypass is not None:
                                bgproute.recursive = bgproute.recursive.bypass
                                if bgproute.recursive.interface.is_up():
                                    print(bgproute)
                        elif route.interface.is_up():
                            print(route)

    # Generate the forwarding table, by taking a single
    # instance of each prefix

    def forwarding_table(self):
        fib = {
            FrameType.IPV4: OrderedDict(),
            FrameType.MPLSU: OrderedDict()
        }

        ipfib = fib[FrameType.IPV4]
        mplsfib = fib[FrameType.MPLSU]

        have_default = False
        default = ipaddress.ip_network("0.0.0.0/0")
        prefixes = set()
#        for table_name in self.tables:
        for table in self.inet.maps:
            prefixes.update(table.keys())

        prefixes = list(prefixes)
        # We keep calling this an address.. but it's acually a network
        # we  want from longest to shortest prefix, then by address
        prefixes = sorted(
            sorted(prefixes,
                   key=lambda address: address.prefixlen
                   ),
            key=lambda address: address.network_address
        )

        prefixes.reverse()

        for prefix in prefixes:
            if prefix == default:
                have_default = True

            applied_prefix = False
            for route in self.inet.get(prefix):

                if route.type == RouteType.LOCAL:
                    # TODO: We could also install it to send out over a
                    #  private special interface
                    # .. which is really where we are moving to
                    ipfib[prefix] = ForwardingEntry(
                        prefix, route.interface, action='CONTROL')
                    applied_prefix = True
                elif route.type == RouteType.BGP:
                    recursive_route = self.recursive_lookup_ip(route.protocol_next_hop)
                    if recursive_route is None:
                        self.logger.info(f"Unable to lookup pnh for {route}, will be hiding")
                        continue
                        
                    if recursive_route.interface.is_up():
                        ipfib[prefix] = ForwardingEntry(
                            prefix, recursive_route.interface, recursive_route.action)
                        applied_prefix = True
                    elif recursive_route.bypass is not None and recursive_route.bypass.interface.is_up():
                        ipfib[prefix] = ForwardingEntry(
                            prefix, recursive_route.bypass.interface,
                                CombinedAction([recursive_route.action, recursive_route.bypass.action]))
                else:
                    ipfib[prefix] = ForwardingEntry(prefix, route.interface)
                    applied_prefix = True

                # This route isn't hidden
                if applied_prefix:
                    break

        if not have_default:
            # now add a default UNREACHABLE
            ipfib[default] = ForwardingEntry(default, None, action='REJECT')

        for label in self.mpls:
            route = self.mpls[label][0]

            action = route.action

            iface = route.interface
            if route.interface is None:
                print(route)
            if not route.interface.is_up() and route.bypass is not None:
                action = CombinedAction([route.action, route.bypass.action])
                iface = route.bypass.interface

            mplsfib[label] = ForwardingEntry(
                label, iface, action=action
            )
        return fib
