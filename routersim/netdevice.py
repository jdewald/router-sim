
from .interface import PhysicalInterface
from .messaging import ICMPMessage, ICMPType, IPPacket, IPProtocol, MACAddress
from .observers import Event, EventManager, EventType, GlobalQueueManager
from .junos import parser as junos
import ipaddress
import logging
import random


class NetworkDevice():

    def __init__(self, hostname):
        # Actual interfaces which can have a cable attached
        self.hostname = hostname
        self.logger = logging.getLogger(hostname)
        self.phy_interfaces = dict()
        self.event_manager = EventManager(self.hostname)

        self.pingid = 0

        # All interfaces (including logical)
        # maybe should just be the logical
        self.interfaces = dict()

    def __str__(self):
        return self.hostname

    def run_junos_op(self, command: str):
        func = junos.parse(command)
        if func is not None:
            func(self)

    def interface(self, interface_name):
        return self.interfaces[interface_name]

    def add_physical_interface(self, interface_name: str, oui=0x420000):
        is_loopback = False
        if 'lo' in interface_name:
            is_loopback = True

        netaddress = random.randbytes(3)
        netasint = int.from_bytes(netaddress, 'big')
        addrasint = oui << 24 | netasint

        fulladdr = addrasint.to_bytes(6, 'big')

        intf = PhysicalInterface(
            interface_name, MACAddress(fulladdr),
            owner=self, is_loopback=is_loopback)
        intf.event_manager = self.event_manager
        self.phy_interfaces[interface_name] = intf
        self.interfaces[interface_name] = intf

        return self.phy_interfaces[interface_name]

    def add_logical_interface(self, phy, interface_name, addresses=None):
        intf = phy.add_logical_interface(interface_name, addresses)
        self.interfaces[interface_name] = intf
        return intf

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

    def ping(self, ip_address, source_interface=None,
             source_ip=None, count=5, timeout=1000):

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
            if (evt.object.pdu.type == ICMPType.EchoReply and
                evt.object.pdu.payload['id'] == state['lastsent']):
                delta = GlobalQueueManager.now(
                ) - evt.object.pdu.payload['time']
                print(
                    f"\tReceived reply from {evt.object.source_ip} - {delta} ms")
                state['lost'] = False
            elif (evt.object.pdu.type == ICMPType.DestinationUnreachable and
                  evt.object.pdu.payload[2]['id'] == state['lastsent']):
                print(f"\t{evt.object.pdu} from {evt.object.source_ip}")
                state['lost'] = False

        def check_and_send():
            if state['lost']:
                print(f"\t!! Lost after {timeout}ms")
            if state['remaining'] > 0:
                send_packet(state['dest_ip'],
                            state['source_interface'], state['source_ip'])
            else:
                self.event_manager.stop_listening(
                    EventType.ICMP, state['handler'])

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
                raise Exception(
                    f"{self.hostname}: Unable to identify a source_ip to ping {ip_address} from {source_interface}")

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
                                   arguments=(
                                       ip_address, source_interface, source_ip)
                                   )
        # source_interface.send_ip(packet)
