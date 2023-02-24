from ..mpls import PopStackOperation, PushStackOperation, ReplaceStackOperation
from .object import IPV4SenderTemplate, Session, LSPTunnelSessionAttribute, FilterSpec
from .pdu import Path, Resv
from copy import copy, deepcopy
from ..observers import GlobalQueueManager, Event, EventType
from ..messaging import IPProtocol
from ..routing import RSVPRoute, RouteType
import random
import pprint
import functools
import sys
from ipaddress import IPv4Address, ip_network
from scapy.layers.inet import IP,IPOption_Router_Alert

# https://www.juniper.net/documentation/en_US/release-independent/nce/topics/example/mpls-lsp-link-protect-solutions.html
# https://www.juniper.net/documentation/en_US/release-independent/nce/topics/concept/mpls-lsp-node-link-protect-overview-solutions.html


class PathStateBlock():
    def __init__(self, path: Path, type='standard', bypassed=None):
        self.hop = path.hop.hop_address
        self.sender = copy(path.sender)
        self.session = copy(path.session)
        self.attributes = path.attributes
        self.label = None

        # bypass or standard
        self.type = type
        self.bypassed = bypassed
        self.route = None


class ResvStateBlock():
    def __init__(self, resv: Resv):
        self.resv = copy(resv)
        self.session = resv.session
        self.hop = resv.hop.hop_address
        # flowspec


class RsvpSession:
    def __init__(self, source_ip, dest_ip, lsp_name, lsp_id, protected_ip=None):
        self.source_ip = source_ip
        self.dest_ip = dest_ip
        self.lsp_name = lsp_name
        self.last_send = 0
        self.lsp_id = lsp_id
        self.protected_ip = protected_ip

        self.session = Session.newSession(dest_ip, source_ip)
        self.paths = []

        firstpath = Path(
            self.session,
            sender=IPV4SenderTemplate(source_ip, self.lsp_id),
            attribute=LSPTunnelSessionAttribute(lsp_name)
        )
        self.paths.append(firstpath)


class RsvpProcess:

    def __init__(self, event_manager, router, source_ip):
        self.event_manager = event_manager
        self.router = router
        self.source_ip = source_ip
        self.started = False
        self.path_state = {}
        self.resv_state = {}
        self.logger = self.router.logger.getChild("rsvp")
        self.lsp_id = 1

        self.current_label = random.randint(100, 500)

        # set of known sessions requestev via Path messages
        self.sessions = []

    def __refresh_paths(self):
        if not self.started:
            return

        for session in self.sessions:
            path_msg = session.paths[0]
            exclude_ip = session.protected_ip

            psb = self.path_state.get(path_msg.key())
            if psb is None:
                # For now we aren't really doing refreshes
                ero = self.shortest_path(session.dest_ip, exclude_ip=exclude_ip)
                if ero is None or len(ero) == 0:
                    self.logger.warn(f"No path available for {path_msg.attributes.name} from {self.router.hostname}")
                    continue
                else:
                    route = self.router.routing.lookup_ip(ero[0])

                for entry in ero:
                    path_msg.add_explicit(entry)

                path_msg.set_hop(route.interface.address().ip)
                path_msg.add_record(route.interface.address().ip)


                packet = IP(
                    dst=session.dest_ip,
                    src=session.source_ip,
                    protocol=IPProtocol.RESV,
                    options=IPOption_Router_Alert(),
                ) / path_msg

                #packet = IPPacket(session.dest_ip,
                #                  session.source_ip,
                #                  IPProtocol.RSVP,
                #                  path_msg, router_alert=True)
                self.event_manager.observe(Event(
                    EventType.RSVP, self, f"Send Path message for LSP", object=path_msg, sub_type="SEND_PATH"))

                # TODO: Is this even right... ?
                type = 'standard'
                if exclude_ip is not None:
                    type = 'bypass'
                self.path_state[path_msg.key()] = PathStateBlock(path_msg, type=type, bypassed=exclude_ip)
                self.router.send_ip(packet, source_interface=route.interface)

    def create_session(self, dest_ip, lsp_name, link_protection=False, protected_ip=None):

        for session in self.sessions:
            if session.lsp_name == lsp_name:
                self.logger.info(f"Alreday have {lsp_name}, stopping")
                return session

        self.lsp_id = self.lsp_id + 1
        session = RsvpSession(self.source_ip, dest_ip, lsp_name, self.lsp_id, protected_ip=protected_ip)
        session.paths[0].attributes.local_repair = link_protection

        self.sessions.append(session)

        self.__refresh_paths()
        return session


    def shortest_path(self, dest_ip, exclude_ip=None):
        self.logger.info(f"SFP Starting for {dest_ip}, excluding {exclude_ip}")
        originaldb = self.router.process['isis'].database
        ted = {}
        # For now, we're using the isis process
        # for our source for the TED
        # This would run a Constrained Shortest Path First
        # in case that there were other constraints in play
        # Really want to have it avoid the ISIS-specific stuff

        # The final calculated distance to each prefix
        distance = {}

        # Calculated distance to each system, most useful for debugging
        system_distance = {}

        # linked list of paths from the destination back to us
        prev = {}

        # linked list of paths from another system back to us over shortest path
        prev_system = {}

        # Remaining LSPs we need to process
        queue = []

        # https://en.wikipedia.org/wiki/Dijkstra%27s_algorithm
        dbvalues = sorted(
            originaldb.values(),
            key=lambda lsp: lsp.pdu.source_address)

        for wrapper in dbvalues:
            lsp = wrapper.pdu

            router_id = lsp.routerid
            ted[router_id] = lsp

#            entry_node = lsp.source_address
            entry_node = router_id
            # Note the shortcut we're taking of treating the lsp_id as the system_id
            system_distance[entry_node] = sys.maxsize
            prev_system[entry_node] = None
            # queue.append(lsp.source_address)
            queue.append(router_id)

        #system_id = self.router.process['isis'].system_id
        system_distance[self.source_ip] = 0

        done = False
        while len(queue) > 0 and not done:

            # find shortest element
            min_idx = 0
            min_dist = sys.maxsize
            for i in range(len(queue)):
                if system_distance[queue[i]] < min_dist:
                    min_idx = i
                    min_dist = system_distance[queue[i]]

            node = queue.pop(min_idx)

            self.logger.info(f"SPF processing {node}")
            lsp = ted[node]

            neighbors = lsp.neighbors

            for neigh in neighbors:
                og_neigh_id = neigh.system_id
                neigh_id = originaldb[og_neigh_id].pdu.routerid

                if neigh_id == self.source_ip:
                    self.logger.info(f"Skipping self neighbor")
                    continue

                metric = neigh.metric

                if exclude_ip is not None and neigh.neighbor_ip == exclude_ip:
                    self.logger.info(
                        f"Skipping {neigh} as it referencees IP we are excluding")
                    continue
                if exclude_ip is not None and neigh.local_ip == exclude_ip:
                    self.logger.info(
                        f"Skipping {neigh} as it referencees IP we are excluding")
                    continue

                self.logger.info(f"processing {neigh_id} neighbor of {node}")
                if neigh_id not in system_distance:
                    self.logger.info(f"ignoring due to {neigh_id}")
                    # We haven't actually converged
                    return None

                new_dist = system_distance[node] + metric

                if new_dist < system_distance[neigh_id]:
                    system_distance[neigh_id] = new_dist
                    self.logger.info(
                        f"SPF distance to {neigh_id} is {new_dist}, via {lsp.routerid}")
                    #prev_system[neigh_id] = lsp.source_address
                    prev_system[neigh_id] = lsp.routerid

            # Now deal with our routable prefixes
            for network in lsp.addresses:
                address = network.prefix
                metric = network.metric

                if str(network.state) != 'UP':
                    self.logger.debug(f"Skipping {network} as it is not up")
                    continue

                if exclude_ip is not None and address.overlaps(ip_network(exclude_ip)):
                    self.logger.info(f"Skipping {address}")
                    continue

                new_dist = system_distance[node] + metric

                existing_metric = distance.get(address)
                if existing_metric is None or existing_metric > new_dist:
                    distance[address] = new_dist
                    #prev[address] = lsp.source_address
                    prev[address] = lsp.routerid
                    self.logger.info(
                        f"SPF set prev for {address} to {lsp.routerid}")
#                if address.overlaps(ip_network(dest_ip)):
#                    done = True
        # right now this is super ghetto, as we have a list of system ids
        # we're going to walk that to get the interface ips
        address_paths = {}
        system_paths = {}

        def resolve_path(cur_elem):
            the_path = []
            while cur_elem is not None:
                if cur_elem != self.source_ip:
                    the_path.append(cur_elem)
                cur_elem = prev_system.get(cur_elem)
            return the_path

        for address in prev:
            path_elem = prev[address]
            this_path = resolve_path(path_elem)
            address_paths[address] = this_path
            address_paths[address].reverse()

        for loopbackip in prev_system:
            this_path = []

            path_elem = prev_system.get(loopbackip)
            this_path = resolve_path(path_elem)
            system_paths[loopbackip] = this_path
            system_paths[loopbackip].reverse()


#        print(f"Hunting for shortest path to {dest_ip}")
        ero = []
        from_entry = self.source_ip

        #system_path = address_paths[ip_network(dest_ip)]
        if dest_ip not in system_paths:
            return None
        system_path = system_paths[dest_ip]

        for loopbackip in system_path:
            from_lsp = ted[from_entry]

            for neighbor in from_lsp.neighbors:
                neigh_router_id = originaldb[neighbor.system_id].pdu.routerid
                if neigh_router_id == loopbackip:
                    target_ip = neighbor.neighbor_ip
                    self.logger.debug(
                        f"\tTo reach {loopbackip}, assuming address is {target_ip}")
                    ero.append(target_ip)
            from_entry = loopbackip
        if from_entry is not None:
            from_lsp = ted[from_entry]

            for neighbor in from_lsp.neighbors:
                neigh_router_id = originaldb[neighbor.system_id].pdu.routerid
                if neigh_router_id == dest_ip:
                    target_ip = neighbor.neighbor_ip
                    self.logger.debug(
                        f"\tTo reach {loopbackip}, assuming address is {target_ip}")
                    ero.append(target_ip)

        return ero

    def start(self):
        if self.started:
            return

        GlobalQueueManager.enqueue(random.randint(0, 5), self.__refresh_paths)
        self.started = True

    # def send(self, packet):
    #    self.router.send_ip(packet)

    def _process_path(self, interface, packet):
        pdu = packet.pdu

        self.logger.info(f"{self.router.hostname} Received RSVP Path message on {interface.address().ip} {packet}, hop={pdu.hop.hop_address} for {pdu.attributes.name}")
        # this is ghetto style, we basically need to just
        # know if it's any of our IPs
        if packet.dest_ip == self.source_ip:
            self.logger.debug(f"{self.router.hostname} path is for us")
            resv = Resv(
                pdu.session,
                filter=FilterSpec(pdu.sender.address, pdu.sender.lsp_id)
            )

            packet = IP(
                dst=pdu.hop.hop_address,
                src=interface.address().ip,
                protocol=IPProtocol.RSVP) / resv
            resv.set_label(3)  # Implicit null
            resv.set_hop(packet.source_ip)

            self.logger.info(f"Issuing RSVP Resv message to {packet.dest_ip} from {packet.source_ip}")

            self.router.send_ip(packet)

            return

        # In real life we would reserve the requested bandwidth
        if pdu.key() in self.path_state:
            self.logger.info("Already have PATH STATE for {pdu.key}")
        self.path_state[pdu.key()] = PathStateBlock(pdu)

        found = False
        iface_address = None
        route = None


        ero_entry = pdu.explicit_route.pop(0)
        addr = ero_entry.route
        self.logger.info(f"Checking {addr}")
        if addr == interface.address().ip:
            # we've made it to us, the next one is where we want to send it
            found = True
        if found and len(pdu.explicit_route) > 0:
            # The next item should be our downstream
            route = self.router.routing.lookup_ip(pdu.explicit_route[0].route)
            iface_address = route.interface.address().ip
        elif found:
            route = self.router.routing.lookup_ip(packet.dest_ip)
            iface_address = route.interface.address().ip
        else:
            self.logger.warn(f"Did not find ourselves in the ERO {addr} != {interface.adress().ip}")
            raise Exception("Did not ourselves in the ERO")

        pdu.set_hop(iface_address)
        pdu.add_record(iface_address)
        self.event_manager.observe(Event(
            EventType.RSVP, self, f"Processed Path mesasge", object=pdu, sub_type="PROCESS_PATH"))
        self.router.send_ip(packet, source_interface=route.interface)

    def _process_resv(self, interface, packet):
        assert interface is not None
        resv = packet.pdu  # Resv

        rsb = self.resv_state.get(resv.key())
        if rsb is None:
            rsb = ResvStateBlock(resv)
            self.resv_state[resv.key()] = rsb


        self.event_manager.observe(Event(
            EventType.RSVP, self, f"Processed Resv mesasge", object=resv, sub_type="PROCESS_RESV"))

        psb = None
        # TODO: The descriptions of the key into the
        # path state aren't clear
        for key in self.path_state:
            path_info = self.path_state[key]
            if (path_info.session.dest_ip == resv.session.dest_ip and
                path_info.session.tunnel_id == resv.session.tunnel_id and
                path_info.sender.address == resv.filter.address and
                    path_info.sender.lsp_id == resv.filter.lsp_id):
                psb = path_info
                break

        if psb is None:
            self.logger.info(f"Received RESV mesage {resv} with no corresponding PSB!")
            return

        self.logger.debug(f"{self.router.hostname} Received RSVP RESV message on {interface.address().ip} {packet}, hop={resv.hop.hop_address}, for {psb.attributes.name}")
        label = resv.label
        psb.label = label

        action = None
        if label == 3:
            action = PopStackOperation()
        else:
            action = ReplaceStackOperation(label)

        route = self.router.routing.lookup_ip(psb.hop)
        our_ip = route.interface.address().ip
        resv.add_record(interface.address().ip)

        if resv.filter.address == self.source_ip:
            self.logger.debug("{self.router.hostname} this was our Request")
            # Its made it back to our own session
            # in the case of 3 its a bit weird and maybe
            # should instead be one of the others
            action = PushStackOperation(label)
            # This fields weird, adding the routes twice
            # that's definitely wrong
            newroute = RSVPRoute(
                ip_network(str(psb.session.dest_ip) + "/32"),
                interface,
                resv.hop.hop_address,
                lsp_name=psb.attributes.name,
                action=action,
                metric=RouteType.RSVP.value if psb.type == 'standard' else RouteType.RSVP.value+1
            )
            # ????
            psb.route = newroute

            if psb.type == 'standard':
                self.router.routing.add_route(newroute, 'rsvp')
            else:
                route_table = self.router.routing.tables['rsvp']

                # TODO: This whole thing is terribly, really we need to just have the bypass
                # available for later lookup
                # Or even better associate it directly
                for routes in route_table.values():
                    for route in routes:
                        if route.next_hop_ip == psb.bypassed:
                            route.bypass = newroute
                            self.event_manager.observe(Event(
                                EventType.RSVP, self, f"Added RSVP bypass route", object=newroute, sub_type="BYPASS_INSTALLED"))

                for routes in self.router.routing.tables['mpls'].values():
                    for route in routes:
                        if route.next_hop_ip == psb.bypassed:
                            route.bypass = newroute
                            self.event_manager.observe(Event(
                                EventType.RSVP, self, f"Added MPLS bypass route", object=newroute, sub_type="BYPASS_INSTALLED"))

                for psbinfo in self.path_state.values():
                    if newroute.next_hop_ip == psbinfo.bypassed:
                        newroute.bypass = psbinfo.route

        else:
            if our_ip == psb.hop:
                self.logger.error(f"Apparenty routing loop, {our_ip} is {psb.hop} {psb.attributes.name}")
                raise Exception(f"Routing loop detected! ")

            # Now we set up our own label that we'll convey downstream
            # Do we still do this during refreshes?
            next_label = self.current_label
            self.current_label += 10
            # TODO: It should be safe to put this where we have BGP routes

            rsvproute = RSVPRoute(
                    str(next_label),
                    interface,
                    resv.hop.hop_address,
                    lsp_name=psb.attributes.name,
                    action=action
                )
            for psbinfo in self.path_state.values():
                if rsvproute.next_hop_ip == psbinfo.bypassed:
                    rsvproute.bypass = psbinfo.route

            self.router.routing.add_route(
                rsvproute,
                'mpls'
            )

            self.event_manager.observe(Event(
                EventType.RSVP, self, f"Reserved new label {next_label}", object=next_label, sub_type="Reserved label"))

            resv.set_label(next_label)
            resv.set_hop(our_ip)
            # Fire it off downstream from wherever we got it
            if psb.hop == our_ip:
                self.logger.warn(f"Invalid self-RESV {resv.filter.address}, {self.source_ip}")
                return
            packet = IP(
                dst=psb.hop,
                src=our_ip, protocol=IPProtocol.RSVP) / resv
            self.logger.info(packet)
            self.logger.info(f"When sending RESV, using interface {route.interface}")
            self.logger.debug(f"{self.router.hostname} forwarding RESV via {route.interface.name} to {psb.hop} for {psb.attributes.name}")
            self.router.send_ip(packet, source_interface=route.interface)

        # if the ingress requested local repair
        # we are going to set up a Bypass path
        # round the next element in the path
        # Note that the bypass is able to protect multiple
        # LSPs as it's actually protecting the interfac3
        if psb.attributes.local_repair:
            next_hop_ip = rsb.hop

            for _, interface in self.router.interfaces.items():
                if (
                    not interface.is_physical() and
                    interface.address().ip == next_hop_ip
                    ):
                    return
            # TODO: What's the best way to figure out the best way to
            # find the node by its loop back. Is that traffic
            # engineering router id?

            GlobalQueueManager.enqueue(
                0,
                functools.partial(self._create_bypass_lsp,
                                  route.interface, next_hop_ip)
            )

    # Create an LSP

    def _create_bypass_lsp(self, protected_interface, protected_ip: IPv4Address):
        # Note: In real life we can derive the interface/ips to exclude fromthe
        # TED. But baby steps

        # We are assuming that the excluded is an interface address
        # of a system that we still want to reach (so just doing link bypass)
        self.logger.info(f"Creating Bypass session to {protected_ip}")

        ted = self.router.process['isis'].database

        router_id = None
        for lspid in ted:
            lsp = ted[lspid].pdu

            for neighbor in lsp.neighbors:
                if neighbor.local_ip == protected_ip:
                    # we are ssuming router_id = loopback/destination
                    router_id = lsp.routerid

        if router_id is None:
            self.logger.warn(
                f"Unable to create bypass for {protected_ip}, unable to find router")

        session_name = f"Bypass->{protected_ip} ({self.router.hostname})"

        self.create_session(router_id, session_name, link_protection=True, protected_ip=protected_ip)


    def process_packet(self, interface, packet):
        pdu = packet.pdu

        if isinstance(pdu, Path):
            self._process_path(interface, packet)
        elif isinstance(pdu, Resv):
            self._process_resv(interface, packet)
