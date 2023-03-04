from typing import Generic
from routersim.mpls import MPLSPacket
from .rsvp.process import RsvpProcess
from .isis.process import IsisProcess
from .routing import RoutingTables, Route, RouteType
from .observers import EventManager, EventType, LoggingObserver, Event
from .observers import GlobalQueueManager
from .messaging import FrameType, IPProtocol, ICMPMessage, ICMPType, Frame, MACAddress, RSVPMessage
from .messaging import BROADCAST_MAC
from .forwarding import PacketForwardingEngine, ForwardingTable
from .interface import ConnectionState, LogicalInterface
from .netdevice import NetworkDevice
from .arp import ArpHandler, ArpPacket
import ipaddress
import logging
from functools import partial
from copy import copy
from .server import Server


# TODO: Refer to https://flylib.com/books/en/2.515.1.18/1/#:~:text=The%20Routing%20Engine%20and%20Packet,scale%20networks%20at%20high%20speeds.

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
                self.router._forwarding.set_fib(self.router.routing.forwarding_table())


class PacketListener:
    def __init__(self, router):
        self.router = router

    def observe(self, evt):
        # TODO: This stuff will move into type-specific processors
        if not evt.event_type == EventType.PACKET_RECV:
            return

        frame = evt.object
        # assuming we're not there, we now need to determine if the packet
        # should be forwarded on or is actually meant for us
        # (control plane traffic)
        # Still need to work out exactly how we distinguish these

        # assume it was meant for the first interfrace for now,
        # e.g. no vlan support
        logint = None
        for ifacename in evt.source.interfaces:
            logint = evt.source.interfaces[ifacename]
            #self.interfaces[ifacename].receive(frame)
            break

        # Treat this as exception traffic
        # In "real life" the PFE would actuall see it first, so we're
        # currently treating this listener as part of the PFE
        if frame.dest == BROADCAST_MAC or frame.dest == logint.hw_address:
            self.router.process_frame(frame, logint)
        else:
            self.router.pfe.process_frame(frame, source_interface=logint)


# A router is essentially a regular server (the control plane)
# a badass set of network cards (the fowrarding plane/packet fowarding engine)
class Router(Server):

    def __init__(self, hostname, loopback_address):
        super().__init__(hostname)
        self.loopback_address = loopback_address
        self.arp = ArpHandler(self, self.event_manager, self.logger)
        self.process = dict()
        self.event_manager = EventManager(self.hostname)
        self.routing = RoutingTables(evt_manager=self.event_manager, parent_logger=self.logger)
        self._forwarding = ForwardingTable(self.event_manager, self.logger)
        self.pfe = PacketForwardingEngine(self._forwarding, self)
        self.pingid = 0

        self.event_manager.listen(
            '*', LoggingObserver(self.hostname, self.logger).observe)
        self.event_manager.listen(
            EventType.LINK_STATE, RouteTableUpdater(self).observe)
        self.event_manager.listen(
            EventType.PACKET_RECV, PacketListener(self).observe)

        self.event_manager.listen(EventType.ROUTE_CHANGE,
                                  lambda evt: self._forwarding.set_fib(
                                      self.routing.forwarding_table())
                                  )

        lo = self.add_physical_interface("lo").add_logical_interface(
            "lo.0", addresses={
                "ip": loopback_address}
        )
        lo.te_metric = 500
        self.interfaces['lo'].state = ConnectionState.UP
        lo.state = ConnectionState.UP

        self.process['rsvp'] = RsvpProcess(
            self.event_manager, self, loopback_address)
        self.process['isis'] = IsisProcess(
            self.event_manager, self.hostname, self.routing)

        self.interfaces['lo.0'] = lo

        self.routing.add_route(
            Route(lo.addresses['ipv4'].network,
                  RouteType.LOCAL,
                  lo,
                  None,
                  metric=1), 'direct', src=self.hostname
        )

    def __str__(self):
        return self.hostname

    def enable_isis(self, interface, passive=False, metric=10):
        self.process['isis'].enable_interface(
            interface, passive=passive, metric=metric)

    def start_isis(self):
        self.process['isis'].start()

    def start_rsvp(self):
        self.process['rsvp'].start()

    def show_isis_database(self):
        self.process['isis'].print_database()

    def process_arp(self, source_interface, pdu):
        self.arp.process(pdu, source_interface)

    def process_packet(self, source_interface, packet):
        self.logger.info(f"Received {packet}")

        if super().process_packet(source_interface, packet):
            return True

        if isinstance(packet.pdu, RSVPMessage):
            return self.process['rsvp'].process_packet(source_interface, packet)

    def static_route(self, dest_prefix, gw_int):
        if isinstance(dest_prefix, str):
            dest_prefix = ipaddress.ip_network(dest_prefix)

        if isinstance(gw_int, str):
            gw_int = self.interfaces[gw_int]

        self.routing.add_route(
            Route(
                dest_prefix,
                RouteType.STATIC,
                gw_int,
                None,
                metric=RouteType.STATIC.value
            ),
            'static',
        )

    # TODO: This will probably end up in NetworkDevice,
    # or router will extend from Server
    def send_frame(self,
                   interface: LogicalInterface,
                   dest_address: MACAddress,
                   frame_type: FrameType,
                   pdu,
                   source_override=None):

        # Assumption on this level is that we are over a shared medium
        # such that we can just dump this on the wire. 
        interface.send(dest_address, frame_type, pdu)

 
    def _send_ip(self, packet, source_interface=None):

        if source_interface is None:
            route = self.routing.lookup_ip(packet.dst)

            if route is not None:
                source_interface = route.interface

        # Once we do layer2, we might just ship the IPV4 to it?
        GlobalQueueManager.enqueue(
            0,
            self.pfe.accept_frame,
            arguments=(Frame("000", "000", FrameType.IPV4, packet),
                       source_interface)
        )



    def create_lsp(self, lsp_name, dest_ip, link_protection=False):
        """
        Kick off the logic to issue RSVP Path messages
        to build an LSP to the target IP
        Assumes access to IGP data
        """

        # This create ERO based on the shortest-path
        # We also want to create a bypass path (Detour)

        self.process['rsvp'].create_session(
            dest_ip,
            lsp_name,
            link_protection=link_protection
        )

    def show_route_table(self):
        print(f"### {self.hostname} routes ###")
        self.routing.print_routes()
        print("")