from routersim.server import Server
from routersim.switching.switch import Switch
from routersim.topology import Topology
from routersim.junos import parser as junos
import logging

logging.basicConfig()

logger = logging.getLogger()
#logger.setLevel(logging.DEBUG)

topology = Topology("My Topo")

switch = topology.add_switch("sw1")

pc1 = Server('pc1')
pc1.add_ip_address('et1', '192.168.1.100/24')

pc2 = Server('pc2')
pc2.add_ip_address('et1', '192.168.1.200/24')

switch.interface('et1').connect(pc1.interface('et1'), latency_ms=1)
switch.interface('et2').connect(pc2.interface('et1'), latency_ms=1)

pc1.ping("192.168.1.200", count=2)
topology.run_another(500)