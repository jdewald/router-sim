from routersim.server import Server
from routersim.switching.switch import Switch
from routersim.topology import Topology
from routersim.junos import parser as junos
import logging

logging.basicConfig()

topology = Topology("My Topo")

switch = Switch("sw1")
switch.logger.setLevel("DEBUG")

switch2 = Switch("sw2")
switch2.logger.setLevel("DEBUG")

switch3 = Switch("sw3")
switch3.logger.setLevel("DEBUG")

host = Server("pc1")
host.logger.setLevel('DEBUG')

hostint = host.interface("et1")
host.add_logical_interface(hostint, "et1.0", addresses={'ip': '10.1.1.100/24'})


host2 = Server("pc2")
host2.logger.setLevel('DEBUG')
host2int = host2.interface('et1')
host2.add_logical_interface(host2int, "et1.0", addresses={'ip': '10.1.1.102/24'})

host3 = Server("pc3")
host3int = host3.interface('et1')
host3.logger.setLevel('DEBUG')
host3.add_logical_interface(host3int, "et1.0", addresses={'ip': '10.1.1.103/24'})


#router = Router("r1", "192.168.1.1")
#router.logger.setLevel('DEBUG')


#r1et1 = router.add_physical_interface("et1")
#router.add_logical_interface(r1et1, "et1.0", addresses={'ip': '10.1.1.1/24'})



# Each host is connected to its own switch
switch.interface('et1').connect(hostint, latency_ms=1)
switch2.interface('et1').connect(host2int, latency_ms=1)
switch3.interface('et1').connect(host3int, latency_ms=1)

switch.interface('et10').connect(switch2.interface('et10'), latency_ms=1)
switch2.interface('et11').connect(switch3.interface('et10'), latency_ms=1)

#link = hostint.connect(r1et1)

#host.static_route("0.0.0.0/0", "10.1.1.1", "et1.0")
topology.run_another(100)

host.ping("10.1.1.103", count=2)

topology.run_another(5000)


switch.run_junos_op("show ethernet-switching table")

# Now we'll create a loop...
switch3.interface('et9').connect(switch.interface('et11'))

host.ping("10.1.1.102", count=2)
topology.run_another(500)