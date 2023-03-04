
from .interface import PhysicalInterface
from .messaging import ICMPMessage, ICMPType, IPProtocol, MACAddress

from .observers import Event, EventManager, EventType, GlobalQueueManager
from .junos import parser as junos
import ipaddress
import logging
import random
import json

from scapy.layers.inet import IP,ICMP


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

    def add_ip_address(self, interface_name, address):
        intf = self.interfaces.get(interface_name)
        if intf is None:
            raise f"{interface_name} is an unknown interface"

        if type(address) == str:
            address = { 'ip': address}

        if intf.is_physical():
            logf = self.interfaces.get(interface_name + ".0")
            if logf is None:
                logf = self.add_logical_interface(intf, interface_name + ".0", address)
        else:
            intf.addresses['ipv4'] = ipaddress.ip_interface(
                    address['ip'])
        
        return self

    def add_logical_interface(self, phy, interface_name, addresses=None):
        intf = phy.add_logical_interface(interface_name, addresses)
        self.interfaces[interface_name] = intf
        return intf

    def process_packet(self, source_interface, packet):
        payload = packet.payload
        self.logger.info(f"Received {payload} ({payload.type})")

        if isinstance(payload, ICMPMessage) or isinstance(payload, ICMP):
            if payload.type == ICMPType.EchoRequest.value:
                packet = IP(
                    src = packet.dst,
                    dst = packet.src    
                ) / ICMP (
                    type = ICMPType.EchoReply
                ) / payload.payload

                #packet = IPPacket(
                #    packet.source_ip,
                #    packet.dest_ip,
                #    IPProtocol.ICMP,
                #    ICMPMessge(
                #        ICMPType.EchoReply,
                #        payload=packet.pdu.payload
                #    )
                #)
                # In real life, I'm not sure we would do this
                # but would look it up?
                self.send_ip(packet)
                return True
            elif payload.type == ICMPType.EchoReply.value:
                self.event_manager.observe(Event(
                    EventType.ICMP,
                    self,
                    msg=f"Received Echo Reply {payload.payload}",
                    object=packet,
                    sub_type=payload.type
                ))
                return True
            elif payload.type == ICMPType.DestinationUnreachabl.valuee:
                self.event_manager.observe(Event(
                    EventType.ICMP,
                    self,
                    msg=f"Received Unreachable ({packet.pdu.code})",
                    object=packet,
                    sub_type=packet.pdu.type
                ))
                return True
        return False

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
            # scapy
            pdu = evt.object.payload
            pingpayload = json.loads(pdu.payload.load)
            if (pdu.type == ICMPType.EchoReply.value and pingpayload['id'] == state['lastsent']):
                delta = GlobalQueueManager.now(
                ) - pingpayload['time']
                print(
                    f"\tReceived reply from {evt.object.src} - {delta} ms")
                state['lost'] = False
            elif (pdu.type == ICMPType.DestinationUnreachable.value and
                  evt.object.pdu.payload[2]['id'] == state['lastsent']):
                print(f"\t{pdu} from {evt.object.src}")
                state['lost'] = False

        def check_and_send():
            now = self.event_manager.now()
            if state['lost']:
                print(f"\t!! Lost after {now - state['sent_time']}ms")
            if state['remaining'] > 0:
                state['sent_time'] = now
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
            #packet = IPPacket(
            #    ip_address,
            #    source_ip,
            #    IPProtocol.ICMP,
            #    ICMPMessage(ICMPType.EchoRequest, payload=pingpayload)
            #)
            packet = IP(
                src = source_ip,
                dst = ip_address
            ) / ICMP (
                type=ICMPType.EchoRequest
            ) / json.dumps(pingpayload)
            state['lastsent'] = pingpayload['id']
            state['lost'] = True
            state['sent_time'] = self.event_manager.now()
            state['remaining'] = state['remaining'] - 1
            self.scapy_send_ip(packet, source_interface=source_interface)
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
