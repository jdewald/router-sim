from enum import Enum


BROADCAST_MAC = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
class FrameType(Enum):
    # So, this is a total fudge. OSI CLNS packets
    # are actually encapsulated in Link Layer Control (LLC)
    # frames, and have a type there. The goal of this
    # simulator isn't to go down to that level of detail
    # for now so fudging it here
    CLNS = 0x001
    IPV4 = 0x0800
    ARP = 0x0806
    MPLSU = 0x8847
    MPLSM = 0x8848

    def __str__(self):
        return self.name


# https://en.wikipedia.org/wiki/List_of_IP_protocol_numbers
class IPProtocol(Enum):
    ICMP = 1
    TCP = 6
    UDP = 17
    RSVP = 46


class ICMPType(Enum):
    EchoReply = 0
    EchoRequest = 8
    DestinationUnreachable = 3

    def __str__(self):
        return self.name


class UnreachableType(Enum):
    NetworkUnreachable = 0
    HostUnreachable = 1


class MACAddress():
    def __init__(self, source):
        self.bytes = bytes(source)

    def __hash__(self):
        return hash(self.bytes)

    def __eq__(self, other):
        return (self.__class__ == other.__class__ and
                self.bytes == other.bytes
                )

    def __str__(self):
        return self.bytes.hex(":", 1)

class Frame:

    def __init__(self,
                 src: MACAddress, dest: MACAddress,
                 type, pdu):
        self.src = src
        self.dest = dest
        self.pdu = pdu
        self.type = type



class IPPacket:
    def __init__(self, dest_ip, source_ip, protocol: IPProtocol, pdu, router_alert=False, ttl=64):
        self.source_ip = source_ip
        self.dest_ip = dest_ip
        self.pdu = pdu
        self.protocol = protocol
        # IP Option router_alert allows an intermediate
        # (supporting) router to actually deal with
        # the packet before forwarding it on
        self.ra = router_alert
        self.ttl = ttl

    def inspectable(self):
        return self.ra

    def __str__(self):
        return f"{self.source_ip}->{self.dest_ip} (TTL={self.ttl}) {self.protocol.name}"

    def seq_note(self):
        notefn = getattr(self.pdu, "seq_note", None)
        if notefn is not None:
            note = notefn()
        else:
            note = None

        return note



class ICMPMessage:
    def __init__(self, type: ICMPType, code=0, payload=None):
        self.type = type
        self.code = code
        self.payload = payload

    def __str__(self):
        return f"{self.type}"

    def seq_note(self):
        return f"{self.type}\n{self.payload}"



class RSVPMessage:
    pass