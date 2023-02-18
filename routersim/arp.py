from collections import UserDict
import binascii
from enum import Enum
from ipaddress import IPv4Address

from .messaging import IPPacket, MACAddress
from .interface import LogicalInterface


from .observers import GlobalQueueManager, EventType, Event
from .messaging import FrameType, BROADCAST_MAC


class ArpEvent(Event):
    def __init__(self, source, msg, object, sub_type):
        super().__init__(EventType.ARP,
                         source,
                         msg,
                         object,
                         sub_type)


class ArpCache(UserDict):
    def __init__(self):
        super().__init__()

    def __setitem__(self, key, value):
         self.data[key] = ArpEntry(key, value, GlobalQueueManager.now())

    def __getitem__(self, key):
        entry = self.data.get(key)
        if entry is None:
            return None
        else:
            return entry.l2address


class ArpType(Enum):
    Request = 1
    Reply = 2


# https://datatracker.ietf.org/doc/html/rfc826
class ArpEntry:
    def __init__(self, l3address: IPv4Address, l2address: MACAddress, used: int):
        self.l3address = l3address
        self.l2address = l2address
        self.last_used = used


# We are assuming we're going for Ethernet adress
class ArpPacket:
    def __init__(self,
                 arp_type: ArpType,
                 hw_address: MACAddress,
                 source_address: IPv4Address,
                 target_hw: MACAddress,
                 target_address: IPv4Address,
                 protocol: FrameType = FrameType.IPV4):
        self.arp_type = arp_type
        self.protocol = protocol
        self.hw_address = hw_address
        self.source_address = source_address
        self.target_hw = target_hw
        self.target_address = target_address

    def __str__(self):
        if self.arp_type == ArpType.Request:
            return f"ARP Request Who-Is {self.target_address}, tell {self.source_address} at {self.hw_address}"
        else:
            return f"ARP Response {self.source_address} is {self.hw_address}"


class ArpHandler:
    def __init__(self, sender, event_manager, logger, cache=None, queue=None):
        self.sender = sender
        self.event_manager = event_manager
        self.logger = logger.getChild("arp")
        if cache is None:
            self.cache = ArpCache()
        else:
            self.cache = cache

        if queue is None:
            # List of packets waiting for ARP responses
            self.send_q = dict()
        else:
            self.send_q = queue

    def process(self, packet: ArpPacket, interface: LogicalInterface):
        # ARP Poisoning, whaddup
        if self.cache[packet.source_address] != packet.hw_address:
            self.event_manager.observe(
                ArpEvent(
                    self,
                    "Added ARP Entry",
                    (packet.source_address, packet.hw_address),
                    "ARP_ADD"
                )
            )

        # We need to "ping" it to refresh it from aging out
        self.cache[packet.source_address] = packet.hw_address

        if packet.arp_type == ArpType.Request:

            # TODO: An interface can have multiple addresses
            if packet.target_address == interface.address().ip:
                self.reply(
                    packet.hw_address,
                    packet.source_address,
                    packet.target_address,
                    interface
                )

        if packet.source_address in self.send_q:
            self.logger.debug(f"Sending queued items to {packet.source_address}")
            for item in self.send_q[packet.source_address]:
                pdu, interface = item
                self.sender.send_frame(interface, packet.hw_address, FrameType.IPV4, pdu)
            del self.send_q[packet.source_address]

    # TODO: This probably belongs in the "sender"
    def enqueue(self, pdu: IPPacket, interface: LogicalInterface):
        if pdu.dest_ip not in self.send_q:
            self.send_q[pdu.dest_ip] = []

        self.logger.debug(f"Enqueued {pdu} waiting for ARP")
        self.send_q[pdu.dest_ip].append((pdu, interface))

    def request(self, target: IPv4Address, interface: LogicalInterface):

        packet = ArpPacket(arp_type=ArpType.Request,
                           hw_address=interface.hw_address,
                           source_address=interface.address().ip,
                           target_hw=None,
                           target_address=target)
        # Observe ARP
        interface.send(BROADCAST_MAC, FrameType.ARP, packet)

    def reply(self,
              target_hw: MACAddress,
              target_address: IPv4Address,
              from_address: IPv4Address,
              interface: LogicalInterface):

        packet = ArpPacket(ArpType.Reply,
                           interface.hw_address,
                           from_address,
                           target_hw,
                           target_address,
                           )

        interface.send(target_hw, FrameType.ARP, packet)

