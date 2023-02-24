from scapy import config as scapconf
from scapy.interfaces import NetworkInterfaceDict, IFACES


# reset, as we don't want the default link
scapconf.ifaces = IFACES = NetworkInterfaceDict()


from scapy.layers.inet import IP,ICMP,IPOption_Router_Alert
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

