from ipaddress import IPv4Address


class ExplicitRouteObject:
    # IP Address or ASN
    def __init__(self, route, strict=True):
        self.route = route
        self.strict = strict

    def __str__(self):
        return f"{self.route} ({'S' if self.strict else 'L'}"


class RecordRouteObject:
    # IP Address or ASN
    def __init__(self, address):
        self.address = address

    def __str__(self):
        return f"{self.address}"


class LabelRequest:
    def __init__(self):
        # ipv4
        self.type = 0x0800


class RsvpHop:
    def __init__(self, hop_address):
        # either an ipv4 or ipv6 address
        self.hop_address = hop_address


class Session:
    tunnelid = 0

    def __init__(self, dest_ip, tunnel_id, source_ip):
        self.dest_ip = dest_ip
        self.tunnel_id = tunnel_id
        self.source_ip = source_ip

    @staticmethod
    def newSession(dest_ip, source_ip):
        Session.tunnelid += 1
        return Session(dest_ip, Session.tunnelid, source_ip)


class IPV4SenderTemplate:
    def __init__(self, address: IPv4Address, lsp_id: int):
        self.address = address
        self.lsp_id = lsp_id

    def __str__(self):
        return f"Sender: {self.address}/lsp={self.lsp_id}"

class FilterSpec:
    def __init__(self, address: IPv4Address, lsp_id: int):
        self.address = address
        self.lsp_id = lsp_id

    def __str__(self):
        return f"Filter: {self.address}/lsp={self.lsp_id}"


class Label:
    def __init__(self, label: int):
        self.label = label

    def __str__(self):
        return f"Label: {self.label}"


class LSPTunnelSessionAttribute:
    def __init__(self, name,
                 local_repair=True,
                 record_labels=True,
                 shared_explicit=False,
                 reserve_bw=False,
                 node_repair=True,
                 hold=0,
                 setup=7):
        self.name = name
        self.local_repair = local_repair
        self.record_labels = record_labels
        self.shared_explicit = shared_explicit
        self.reserve_bw = reserve_bw
        self.node_repair = node_repair
        self.hold = hold
        self.setup = setup

    def __str__(self):
        return f"TSA: {self.name} LR={self.local_repair}"