from routersim.router import Router
from routersim.topology import Topology
from routersim.observers import EventType, GlobalQueueManager
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

#r1.logger.setLevel("INFO")
#r3.logger.setLevel("INFO")

r1.show_isis_database()

sequence = packet_sequence("Sending PING", [r1, r2, r3])
r3.ping(ipaddress.ip_address("100.65.0.0"))

events = topology.run_another(500)

with open("ping.puml", "w") as f:
    for evt_data in events:
        packet_sequence_add_event(
            sequence,
            evt_data[0],  # source router
            evt_data[1]
        )
    f.write(sequence.render_syntax())


