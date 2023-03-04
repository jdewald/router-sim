from scapy.interfaces import IFACES, InterfaceProvider, NetworkInterface, \
    network_name

from scapy.supersocket import SuperSocket
from scapy.route import Route
from scapy.config import conf as scapy_conf
from .routing import RoutingTables


class RouterSimNetworkInterface(NetworkInterface):

    def __init__(self, intf, provider, data=None):
        self.base_intf = intf
        super().__init__(provider, data)

class RouterSimInterfaceProvider(InterfaceProvider):
    
    def l2socket(self):
        raise "NotImplemented"
    
    def l2listen(self):
        raise "NotImplemented"
    
    def l3socket(self):
        return RouterSimL3Socket

class RouterSimRoute(Route):

    def __init__(self, routing: RoutingTables):
        # not calling super
        self.routing = routing

    def route(self, dst=None, verbose=scapy_conf.verb):
        # returns (iface, output_ip, gateway_ip)
    
        r = self.routing.lookup_ip(dst)

        if r is None:
            raise Exception(f"{dst}: no route to host")
        
        intf = r.interface

        # TODO: We need to update the route tables to
        # have the source IP, so we can have multiple
        # on the interface
        # we also need to support V6!
        return (
            RouterSimNetworkInterface(intf, RouterSimInterfaceProvider()),
            intf.address("ipv4"),
            r.next_hop_ip,
        )

class RouterSimL3Socket(SuperSocket):

    def send(self, x):

        # should be logical
        iface = self.iface.base_intf
        if not self.iface.base_intf.is_physical():
            iface = self.iface.base_intf.parent
        # should be a server/netdevice which can do ARP and whatnot
        iface.parent.send_ip(x, self.iface.base_intf)