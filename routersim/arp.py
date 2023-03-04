from collections import UserDict
import binascii
from enum import Enum
from ipaddress import IPv4Address

from scapy.layers.inet import IP
from scapy.layers.l2 import ARP
from .messaging import MACAddress
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

    def process(self, packet: ARP, interface: LogicalInterface):
        # ARP Poisoning, whaddup
        if self.cache[packet.psrc] != packet.hwsrc:
            self.event_manager.observe(
                ArpEvent(
                    self,
                    "Added ARP Entry",
                    (packet.psrc, packet.hwsrc),
                    "ARP_ADD"
                )
            )

        # We need to "ping" it to refresh it from aging out
        self.cache[packet.psrc] = packet.hwsrc

        if packet.op == ArpType.Request.value:

            # TODO: An interface can have multiple addresses
            self.logger.debug(f"Its a request...{str(packet.pdst)} {str(interface.address().ip)}")
            if str(packet.pdst) == str(interface.address().ip):
                self.logger.info(f"\tSending reply")
                self.reply(
                    packet.hwsrc,
                    packet.psrc,
                    packet.pdst,
                    interface
                )

        if packet.psrc in self.send_q:
            self.logger.debug(f"Sending queued items to {packet.psrc}")
            for item in self.send_q[packet.psrc]:
                pdu, interface = item
                self.sender.send_frame(interface, packet.hwsrc, FrameType.IPV4, pdu)
            del self.send_q[packet.psrc]

    # TODO: This probably belongs in the "sender"
    def enqueue(self, nh: IPv4Address, pdu: IP, interface: LogicalInterface):
        if nh not in self.send_q:
            self.send_q[nh] = []

        self.logger.debug(f"Enqueued {pdu} waiting for ARP of {nh}")
        self.send_q[nh].append((pdu, interface))

    def request(self, target: IPv4Address, interface: LogicalInterface):

        packet = ARP(
            op=ArpType.Request,
            hwsrc = interface.hw_address,
            psrc = interface.address().ip,
            pdst=target,
        )

        # Observe ARP
        interface.send(BROADCAST_MAC, FrameType.ARP, packet)

    def reply(self,
              target_hw: MACAddress,
              target_address: IPv4Address,
              from_address: IPv4Address,
              interface: LogicalInterface):

        packet = ARP(
            op = ArpType.Reply,
            hwsrc = interface.hw_address,
            psrc = from_address,
            hwdst = target_hw,
            pdst = target_address,
        )

        interface.send(target_hw, FrameType.ARP, packet)

