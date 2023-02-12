from routersim.mpls import PopStackOperation
from routersim.router import Router
from routersim.topology import Topology
from routersim.observers import EventType, GlobalQueueManager
from routersim.mpls import PushStackOperation, MPLSPacket
from routersim.routing import BGPRoute, RSVPRoute
from plantuml import Sequence, ObjectDiagram
from simhelpers import isis_sequence, isis_sequence_add_event
from simhelpers import packet_sequence, packet_sequence_add_event
from functools import partial

import ipaddress
import logging


logging.basicConfig()


topology = Topology("My Topology!")
topology.logger.setLevel("INFO")

r1 = topology.add_router("r1", interfaces=['et1', 'et2'])
r2 = topology.add_router("r2", interfaces=['et1', 'et2'])
topology.link_router_pair(r1, r2)

topology.isis_enable_all()
topology.isis_start_all()

sequence = isis_sequence("Two Router Convergence", [r1, r2])

#r1.event_manager.listen('*', partial(isis_sequence_add_event, sequence, r1))
#r2.event_manager.listen('*', partial(isis_sequence_add_event, sequence, r2))

events = topology.run_until(30000) # 15s

with open("seq1.puml", "w") as f:
    for evt_data in events:
        isis_sequence_add_event(
            sequence,
            evt_data[0],  # source router
            evt_data[1]
        )
    f.write(sequence.render_syntax())


# Now let's try adding another router connected to r2

r3 = topology.add_router("r3", interfaces=['et1'])

sequence = isis_sequence("IS-IS Reconvergence with 3rd Router", [r1, r2, r3])

topology.link_router_pair(r2, r3)


topo_data = topology.get_topology()
with open("topology.puml", "w") as f:
    diagram = ObjectDiagram(topology.name)

    cluster1 = topo_data['clusters'][0]

    for routerdata in cluster1['systems']:
        actor = diagram.actor(routerdata['name'], type='map')
        for ifaceinfo in routerdata['interfaces']:
            actor.add_mapping(ifaceinfo['name'], ifaceinfo['address'])

    # This is kind of cheating... but still need best way to 
    # make the diagram
    for link in topo_data['links']:
        diagram.send_message(link['endpoint1'], link['endpoint2'])

    f.write(diagram.render_syntax())
# This is a safe operation, as it won't re-add
# interfaces which are already enabled
#topology.isis_enable_all()

# but can also enable manually
r3.enable_isis(r3.interface('lo.0'), passive=True)
r3.enable_isis(r3.interface('et1.0'))
r2.enable_isis(r2.interface('et2.0'))

r3.start_isis()

events = topology.run_another(30000)

with open("seq2.puml", "w") as f:
    for evt_data in events:
        isis_sequence_add_event(
            sequence,
            evt_data[0],  # source router
            evt_data[1]
        )
    f.write(sequence.render_syntax())

print("=== R1 Routing Table ===")
r1.routing.print_routes()
print("")

print("=== R2 Routing Table ===")
r2.routing.print_routes()
print("")

print("=== R3 Routing Table ===")
r3.routing.print_routes()
print("")

r1.routing.add_route(
    BGPRoute(
        ipaddress.ip_network("10.1.42.0/24"),
        None,  # we don't necessarily know the iface
        ipaddress.ip_address("10.10.10.10"),  # maybe?
        ['I'],
        r3.interface('lo.0').address().ip,
    ),
    'bgp'
)

# Note that we've learned a route 
r1.routing.add_route(
    RSVPRoute(
        r3.interface('lo.0').address().network,
        r1.interface('et1.0'),
        r2.interface('et1.0').address(),
        lsp_name="lsp-r1-to-r3",
        action=PushStackOperation(42)
    ),
    'rsvp'  # basically inet.3
)

print("=== R1 Routing Table ===")
r1.routing.print_routes()
print("")

# This is actually the end of our line here
r2.routing.add_route(
    RSVPRoute(
        "42",
        r2.interface('et2.0'),
        r3.interface('et1.0').address(),
        lsp_name="lsp-r1-to-r3",
        action=PopStackOperation()
    ),
    'mpls'
)

print("=== R2 Routing Table ===")
r2.routing.print_routes()
print("")

print("==== R2 FIB ====")
r2.pfe.forwarding.print_fib()
print("")

sequence = packet_sequence("Sending PING over MPLS", [r1, r2, r3])
r1.ping(ipaddress.ip_address("10.1.42.2"))

events = topology.run_another(500)

with open("mplsping.puml", "w") as f:
    for evt_data in events:
        packet_sequence_add_event(
            sequence,
            evt_data[0],  # source router
            evt_data[1]
        )
    f.write(sequence.render_syntax())