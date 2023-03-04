from routersim.interface import LogicalInterface
from .netdevice import NetworkDevice
from .routing import RoutingTables, Route, RouteType
from .observers import LoggingObserver, EventType
from .messaging import BROADCAST_MAC, FrameType
from .arp import ArpHandler
import ipaddress
from .scapy import RouterSimRoute
from scapy.sendrecv import send as scapy_l3_send
from scapy.config import conf as scapy_conf
from scapy.layers.l2 import Ether

class RouteTableUpdater:
    def __init__(self, router):
        self.router = router

    def observe(self, evt):
        if evt.event_type == EventType.LINK_STATE:
            source = evt.source

            if source.is_up():
                # Need to add connected routes

                if not source.is_physical():
                    self.router.routing.add_route(
                        Route(
                            source.addresses['ipv4'].network,
                            RouteType.CONNECTED,
                            source,
                            None,
                            metric=1
                        ),
                        'direct',
                        src=source.parent.parent
                    )
                    self.router.routing.add_route(
                        Route(
                            ipaddress.ip_network(
                                (source.addresses['ipv4'].ip, 32)),
                            RouteType.LOCAL,
                            source,
                            None,
                            metric=1
                        ),
                        'direct',
                        src=source.parent.parent
                    )
            else:
                # BLEH.
                if not source.is_physical():
                    self.router.routing.del_route(
                        Route(
                            source.addresses['ipv4'].network,
                            RouteType.CONNECTED,
                            source,
                            None,
                            metric=1
                        ),
                        'direct',
                        src=source.parent.parent
                    )
                    self.router.routing.del_route(
                        Route(
                            ipaddress.ip_network(
                                (source.addresses['ipv4'].ip, 32)),
                            RouteType.LOCAL,
                            source,
                            None,
                            metric=1
                        ),
                        'direct',
                        src=source.parent.parent
                    )

class PacketListener:
    def __init__(self, server):
        self.server = server

    def observe(self, evt):
        # TODO: This stuff will move into type-specific processors
        if not evt.event_type == EventType.PACKET_RECV:
            return

        frame = evt.object

        physint = evt.source
        # assuming we're not there, we now need to determine if the packet
        # should be forwarded on or is actually meant for us
        # (control plane traffic)
        # Still need to work out exactly how we distinguish these
        # assume it was meant for the first interfrace for now,
        # e.g. no vlan support
        logint = None
        for ifacename in physint.interfaces:
            logint = physint.interfaces[ifacename]
            #self.interfaces[ifacename].receive(frame)
            break

        self.server.process_frame(frame, source_interface=logint)

# An end host
class Server(NetworkDevice):
    def __init__(self, hostname):
        super().__init__(hostname)

        self.add_physical_interface("et1")
        self.routing = RoutingTables(evt_manager=self.event_manager, parent_logger=self.logger)
        self.arp = ArpHandler(self, self.event_manager, self.logger)
        self.event_manager.listen(
            '*', LoggingObserver(self.hostname, self.logger).observe)
        self.event_manager.listen(
            EventType.PACKET_RECV, PacketListener(self).observe)
        self.event_manager.listen(
            EventType.LINK_STATE, RouteTableUpdater(self).observe)

    def static_route(self, dest_prefix, gw_ip, gw_int):
        if isinstance(dest_prefix, str):
            dest_prefix = ipaddress.ip_network(dest_prefix)

        if isinstance(gw_ip, str):
            gw_ip = ipaddress.ip_address(gw_ip)
        if isinstance(gw_int, str):
            gw_int = self.interfaces[gw_int]

        self.routing.add_route(
            Route(
                dest_prefix,
                RouteType.STATIC,
                gw_int,
                gw_ip,
                metric=RouteType.STATIC.value
            ),
            'static',
        )

    # TODO: This may move to NetworkDevice
    # Or else, router/switch will extend from NetworkDevice
    def send_frame(self,
                   interface,
                   dest_address,
                   frame_type,
                   pdu,
                   source_override=None):

        # Assumption on this level is that we are over a shared medium
        # such that we can just dump this on the wire. 
        interface.send(dest_address, frame_type, pdu)

    def scapy_send_ip(self, packet, source_interface=None):
        scapy_conf.route = RouterSimRoute(self.routing)
        scapy_l3_send(packet)

    # In order to send a Layer 3 (IP) packet that is on the same layer 3 network as
    # our packet, we need to to know it's Layer 2 (Ethernet) address. This
    def send_ip(self, packet, source_interface=None):
  
  #      route = self.routing.lookup_ip(packet.dest_ip)
        route = self.routing.lookup_ip(packet.dst)
        if route is None:
            # TODO: NoRouteException
            raise Exception()
            #f"{packet.dest_ip}: no route to host")

        if source_interface is None:
            if route is not None:
                source_interface = route.interface

        # Now, we need to determine whether this packet is destined for our
        # local network to go over Layer 2, or if it should be sent off
        # to to the default route
        lookup_addr = route.next_hop_ip
#        dest_ip = packet.dest_ip
        dest_ip = packet.dst
        dest_ip_as_net = ipaddress.ip_network(f"{dest_ip}/32")
        if source_interface.address().network.overlaps(dest_ip_as_net):
            lookup_addr = dest_ip

        mac_address = self.arp.cache.get(lookup_addr)
  
        if mac_address is None:
            self.arp.enqueue(lookup_addr, packet, source_interface)
            self.arp.request(lookup_addr, source_interface)
        else:
            self.send_frame(source_interface,
                            mac_address,
                            FrameType.IPV4,
                            packet)

    def process_frame(self, frame: Ether, source_interface: LogicalInterface):
        if frame.dst != BROADCAST_MAC and frame.dst != source_interface.hw_address:
            return

        if int(frame.type) == FrameType.ARP:
            self.arp.process(frame.payload, source_interface)
        elif int(frame.type) == FrameType.IPV4:
            self.process_packet(source_interface, frame.payload)
