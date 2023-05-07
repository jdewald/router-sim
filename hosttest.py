from routersim.server import Server
from routersim.router import Router
from routersim.topology import Topology
from routersim.junos import parser as junos
from simhelpers import frame_sequence
import logging

logging.basicConfig()

topology = Topology("My Topo")
host = topology.add_server("pc1")
host2 = topology.add_server("pc2")
host.logger.setLevel('DEBUG')

hostint = host.interface("et1")
host.add_logical_interface(hostint, "et1.0", addresses={'ip': '10.1.1.100/24'})

hostint2 = host2.interface("et1")
host2.add_logical_interface(hostint2, "et1.0", addresses={'ip': '10.1.2.100/24'})

router = topology.add_router("r1", "192.168.1.1")
router.logger.setLevel('DEBUG')


r1et1 = router.add_physical_interface("et1")
router.add_logical_interface(r1et1, "et1.0", addresses={'ip': '10.1.1.1/24'})

r1et2 = router.add_physical_interface("et2")
router.add_logical_interface(r1et2, "et2.0", addresses={'ip': '10.1.2.1/24'})

link = hostint.connect(r1et1)

hostint2.connect(r1et2)

host.static_route("0.0.0.0/0", "10.1.1.1", "et1.0")
host2.static_route("0.0.0.0/0", "10.1.2.1", "et1.0")

topology.run_another(100)

host.ping("10.1.2.100", count=2)

events = topology.run_another(5000)
with open("hostping.puml", "w") as f:
    sequence = frame_sequence("Sending PING", [host, router, host2], events)
    f.write(sequence.render_syntax())

f = junos.parse("show route")
f(router)


