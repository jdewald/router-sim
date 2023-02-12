from .tlv import *


class IsisPDU:
    def __init__(self, source_address, pduname):
        self.source_address = source_address
        self.pduname = pduname
        self.tlvs = []

    def __str__(self):
        return f"{self.pduname} (source={self.source_address})"

    def seq_note(self):
        return None


class P2PHelloPDU(IsisPDU):
    """
    The Hello PDU is used to establish and maintain adjacencies
    """

    def __init__(self, source_address, hostname=None):
        super().__init__(source_address, "p2p Hello")
        self.hostname = hostname


class CSNPPDU(IsisPDU):
    """
    Send all known LSP entries
    """

    def __init__(self, source_address):
        super().__init__(source_address, "L1 CSNP")

        self.tlvs = []

    def seq_note(self):
        note = f"I know about these LSPs:\n"
        for tlv in self.tlvs:
            if isinstance(tlv, LSPEntryTLV):
                note += f"\t{tlv}\n"
        return note


class PSNPPDU(IsisPDU):
    """
    Request any PDUs that we believe are old or absent
    """

    def __init__(self, source_address):
        super().__init__(source_address, "L1 PSNP")

        self.tlvs = []


class LinkStatePDU(IsisPDU):
    """
    Information about about LSPs we know about.
    They do not have to be ones we generated
    """

    def __init__(self, source_address, lsp_id, seq_no):
        super().__init__(source_address, "L1 LSP")
        self.lsp_id = lsp_id
        self.seq_no = seq_no

        self.tlvs = []

    @property
    def neighbors(self):
        return [tlv for tlv in self.tlvs if isinstance(tlv, ExtendedISReachabilityTLV)]

    @property
    def addresses(self):
        return [tlv for tlv in self.tlvs if isinstance(tlv, ExtendedIPReachabilityTLV)]

    @property
    def routerid(self):
        routertlv = [tlv for tlv in self.tlvs if isinstance(tlv, TrafficEngineeringIPRouter)]
        for tlv in routertlv:
            return tlv.address
        return None

    def remove_neighbor(self, system_id):
        found = False
        new_tlvs = []
        for tlv in self.tlvs:
            if isinstance(tlv, ExtendedISReachabilityTLV):
                if tlv.system_id == system_id:
                    found = True
                    continue
            new_tlvs.append(tlv)
        self.tlvs = new_tlvs
        return found

    @property
    def hostname(self):
        hosttlv = [tlv for tlv in self.tlvs if isinstance(tlv, DynamicHostnameTLV)]
        for tlv in hosttlv:
            return tlv.hostname
        return None

    def __str__(self):
        if self.hostname is not None:
            return f"LSP {self.hostname}({self.lsp_id}).00,seq={self.seq_no}"
        else:
            return f"LSP {self.lsp_id}.00,seq={self.seq_no}"

    def extensive(self):
        mystring = str(self)

        for tlv in self.tlvs:
            mystring += "\n\t" + tlv.extensive()

        return mystring


    def seq_note(self):
        note = f"IPs {self.lsp_id if self.hostname is None else self.hostname} can reach:\n"
        for tlv in self.tlvs:
            if isinstance(tlv, ExtendedIPReachabilityTLV):
                note += f"\t{tlv.prefix}\n"
        note += f"\nNeighbors:\n"
        for tlv in self.tlvs:
            if isinstance(tlv, ExtendedISReachabilityTLV):
                note += f"\t{tlv.system_id}\n"

        return note
