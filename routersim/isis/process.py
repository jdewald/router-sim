from ..observers import GlobalQueueManager, Event, EventType
from ..routing import Route, RouteType
from ..interface import ConnectionState
from .pdu import LinkStatePDU, P2PHelloPDU, CSNPPDU, PSNPPDU
from .tlv import *
import random
import sys
import logging
import pprint
from copy import deepcopy

# Intermediate-System to Intermediate-System
# ISO/IEC 10589
# http://standards.iso.org/ittf/PubliclyAvailableStandards/c030932_ISO_IEC_10589_2002(E).zip
# RFC 1195 adds IP handling (https://tools.ietf.org/html/rfc1195)
# At this time, only point-to-point is implemented
# RFC 5305 for TE


class LSPNeighborEntry:
    def __init__(self, address, metric, our_address):
        self.address = address
        self.metric = metric
        self.our_address = our_address

    def __str__(self):
        return f"{self.address}[{self.metric}] as {self.our_address}]"


class LSPIPEntry:
    def __init__(self, ip_prefix, metric, state='UP'):
        self.ip_prefix = ip_prefix
        self.metric = metric
        self.state = state

    def __str__(self):
        return f"{self.ip_prefix}[{self.metric}]({self.state}"


class Neighbor:
    def __init__(self, system_id, iface):
        self.system_id = system_id
        self.interface_name = iface
        self.state = 'Initializing'
        self.name = '<Unknown>'
        self.level = 1
        self.metric = 10

    def __str__(self):
        return f"{self.system_id}({self.name})"


class LinkStatePacketWrapper:
    def __init__(self, source_pdu, remaining_lifetime=1200):
        self.pdu = source_pdu
        self.remaining_lifetime = remaining_lifetime
#        self.system_id = system_id
        # Transitionary, we really should just store the PDU as the entry..
#        self.source_pdu = source_pdu
#        self.circuit_id = circuit_id
#        self.lsp_num = lsp_num
#        self.seq_no = seq_no

        self.last_sent = 0

        self.neighbors = []
        self.addresses = []

        # Send Routing Messaging - LSPs we think others need
        self.srms = {}

        # Send Sequence Numbers - LSPs that we want
        self.ssns = {}
        self.hostname = None

    def __str__(self):
        return str(self.pdu)

    def extensive(self):
        return self.pdu.extensive()

    @property
    def seq_no(self):
        return self.pdu.seq_no

    def increment_seq(self):
        self.pdu.seq_no += 1

    def set_srm(self, ifacename):
        self.srms[ifacename] = True

    def clear_srm(self, ifacename):
        self.srms.pop(ifacename, None)

    def set_ssn(self, ifacename):
        self.ssns[ifacename] = True

    def clear_ssn(self, ifacename):
        self.ssns.pop(ifacename, None)


class IsisProcess:

    def __init__(self, event_manager, hostname, routing):
        self.hostname = hostname
        self.started = False
        self.adjacencies = {}
        self.neighbors = {}  # shortcut
        self.interfaces = {}
        self.database = {}
        self.event_manager = event_manager
        self.routing = routing
        self.hello_interval = 3 * 1000
        self.partial_snp_interval = 100  # TODO: complete_snp_interval?
        self.minimum_lsp_interval = 100

        self.logger = logging.getLogger(f"{hostname}.ISIS")
#        self.logger.setLevel('INFO')

        self.hostmapping = {}

        self.spf_pending = False

        # TED
        self.address_paths = None

    def __str__(self):
        return "ISIS"
    # A passive interface will be advertised into ISIS, but
    # won't be used to form adjacencies

    def enable_interface(self, interface, passive=False, metric=10, p2p=True):
        self.interfaces[interface.name] = {
            'interface': interface,
            'active': not passive,
            'metric': metric,
            'point-to-point': p2p
        }
        self.adjacencies[interface.name] = {}
        self.event_manager.observe(Event(
            EventType.ISIS, self, f"ADD_INTERFACE ({interface.name}->{passive})", object=self.interfaces[interface.name], sub_type="INTERFACE_ADD"))

    def __send_hello(self):
        # TODO: This would be on a timer
        for ifacename in self.interfaces:
            if self.interfaces[ifacename]['active']:
                iface = self.interfaces[ifacename]['interface']
                if not iface.is_up():
                    continue
                # On active interfaces we periodically send out
                # Hello PDUs to establish/maintain this adjancency
                if self.interfaces[ifacename]['point-to-point']:
                    hello = P2PHelloPDU(self.system_id)

                    hello.tlvs.append(AreaAddressTLV(self.area_id))
                    hello.tlvs.append(IPAddressTLV(
                        self.interfaces['lo.0']['interface'].address()))

                    for neighbor_id in self.adjacencies[ifacename]:
                        neighbor = self.adjacencies[ifacename][neighbor_id]
                        if neighbor.state == 'NEW' or neighbor.state == 'DOWN':
                            neighbor.state = 'Initializing'
                        hello.tlvs.append(P2PAdjacencyTLV(
                            neighbor.system_id, neighbor.state))

                    iface.send_clns(hello)

        GlobalQueueManager.enqueue(random.randint(
            self.hello_interval-1, self.hello_interval+1), self.__send_hello)

    def __send_complete_snp(self, interface_name=None):
        self.logger.debug(f"Request to send CSNP via {interface_name}")
        cnsp = CSNPPDU(self.system_id)

        # Note that we're fudging this a bit and just using
        # the system_id as the full id
        for lsp in self.database.values():
            cnsp.tlvs.append(LSPEntryTLV(
                lsp.pdu.lsp_id, lsp.seq_no, lsp.remaining_lifetime, hostname=lsp.hostname))

            # In real life these are sorted by the numeric value of the systemid
            cnsp.tlvs.sort(key=lambda entry: entry.lsp_id)

        # TODO: add a helper method to send pack on the IS-IS active interfaces
        for ifacename in self.interfaces:
            if (interface_name is None or ifacename == interface_name) and self.interfaces[ifacename]['active']:
                iface = self.interfaces[ifacename]['interface']
                self.logger.debug(f"Sending CSNP via {ifacename}")
                if iface.is_up():
                    iface.send_clns(cnsp)

    def __send_partial_snps(self):

        self.logger.debug("Sending Partial SNPs")
        for ifacename in self.adjacencies:
            if len([neigh for neigh in self.adjacencies[ifacename].values() if neigh.state == 'UP']) > 0:

                # ssn gets cleared when we hear about it
                candidateids = [lspid for lspid in self.database if self.database[lspid].ssns.get(
                    ifacename) is not None]

                if len(candidateids) > 0:
                    psnp = PSNPPDU(self.system_id)

                    for lspid in candidateids:
                        lsp = self.database[lspid]
                        psnp.tlvs.append(LSPEntryTLV(
                            lsp.pdu.lsp_id, lsp.seq_no, lsp.remaining_lifetime, hostname=lsp.hostname))
                        # TODO: sort by something actually reasonable
                        psnp.tlvs.sort(key=lambda entry: entry.lsp_id)
                        self.logger.debug(
                            f"Added {lspid} to PSNP to through {ifacename}")
                        lsp.clear_ssn(ifacename)

                    iface = self.interfaces[ifacename]['interface']
                    if iface.is_up():
                        iface.send_clns(psnp)
                else:
                    self.logger.debug(
                        "SSN list is empty, don't need to send anything")
        GlobalQueueManager.enqueue(random.randint(
            self.partial_snp_interval-1, self.partial_snp_interval+1), self.__send_partial_snps)

    # Send LSPs on all circuits which have been flagged with SRM
    # TODO: There is a bug where we are sending LSPs before they are requested
    # Maybe that's fine for new ones?
    def __send_lsps(self):
        for lspid in self.database:
            lsp = self.database[lspid]

            if len(lsp.srms) > 0:
                pdu = lsp.pdu

                # TODO: See what's in Sub-TLV Traffic Engineering Metric
                for ifacename in lsp.srms:
                    if len([neigh for neigh in self.adjacencies[ifacename].values() if neigh.state == 'UP']) > 0:
                        if self.interfaces[ifacename]['interface'].is_up():
                            self.interfaces[ifacename]['interface'].send_clns(pdu)

        GlobalQueueManager.enqueue(random.randint(
            self.minimum_lsp_interval-1, self.minimum_lsp_interval+1), self.__send_lsps)

    def __neighbor(self, iface_name, addr):
        if iface_name not in self.adjacencies:
            self.logger.warn(
                f"Received packet on {iface_name}, but IS-IS not enabled")
            return None
        neighbor = self.adjacencies[iface_name].get(addr)
        if neighbor is None:
            neighbor = Neighbor(addr, iface_name)
            # We really know nothing about them
            neighbor.state = 'NEW'

            self.adjacencies[iface_name][addr] = neighbor
            # TODO: There could in fact be multiple at some point, but for now
            # doing 1:1,
            self.neighbors[addr] = neighbor
        return neighbor

    """
  7.3.6 Event driven LSP Generation
In addition to the periodic generation of LSPs, an Intermediate system shall generate an LSP when an event occurs which would cause the information content to change. The following events may cause such a change.
- an Adjacency or Circuit Up/Down event
- a change in Circuit metric
- a change in Reachable Address metric
- a change in manualAreaAddresses
- a change in systemID
- a change in Designated Intermediate System status
- a change in the waiting status
- creation or delete of a virtual circuit
- a changed of AttachedFlag
  """

    def __refresh_local(self):
        if not self.started:
            return
        wrapper = self.database.get(self.system_id)
        changed = False
        new = False
        up_interfaces = []
        lsp = None
        if wrapper is None:
            lsp = LinkStatePDU(self.system_id, self.system_id, 1)
            wrapper = LinkStatePacketWrapper(lsp)

            lsp.tlvs.append(DynamicHostnameTLV(self.hostname))
            lsp.tlvs.append(TrafficEngineeringIPRouter(self.interfaces['lo.0']['interface'].address().ip))
            self.database[self.system_id] = wrapper

            new = True
        else:
            lsp = wrapper.pdu

        for ifacename in self.interfaces:
            neighbors = self.adjacencies[ifacename]

            metric = self.interfaces[ifacename]['metric']

            iface = self.interfaces[ifacename]['interface']
            network = iface.address('ipv4').network

            # This is slow, but I wanted to store it as array
            # We don't really expect there to be many items
            for neighborid in neighbors:

                neigh = neighbors[neighborid]
                found = False

                if not iface.is_up() and neigh.state != 'DOWN':
                    neigh.state = 'DOWN'
                    self.event_manager.observe(Event(
                        EventType.ISIS, self, f"Mark ({neigh})->DOWN", 
                        object=neigh, sub_type="ADJ_CHANGE"))
                elif iface.is_up():
                    up_interfaces.append(ifacename)

                if neigh.state == 'DOWN':
                    if lsp.remove_neighbor(neighborid):
                        changed = True
                        continue
                else:
                    for lspneigh in lsp.neighbors:
                        if lspneigh.system_id == neighborid:
                            found = True
                            if lspneigh.metric != metric:
                                lspneigh.metric = metric
                                changed = True

                if not found and neigh.state != 'DOWN':
                    tlv = ExtendedISReachabilityTLV(neighborid, metric) 
                    lsp.tlvs.append(tlv)
                    tlv.tlvs.append(IPInterfaceAddressTLV(
                        iface.address('ipv4').ip, iface.state))

                    # TODO: How do we actually get the neighbor's address?
                    # for now, we'll assume point-to-point
                    net = iface.address('ipv4').network
                    for ip in net.hosts():
                        if ip != iface.address('ipv4').ip:
                            tlv.tlvs.append(NeighborIPAddressTLV(ip))
                            break
                        changed = True


            found = False
            for lspip in lsp.addresses:
                if lspip.prefix == network:
                    found = True
                    if lspip.metric != metric:
                        lspip.metric = metric
                        changed = True
                    if lspip.state != iface.state:
                        lspip.state = iface.state
                        changed = True
            if not found:
                tlv = ExtendedIPReachabilityTLV(network, metric, iface.state)

                lsp.tlvs.append(tlv)

#        lsp.addresses.sort(key=lambda network: network.ip_prefix)
#        lsp.neighbors.sort(key=lambda neighbor: neighbor.address)
        if changed:
            wrapper.increment_seq()
            for ifacename in up_interfaces:
                wrapper.set_srm(ifacename)

            if not self.spf_pending:
                GlobalQueueManager.enqueue(200, self.run_full_dijkstra)

    def process_hello(self, recv_interface, pdu):
        other_address = pdu.source_address

        # Really this is just for comparing our Areas
        # We would ignore messages from those that don't match ours
        # address_tlv = [tlv for tlv in pdu.tlvs if isinstance(tlv, AreaAddressTLV)][0]
        neighbor = self.__neighbor(recv_interface.name, other_address)

        # Should only happen if message comes on interface not enabled for IS-IS
        if neighbor is None:
            return

        ip_tlvs = [tlv for tlv in pdu.tlvs if isinstance(tlv, IPAddressTLV)]
        for ip in ip_tlvs:
            # just assuming single one for now
            neighbor.address = ip.address

        adj_tlvs = [tlv for tlv in pdu.tlvs if isinstance(
            tlv, P2PAdjacencyTLV)]
        for tlv in adj_tlvs:
            if tlv.system_id == self.system_id:
                # yay, we see ourselves, which means they've gotten our packets
                if tlv.state == 'UP' or tlv.state == 'Initializing':
                    if neighbor.state != 'UP' and not neighbor.state == 'NEW':
                        neighbor.state = 'UP'
                        neighbor.interface_name = recv_interface.name
                        self.neighbors[neighbor.system_id] = neighbor

                        self.event_manager.observe(Event(
                            EventType.ISIS, self, f"Mark ({neighbor})->UP", object=neighbor, sub_type="ADJ_CHANGE"))
                        self.__refresh_local()

                        GlobalQueueManager.enqueue(
                            1, self.__send_complete_snp, arguments=(recv_interface.name,))

                    elif neighbor.state == 'NEW':
                        neighbor.state = 'Initializing'
                        # TODO: Just encode this instead in neighbor.set_state()
                        self.event_manager.observe(Event(
                            EventType.ISIS, self, f"Mark ({neighbor})->Initializing", object=neighbor, sub_type="ADJ_CHANGE"))

    # 7.3.15.2 Action on receipt of a sequence numbers PDU of ISO/IEC 10589
    def process_snp(self, recv_interface, pdu):
        seen = []
        for tlv in pdu.tlvs:
            # should only be linkstate entries
            lsp = self.database.get(tlv.lsp_id)
            seen.append(tlv.lsp_id)
            if lsp is None:
                newlsp = LinkStatePacketWrapper(
                    LinkStatePDU(tlv.lsp_id, tlv.lsp_id, 0))
                self.database[tlv.lsp_id] = newlsp
                newlsp.set_ssn(recv_interface.name)
                newlsp.clear_srm(recv_interface.name)
            elif lsp.seq_no == tlv.seq_no:
                lsp.clear_srm(recv_interface.name)
            elif lsp.seq_no > tlv.seq_no:  # older
                # we need to let them know about our new and shinier version
                lsp.set_srm(recv_interface.name)
                lsp.clear_ssn(recv_interface.name)
            else:  # newer
                lsp.set_ssn(recv_interface.name)
                # TODO: IF we do broadcast handling, this changes
                lsp.clear_srm(recv_interface.name)

    # 7.3.15.1 Action on receipt of a link state PDU
    def process_lsp(self, recv_interface, pdu):

        if len([neigh for neigh in self.adjacencies[recv_interface.name].values() if neigh.state == 'UP']) < 1:
            self.logger.debug(
                f"Received LSP on {recv_interface}, but do not have UP neighbor, ignoring")
            return
        lsp = self.database.get(pdu.lsp_id)
        if lsp is None or lsp.seq_no < pdu.seq_no:
            lsp = LinkStatePacketWrapper(deepcopy(pdu))
#            lsp = LinkStatePacket(pdu.lsp_id, deepcopy(pdu), seq_no=pdu.seq_no)

            self.database[pdu.lsp_id] = lsp
            self.event_manager.observe(Event(
                EventType.ISIS, self, f"Added LSP Entry {pdu.lsp_id}(seq={pdu.seq_no})", object=lsp, sub_type="LSP_ADDED"))

            if not self.spf_pending:
                GlobalQueueManager.enqueue(200, self.run_full_dijkstra)


            for ifacename in self.interfaces:
                if self.interfaces[ifacename]['active']:
                    # We want to let everyone else know about this
                    lsp.set_srm(ifacename)
                    if ifacename != recv_interface.name:
                        lsp.clear_ssn(ifacename)

            lsp.clear_srm(recv_interface.name)
            # So we can send this in PSNP
            # TODO: This would only be on point-to-point links
            lsp.set_ssn(recv_interface.name)
        elif lsp.seq_no == pdu.seq_no:
            # Since they sent us one that matches what we have,
            # we know we don't need to send it to them
            lsp.clear_srm(recv_interface.name)
            lsp.set_ssn(recv_interface.name)
        else:
            # We want to give them more up to date version
            lsp.set_srm(recv_interface.name)
            lsp.clear_ssn(recv_interface.name)

        if isinstance(pdu, CSNPPDU):
            # Since they sent their complete database, we need to let them
            # know if they missed anything
            onlyours = [lsp_id for lsp_id in set(
                self.database.keys()).difference(seen)]

            for lsp_id in onlyours:
                if self.database[lsp_id].seq_no > 0:
                    self.database[lsp_id].set_srm(recv_interface.name)

    def process_pdu(self, recv_interface, pdu):
        if isinstance(pdu, P2PHelloPDU):
            self.process_hello(recv_interface, pdu)
        elif isinstance(pdu, CSNPPDU) or isinstance(pdu, PSNPPDU):
            self.process_snp(recv_interface, pdu)
        elif isinstance(pdu, LinkStatePDU):
            self.process_lsp(recv_interface, pdu)

    def start(self):
        if self.started:
            return
        # Find our area address
        # In real life, a router can actually be in multiple areas
        # So we'd need to parse each one
        for ifacename in self.interfaces:
            iface = self.interfaces[ifacename]['interface']

            iso_addr = iface.address('iso')
            if iso_addr is not None:
                break

        if iso_addr is None:
            raise "Must have iso address"
        parts = iso_addr.split('.')

        self.area_id = parts[0] + '.' + parts[1]
        self.system_id = parts[2] + '.' + parts[3] + '.' + parts[4]
        self.selector = parts[5]

        self.__refresh_local()

        GlobalQueueManager.enqueue(random.randint(
            self.hello_interval-1, self.hello_interval+1), self.__send_hello)
        GlobalQueueManager.enqueue(random.randint(
            self.partial_snp_interval-1, self.partial_snp_interval+1), self.__send_partial_snps)
        GlobalQueueManager.enqueue(random.randint(
            self.minimum_lsp_interval-1, self.minimum_lsp_interval+1), self.__send_lsps)

        def link_handler(evt):
            GlobalQueueManager.enqueue(
                10, self.__refresh_local
            )
            
        self.event_manager.listen(EventType.LINK_STATE, link_handler)
        self.started = True

    # https://en.wikipedia.org/wiki/Dijkstra%27s_algorithm
    # TODO: Rewrite using https://book.systemsapproach.org/internetworking/routing.html
    # This is in reality what C.1.4 is describing, just much more clear
    def run_full_dijkstra(self):
        logger = self.logger.getChild("spf")

        logger.info("Starting SPF run")
        """
    Calculate shortest path from this node by running Dijkstra's algorithm
    and then pulling out the path elements
    NOTE: This is not actually what's specified in RFC1195 - C.1.4
        mainly as I was having trouble grokking what it was doing, possibly
        as it still handles both broadcast and point-to-point and at the
        moment this implementation is for point-to-point
    """

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

        dbvalues = sorted(
            self.database.values(),
            key=lambda lsp: lsp.pdu.source_address)
        # https://en.wikipedia.org/wiki/Dijkstra%27s_algorithm
        for wrapper in dbvalues:
            entry_node = wrapper.pdu.source_address
            # Note the shortcut we're taking of treating the lsp_id as the system_id
            system_distance[entry_node] = sys.maxsize
            prev_system[entry_node] = None
            queue.append(wrapper.pdu.source_address)

        system_distance[self.system_id] = 0

        while len(queue) > 0:

            # find shortest element
            min_idx = 0
            min_dist = sys.maxsize
            for i in range(len(queue)):

                if system_distance[queue[i]] < min_dist:
                    min_idx = i
                    min_dist = system_distance[queue[i]]

            node = queue.pop(min_idx)

            lsp = self.database[node].pdu

            neighbors = lsp.neighbors

            for neigh in neighbors:
                # this is same as "system_id" currently
                neigh_id = neigh.system_id
                metric = neigh.metric
                
                logger.debug(f"processing {neigh_id} neighbor of {node}")
                if neigh_id not in system_distance:
                    logger.debug(f"ignoring due to {neigh_id}")
                    # We haven't actually converged
                    return None

                new_dist = system_distance[node] + metric

                if new_dist < system_distance[neigh_id]:
                    system_distance[neigh_id] = new_dist
                    logger.debug(f"updated {neigh_id} distance to {new_dist}")
                    prev_system[neigh_id] = lsp.source_address

            # Now deal with our routable prefixes
            for network in lsp.addresses:
                if network.state.name != 'UP':
                    continue
                address = network.prefix
                metric = network.metric

                new_dist = system_distance[node] + metric

                existing_metric = distance.get(address)
                if existing_metric is None or existing_metric > new_dist:
                    distance[address] = new_dist
                    prev[address] = lsp.source_address
                    self.logger.debug(
                        f"SPF set prev for {address} to {lsp.source_address}")

        # Now convert to more useful paths
        system_paths = {}
        address_paths = {}

        def resolve_path(cur_elem):
            the_path = []
            while cur_elem is not None:
                if cur_elem != self.system_id:
                    the_path.append(cur_elem)
                cur_elem = prev_system.get(cur_elem)
            return the_path

        for address in prev:
            path_elem = prev[address]
            this_path = resolve_path(path_elem)
            address_paths[address] = this_path
            address_paths[address].reverse()

        for systemid in prev_system:
            this_path = []

            path_elem = prev_system.get(systemid)
            this_path = resolve_path(path_elem)
            system_paths[systemid] = this_path

        self.address_distances = distance
        self.system_paths = system_paths
        self.address_paths = address_paths
        self.event_manager.observe(Event(
            EventType.ISIS, self, f"Recalculated shortest paths", object=lsp, sub_type="SPF_RUN"))
        self.spf_pending = False
        self.update_routing_table()

    def update_routing_table(self):
        routes = []

        if self.address_paths is None:
            return
        for address in self.address_paths:
            if len(self.address_paths[address]) == 0:
                # Don't think we need to put ourself in the routes
                # as it's implied that it'll be in a direct route
                continue
            else:
                next_hop = self.address_paths[address][0]
                if next_hop not in self.neighbors:
                    self.logger.error(
                        f"{self.hostname} Invalid state: {next_hop} is not one of our neighbors")
                    continue
                next_hop_iface = self.neighbors[next_hop].interface_name
                next_hop_name = self.database[next_hop].hostname
                next_hop_addr = self.neighbors[next_hop].address
            metric = self.address_distances[address]
            routes.append(
                Route(
                    address, "ISIS", self.interfaces[next_hop_iface]['interface'], next_hop_addr, RouteType.ISIS.value)
            )

        self.routing.set_routes(routes, 'isis', src=self)

    def print_database(self):
        pp = pprint.PrettyPrinter(depth=4)
        for lsp_id in self.database:
            print(self.database[lsp_id].extensive())

    def print_routes(self):
        if self.address_paths is None:
            return

        for address in self.address_paths:
            the_path = '->'.join(self.address_paths[address])
            if len(self.address_paths[address]) == 0:
                next_hop_iface = ''
                next_hop_name = 'SELF'
            else:
                next_hop = self.address_paths[address][0]
                next_hop_iface = self.neighbors[next_hop].interface_name
                next_hop_name = self.database[next_hop].hostname
            metric = self.address_distances[address]
            print(f"{address}\t{metric}\t{next_hop_iface}({next_hop_name})")
    # RFC1195 - C.1.4
    # Modified Dijskstra

    def run_spf(self):
        paths = []
        tents = {}

        paths.append((self.system_id, 0, -1))

        selflsp = self.database[self.system_id]

        for reachableip in selflsp.addresses:
            address = reachableip.ip_prefix
            cost = reachableip.metric
            adj = set(self.system_id)  # ?

            entry = tents.get(address)

            if entry is not None and entry[0] == cost:
                tents[address] = (cost, entry[1].union(adj))
            elif entry is not None and entry[0] < cost:
                pass
            else:  # no entry or >
                tents[address] = (cost, adj)

        for neighbor in selflsp.neighbors:
            address = neighbor.system_id
            cost = neighbor.metric
            adj = set(self.system_id)

            entry = tents.get(address)
            if entry is not None and entry[0] == cost:
                tents[address] = (cost, entry[1].union(adj))
            elif entry is not None and entry[0] < cost:
                pass
            else:  # no entry or >
                tents[address] = (cost, adj)
