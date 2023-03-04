from routersim.server import Server
from routersim.router import Router
from routersim.topology import Topology
from routersim.junos import parser as junos
from scapy.layers.inet import IP
from scapy.sendrecv import send
import logging

logging.basicConfig()

topology = Topology("My Topo")
host = Server("pc1")
host.logger.setLevel('DEBUG')

hostint = host.interface("et1")
host.add_logical_interface(hostint, "et1.0", addresses={'ip': '10.1.1.100/24'})


router = Router("r1", "192.168.1.1")
router.logger.setLevel('DEBUG')


r1et1 = router.add_physical_interface("et1")
router.add_logical_interface(r1et1, "et1.0", addresses={'ip': '10.1.1.1/24'})


link = hostint.connect(r1et1)

host.static_route("0.0.0.0/0", "10.1.1.1", "et1.0")



