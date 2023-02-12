from typing import Generic
from routersim.mpls import MPLSPacket
from .rsvp.process import RsvpProcess
from .isis.process import IsisProcess
from .routing import RoutingTables, Route, RouteType
from .observers import EventManager, EventType, LoggingObserver, Event
from .observers import GlobalQueueManager
from .interface import PhysicalInterface
from .messaging import FrameType, IPPacket, IPProtocol, ICMPMessage, ICMPType, Frame, RSVPMessage
from .forwarding import PacketForwardingEngine, ForwardingTable
from .interface import ConnectionState
import ipaddress
import logging
import random
from functools import partial
from copy import copy


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

        self.router.pfe.process_frame(frame, source_interface=evt.source)


class Router:

    def __init__(self, hostname, loopback_address):
        self.hostname = hostname
        self.logger = logging.getLogger(hostname)
        self.phy_interfaces = dict()
        self.interfaces = dict()
        self.loopback_address = loopback_address
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

    def add_physical_interface(self, interface_name):
        is_loopback = False
        if 'lo' in interface_name:
            is_loopback = True

        intf = PhysicalInterface(
            interface_name, random.randbytes(6),
            owner=self, is_loopback=is_loopback)
        intf.event_manager = self.event_manager
        self.phy_interfaces[interface_name] = intf
        self.interfaces[interface_name] = intf

        return self.phy_interfaces[interface_name]

    def add_logical_interface(self, phy, interface_name, addresses=None):
        intf = phy.add_logical_interface(interface_name, addresses)
        self.interfaces[interface_name] = intf
        return intf

    def interface(self, interface_name):
        return self.interfaces[interface_name]

    def enable_isis(self, interface, passive=False, metric=10):
        self.process['isis'].enable_interface(
            interface, passive=passive, metric=metric)

    def start_isis(self):
        self.process['isis'].start()

    def start_rsvp(self):
        self.process['rsvp'].start()

    def show_isis_database(self):
        self.process['isis'].print_database()

    def process_packet(self, source_interface, packet):
        self.logger.info(f"Received {packet.pdu}")

        if isinstance(packet.pdu, ICMPMessage):
            if packet.pdu.type == ICMPType.EchoRequest:

                packet = IPPacket(
                    packet.source_ip,
                    packet.dest_ip,
                    IPProtocol.ICMP,
                    ICMPMessage(
                        ICMPType.EchoReply,
                        payload=packet.pdu.payload
                    )
                )
                # In real life, I'm not sure we would do this
                # but would look it up?
                self.send_ip(packet)
            elif packet.pdu.type == ICMPType.EchoReply:
                self.event_manager.observe(Event(
                    EventType.ICMP,
                    self,
                    msg=f"Received Echo Reply {packet.pdu.payload}",
                    object=packet,
                    sub_type=packet.pdu.type
                ))
            elif packet.pdu.type == ICMPType.DestinationUnreachable:
                self.event_manager.observe(Event(
                    EventType.ICMP,
                    self,
                    msg=f"Received Unreachable ({packet.pdu.code})",
                    object=packet,
                    sub_type=packet.pdu.type
                ))
        elif isinstance(packet.pdu, RSVPMessage):
            self.process['rsvp'].process_packet(source_interface, packet)

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


    def send_ip(self, packet, source_interface=None):

        if source_interface is None:
            route = self.routing.lookup_ip(packet.dest_ip)

            if route is not None:
                source_interface = route.interface

        # Once we do layer2, we might just ship the IPV4 to it?
        GlobalQueueManager.enqueue(
            0,
            self.pfe.accept_frame,
            arguments=(Frame("000", "000", FrameType.IPV4, packet),
                       source_interface)
        )

    def ping(self, ip_address, source_interface=None, source_ip=None, count=5, timeout=1000):

        self.event_manager.stop_listening(EventType.ICMP, None)
        self.pingid += 1
        pingid = self.pingid+1

        if isinstance(ip_address, str):
            ip_address = ipaddress.ip_address(ip_address)

        state = { 
            'lost': None,
            'remaining': count,
            'lastsent': pingid,
            'dest_ip': ip_address,
            'source_interface': source_interface,
            'source_ip': source_ip,
        }

        print(f"PING {ip_address}")

        def ping_handler(evt):
            if evt.object.pdu.type == ICMPType.EchoReply and evt.object.pdu.payload['id'] == state['lastsent']:
                delta = GlobalQueueManager.now() - evt.object.pdu.payload['time']
                print(f"\tReceived reply from {evt.object.source_ip} - {delta} ms")
                state['lost'] = False
            elif evt.object.pdu.type == ICMPType.DestinationUnreachable and evt.object.pdu.payload[2]['id'] == state['lastsent']:
                print(f"\t{evt.object.pdu} from {evt.object.source_ip}")
                state['lost'] = False

        def check_and_send():
            if state['lost']:
                print(f"\t!! Lost after {timeout}ms")
            if state['remaining'] > 0:
                send_packet(state['dest_ip'], state['source_interface'], state['source_ip'])
            else:
                self.event_manager.stop_listening(EventType.ICMP, state['handler'])

        def send_packet(ip_address, source_interface=None, source_ip=None):

            if source_interface is None:
                route = self.routing.lookup_ip(ip_address)
                # TODO: If we can't find one we nneed to do "no route to host"
                if route is not None:
                    source_interface = route.interface
                else:
                    print(f"{self.hostname} {ip_address} - No route to host!") 
                    return

            if source_ip is None and source_interface is not None:
                source_ip = source_interface.address().ip

            if source_ip is None:
                raise Exception(f"{self.hostname}: Unable to identify a source_ip to ping {ip_address} from {source_interface}")

            self.pingid = pingid + 1
            pingpayload = {
                'id': self.pingid,
                'time': GlobalQueueManager.now()
            }
            packet = IPPacket(
                ip_address,
                source_ip,
                IPProtocol.ICMP,
                ICMPMessage(ICMPType.EchoRequest, payload=pingpayload)
            )
            state['lastsent'] = pingpayload['id']
            state['lost'] = True
            state['remaining'] = state['remaining'] - 1
            self.send_ip(packet, source_interface=source_interface)
            GlobalQueueManager.enqueue(timeout, check_and_send)



        state['handler'] = ping_handler
        self.event_manager.listen(EventType.ICMP, state['handler'])
        # Add a bit of "human delay" to also allow for any events
        # that might need to occur before we ping, a la link state changes
        GlobalQueueManager.enqueue(50, send_packet,
            arguments=(ip_address, source_interface, source_ip)
        )
        # source_interface.send_ip(packet)

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