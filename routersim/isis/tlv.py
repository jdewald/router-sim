class TLV:

    def __init__(self, name, id):
        self.name = name
        self.id = id

    def __str__(self):
        return f"{self.name}({self.id})"

    def extensive(self):
        return str(self)


class P2PAdjacencyTLV(TLV):

    def __init__(self, system_id, state='Down'):
        super().__init__("P2P Adjacency", 240)
        self.system_id = system_id
        self.state = state


class AreaAddressTLV(TLV):
    def __init__(self, address):
        super().__init__("Area Adress", 1)
        self.address = address

    def __str__(self):
        return f"{super()}\n\tAddress: {self.address}"


class IPAddressTLV(TLV):
    def __init__(self, address):
        super().__init__("IP Address", 132)
        self.address = address

    def __str__(self):
        return f"{super()}\n\tIP Address: {self.address})"

    def extensive(self):
        return "\t" + self.__str__()


class IPInterfaceAddressTLV(TLV):
    def __init__(self, address, status):
        super().__init__("IP Address", 6)
        self.address = address
        self.status = status

    def __str__(self):
        return f"\tIP Address: {self.address} ({self.status})"

    def extensive(self):
        return "\t" + self.__str__()


class NeighborIPAddressTLV(TLV):
    def __init__(self, address):
        super().__init__("IP Address", 8)
        self.address = address

    def __str__(self):
        return f"\tNeighbor IP Address: {self.address}"

    def extensive(self):
        return "\t" + self.__str__()


class TrafficEngineeringIPRouter(TLV):
    def __init__(self, address):
        super().__init__("TE IP Router ID", 134)
        self.address = address

    def __str__(self):
        return f"IP router id: {self.address}"

    def extensive(self):
        return "\t" + self.__str__()

class ExtendedISReachabilityTLV(TLV):
    def __init__(self, system_id, metric):
        super().__init__("Extended IS Reachability", 22)
        self.system_id = system_id
        self.metric = metric
        self.hostame = None
        self.tlvs = []

    def __str__(self):
        returnstr = f"Extended neighbor: {self.system_id} metric={self.metric}"
        return returnstr

    def extensive(self):
        mystr = str(self)

        for tlv in self.tlvs:
            mystr += "\n\t" + tlv.extensive()

        return mystr

    @property
    def local_ip(self):
        tlv = [tlv for tlv in self.tlvs if isinstance(tlv, IPInterfaceAddressTLV)]
        for t in tlv:
            return t.address
        return None

    @property
    def neighbor_ip(self):
        tlv = [tlv for tlv in self.tlvs if isinstance(tlv, NeighborIPAddressTLV)]
        for t in tlv:
            return t.address
        return None


class ExtendedIPReachabilityTLV(TLV):
    def __init__(self, prefix, metric, state, type='Internal'):
        super().__init__("Extended IP Reachability", 135)
        self.prefix = prefix
        self.metric = metric
        self.state = state
        self.type = type
        self.tlvs = []

    def __str__(self):
        returnstr = f"Extended IP: {self.prefix} metric={self.metric} state={self.state}"
        return returnstr

    def extensive(self):
        mystr = str(self)

        for tlv in self.tlvs:
            mystr += "\n\t" + tlv.extensive()

        return mystr


class LSPEntryTLV(TLV):
    def __init__(self, lsp_id, seq_no, remaining_lifetime, hostname=None):
        super().__init__("LSP Entry", 9)
        self.lsp_id = lsp_id
        self.seq_no = seq_no
        self.remaining_lifetime = remaining_lifetime
        self.hostname = hostname

    def __str__(self):
        if self.hostname is not None:
            return f"{self.hostname}.00 seq={self.seq_no}"
        else:
            return f"{self.lsp_id}.00 seq={self.seq_no}"


class DynamicHostnameTLV(TLV):
    def __init__(self, hostname):
        super().__init__("Dynamic Hostname", 137)
        self.hostname = hostname
