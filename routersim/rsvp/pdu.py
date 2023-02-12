from .object import *
from ..messaging import RSVPMessage



class Path(RSVPMessage):
    def __init__(self, session: Session,
                 sender: IPV4SenderTemplate,
                 attribute: LSPTunnelSessionAttribute):

        self.session = session
        self.sender = sender
        self.attributes = attribute
        # For now, just assuming all Path messages have a LaelRequest
        # for IpV4 services
        self.explicit_route = []
        self.record_route = []

    def set_hop(self, hop_address):
        self.hop = RsvpHop(hop_address)

    def add_record(self, address):
        self.record_route.append(RecordRouteObject(address))

    def add_explicit(self, route):
        self.explicit_route.append(ExplicitRouteObject(route))

    def __str__(self):
        return f"RSVP Path"

    def key(self):
        return (str(self.session.dest_ip), 
                str(self.session.tunnel_id),
                str(self.sender.lsp_id))

    def seq_note(self):
        mystring = f"Requesting LSP {self.attributes.name}\n"
        mystring += f"\tThis hop is {self.hop.hop_address}\n"
        mystring += f"\tERO request: {' '.join([str(r.route) for r in self.explicit_route])}\n"
        mystring += f"\tRecorded: {' '.join([str(r.address) for r in self.record_route])}"

        return mystring
    


class PathErr(RSVPMessage):
    def __init__(self):
        pass

class PathTear(RSVPMessage):
    def __init__(self):
        pass


class Resv(RSVPMessage):
    def __init__(self, session: Session,
                 filter: FilterSpec):

        self.session = session
        self.filter = filter
        self.label = None
        self.explicit_route = []
        self.record_route = []

    def set_hop(self, hop_address):
        self.hop = RsvpHop(hop_address)

    def set_label(self, label):
        self.label = label

    def add_record(self, address):
        self.record_route.append(RecordRouteObject(address))

    def __str__(self):
        return f"RSVP Resv"

    def key(self):
        # The key is actually supposed to just be (dest, tunnel_id)
        # But maybe tunnel id is more complete
        return (str(self.session.dest_ip),
                str(self.session.tunnel_id),
                str(self.filter.address),
                str(self.filter.lsp_id),
                str(self.hop.hop_address))

    def seq_note(self):
        mystring = f"RESV\n"
        mystring += f"\tApply label {self.label}\n"
        mystring += f"\tThis hop is {self.hop.hop_address}\n"
        mystring += f"\tRecorded: {' '.join([str(r.address) for r in self.record_route])}"

        return mystring


class ResvTear(RSVPMessage):
    def __init__(self):
        pass


class ResvErr(RSVPMessage):
    def __init__(self):
        pass
