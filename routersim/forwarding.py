
from routersim.interface import LogicalInterface
from .messaging import FrameType
from .messaging import ICMPType, UnreachableType
from .mpls import MPLSPacket, PopStackOperation
from .observers import Event, EventType
from scapy.layers.inet import IP,ICMP,icmptypes
from copy import copy
import ipaddress


class ForwardingTable:

    def __init__(self, event_manager, parent_logger):
        self.fib = None
        self.event_manager = event_manager
        self.logger = parent_logger.getChild('forwarding')

    def __str__(self):
        return "Forwarding Table"

    def set_fib(self, fib):
        self.fib = fib
        self.logger.debug("Installed new forwarding table")

    def lookup_ip(self, ip_address):
        as_network = ipaddress.ip_network(ip_address)
        # ASSUMPTION: fib is sorted with highest prefix first
        # so we should always arrive at something more specific first
        # yes, this is very inefficient
        if self.fib is None:
            return None

        for prefix in self.fib[FrameType.IPV4]:
            if as_network.overlaps(prefix):
                self.event_manager.observe(
                    Event(
                        EventType.FORWARDING,
                        self,
                        f"Identified forwarding entry for {ip_address}"
                    )
                )
                return [self.fib[FrameType.IPV4][prefix]]

        return None

    def lookup_label(self, label):
        if self.fib is None:
            return None

        if self.fib is None or FrameType.MPLSU not in self.fib:
            return None

        return [self.fib[FrameType.MPLSU][str(label)]]

    def print_fib(self):
        print("** IPV4 FIB ***")
        for prefix in self.fib[FrameType.IPV4]:
            entry = self.fib[FrameType.IPV4][prefix]
            print(f"{entry}")
        print("")
        print("** MPLS FIB ***")
        for prefix in self.fib[FrameType.MPLSU]:
            entry = self.fib[FrameType.MPLSU][prefix]
            print(f"{entry}")
        

class PacketForwardingEngine():

    def __init__(self, forwarding_table: ForwardingTable, router):
        self.router = router
        self.forwarding = forwarding_table
        self.arp_cache = router.arp.cache
        self.logger = router.logger.getChild("pfe")

    # Intended for internal communications
    def accept_frame(self, frame, dest_interface=None):
        self.router.event_manager.observe(
            Event(
                EventType.PACKET_SEND,
                self.router, f"PFE Sending {frame.type}", object=frame, target=dest_interface,
                sub_type="LOCAL_SEND")
            )
        # parameter naming was confusing...
        self.process_frame(frame, dest_interface=dest_interface, from_self=True)

    def process_frame(self, frame, source_interface=None, from_self=False, dest_interface=None):

        def process_ip(pdu, dest_interface=None):
            if pdu.inspectable() and not from_self:
                self.router.process_packet(source_interface, pdu)
                return

            # should be an IPPacket
            potential_next_hops = self.forwarding.lookup_ip(
                pdu.dst
            )
            if potential_next_hops is not None:
                pdu.ttl -= 1
                # TODO: Fire event?
                hop_action = potential_next_hops[0]

                self.logger.info(f"Will apply action {hop_action.action}")


                if not isinstance(hop_action.action, str):
                    newpdu = hop_action.action.apply(pdu, self.router, self.router.event_manager)

                    self.logger.info(f"New pdu is {newpdu}")
                    if isinstance(newpdu, MPLSPacket):
                        hop_action.interface.phy.send(FrameType.MPLSU, newpdu)
                    else:
                        self.logger.warn("Didn't get back an MPLSPacket")
                else:
                    if hop_action.action == 'FORWARD' or dest_interface is not None:
                        # TODO: If we know the dest_interface should we be blindly sending on it?
                        # I'm not too happy about this quite yet
                        # really the link between the RE and PFE is wonky
                        if dest_interface is None:
                            self.logger.debug(f"Using {potential_next_hops[0].interface} for {pdu}")
                            dest_interface = potential_next_hops[0].interface
                        self.logger.debug(f"Using {dest_interface} for {pdu} (potential NH: {potential_next_hops[0]}")
                        self.send_encapsulated(
                            potential_next_hops[0].next_hop_ip,
                            FrameType.IPV4,
                            pdu,
                            dest_interface
                        )
                    elif hop_action.action == 'CONTROL':
                        if from_self:
                            self.logger.error(f"Unexpectedly have frame from self we need to forward {pdu}")
                            raise Exception(f"Unexpectedly have frame from self we need to forward {pdu}")
                        self.router.process_packet(source_interface, pdu)
                    elif hop_action.action == 'REJECT' and source_interface is not None:
                        #print(f"Sending reject from {source_interface.name}:{source_interface.address().ip} to {pdu.source_ip}")
                        
                        packet = IP(
                            dst=pdu.src,
                            src=source_interface.address().ip
                        ) / ICMP(
                            type = ICMPType.DestinationUnreachable,
                            code=UnreachableType.NetworkUnreachable
                        ) / (
                                    pdu.dst,
                                    pdu.src,
                                    pdu.payload.payload  # IRL its first 8 bytes
                                )
                        source_interface.send_ip(packet)
                    else:
                        self.logger.info(f"**** Have action {hop_action.action}")
            else:
                self.logger.warn("**** Need to issue ICMP UNREACHABLE")
                pass
                # send unreachable

        pdu = copy(frame.pdu)
        if frame.type == FrameType.IPV4:
            self.logger.info("Calling process_ip")
            process_ip(pdu, dest_interface)
            # This means we're supposed to look at it
        # special case of control plane...
        elif frame.type == FrameType.ARP:
            # So, dilemma: Here we PROBABLY want to make sure
            # this only happens on switch interfaces?
            # would is also happen on routed interfaces?
            self.router.process_arp(source_interface, pdu)
            # TODO: If we're switching, we also want to forward it!
        elif frame.type == FrameType.CLNS:
            self.router.process['isis'].process_pdu(source_interface, frame.pdu)
        elif frame.type == FrameType.MPLSU:
            # pdu should be an MPLSPacket
            potential_next_hops = None
            try:
                potential_next_hops = self.forwarding.lookup_label(
                    pdu.label_stack[len(pdu.label_stack)-1]
                )
            except:
                if pdu.label_stack[0] == '3':
                    newpdu = PopStackOperation().apply(pdu, self.router, event_manager=self.router.event_manager)
                    if isinstance(newpdu, IP):
                        process_ip(newpdu)
                        return

                self.logger.warn(f"Unable to find {pdu.label_stack[0]}")

            if potential_next_hops is not None:
                fibentry = potential_next_hops[0]
                newpdu = fibentry.action.apply(pdu,
                                               self.router, 
                                               event_manager=self.router.event_manager)
                if isinstance(newpdu, MPLSPacket):
                    fibentry.interface.parent.send(
                        FrameType.MPLSU, newpdu, logical=None)
                elif isinstance(newpdu, IP):
                    fibentry.interface.send_ip(newpdu)
                else:
                    print(f"Unknown de-encapsulated packet type!")
            else:
                self.logger.error(f"**** No action found for label {pdu.label_stack[0]}")

    def send_encapsulated(self,
                          next_hop: ipaddress.IPv4Address,
                          type: FrameType,
                          packet,
                          interface: LogicalInterface):
        if next_hop is None:
            dest_ip = packet.dst
            dest_ip_as_net = ipaddress.ip_network(f"{dest_ip}/32")
            if interface.address().network.overlaps(dest_ip_as_net):
                next_hop = dest_ip
            else:
                raise Exception("Valid IP is required")

        hw_address = self.arp_cache[next_hop]
        if hw_address is None:
            # TODO: Drop it?
            self.router.arp.request(next_hop, interface)
        else:
            interface.send(hw_address, type, packet)

