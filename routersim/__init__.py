from scapy.config import conf as scapconf

from scapy.interfaces import NetworkInterfaceDict, IFACES

from scapy import interfaces
from scapy.layers.inet import IP,ICMP,IPOption_Router_Alert
from scapy.layers.l2 import ARP
from .arp import ArpType

# reset, as we don't want the default links
# Then we can inject our interfaces as necessary
scapconf.ifaces = IFACES = NetworkInterfaceDict()
interfaces.IFACES = None
scapconf.ifaces = None
scapconf.iface = None


def seq_note(self):
    notefn = getattr(self.payload, "seq_note", None)
    if notefn is not None:
        note = notefn()
    else:
         note = None

    return note
    
def ip_inspectable(self):
    return len(
        [opt for opt in self.options if isinstance(opt, IPOption_Router_Alert)]
    ) > 0


def icmp_seq_note(self) -> str:
    return f"{self.type}\n{self.payload.load}"
ICMP.seq_note = icmp_seq_note
IP.seq_note = seq_note
IP.inspectable = ip_inspectable


def arp_str(self) -> str:
    if self.op == ArpType.Request.value:
        return f"ARP Request Who-Is {self.pdst}, tell {self.psrc} at {self.hwsrc}"
    else:
        return f"ARP Response {self.psrc} is {self.hwsrc}"


ARP.__str__ = arp_str