from routersim.server import Server
from routersim.router import Router
from routersim.topology import Topology
from routersim.junos import parser as junos
from simhelpers import frame_sequence, packet_sequence

from routersim.dhcp import DHCPserver
import logging

logging.basicConfig()



homenetwork = Topology("My LAN")

switch = homenetwork.add_switch("sw1")
pc1 = homenetwork.add_server("pc1")
pc2 = homenetwork.add_server("pc2")

# we need a static address for our dns server... otherwise it would
# need to get it from DHCP... oh no!
infra = homenetwork.add_server("server", interface_addr="192.168.1.10/24")


#infra.logger.setLevel('INFO')
#pc1.logger.setLevel('INFO')
#pc2.logger.setLevel('INFO')

# By default within this network sim, the first interface will
# be called et1. You could of course use 'eth0' or whatever
# you might prefer.
# The reason it is set up this way is that this simulator started out
# as a means of simulating some features in Juniper routers, and they
# use the `et` naming.
#pc1.add_ip_address('et1', '192.168.1.100/24')
#pc2.add_ip_address('et1', '192.168.1.200/24')

switch.interface('et1').connect(pc1.interface('et1'), latency_ms=1)
switch.interface('et2').connect(pc2.interface('et1'), latency_ms=1)
switch.interface('et3').connect(infra.interface('et1'), latency_ms=1)

dhcp_service = DHCPserver(infra)

dhcp_service.start()


pc1.dhcp_client_start()

events = homenetwork.run_another(5000)
with open("dhcp.puml", "w") as f:
    sequence = frame_sequence("DHCP Allocation", [pc1, infra], events)
    f.write(sequence.render_syntax())

pc2.dhcp_client_start()
homenetwork.run_another(2000)

# returned address as an interface address: ip/prefixlen
pc1.ping(pc2.interface('et1.0').address().ip, count=2)

with open("dhcpping.puml", "w") as f:
    events = homenetwork.run_another(1000)
    sequence = frame_sequence("Ping", [pc1, switch, pc2], events)
    f.write(sequence.render_syntax())



