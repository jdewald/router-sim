from routersim.mpls import PopStackOperation
from routersim.router import Router
from routersim.topology import Topology
from routersim.observers import EventType, GlobalQueueManager
from routersim.mpls import PushStackOperation, MPLSPacket
from routersim.routing import BGPRoute, RSVPRoute
from plantuml import Sequence, ObjectDiagram, ComponentDiagram
from simhelpers import rsvp_sequence, rsvp_sequence_add_event
from simhelpers import packet_sequence, packet_sequence_add_event
from functools import partial

import ipaddress
import logging


logging.basicConfig()


topology = Topology("My Topology!")
topology.logger.setLevel("INFO")

outside = topology.add_router("outside", interfaces=['et1'], cluster_name="outside")

gxx = topology.add_router("gxx", interfaces=['et1', 'et2', 'et3'], cluster_name="backbone")
mxx = topology.add_router("mxx", interfaces=['et1', 'et2', 'et3'], cluster_name="backbone")
jxx = topology.add_router("jxx", interfaces=['et1', 'et2', 'et3', 'et4'], cluster_name="backbone")
ixx = topology.add_router("ixx", interfaces=['et1', 'et2', 'et3', 'et4', 'et5'], cluster_name="backbone")
axx = topology.add_router('axx', interfaces=['et1', 'et2', 'et3'], cluster_name="backbone")
lxx = topology.add_router('lxx', interfaces=['et1', 'et2'], cluster_name="backbone")
ayy = topology.add_router('ayy', interfaces=['et1', 'et2', 'et3'], cluster_name="backbone")
fxx = topology.add_router('fxx', interfaces=['et1', 'et2', 'et3'], cluster_name="backbone")
dxx = topology.add_router('dxx', interfaces=['et1', 'et2', 'et3'], cluster_name="backbone")
oxx = topology.add_router('oxx', interfaces=['et1', 'et2', 'et3', 'et4'], cluster_name="backbone")
gxx_mxx = topology.link_router_pair(gxx, mxx, te_metric=9210)
gxx_jxx = topology.link_router_pair(gxx, jxx, te_metric=14530)
mxx_axx = topology.link_router_pair(mxx, axx, te_metric=3025)
mxx_dxx = topology.link_router_pair(mxx, dxx, te_metric=6017)

axx_ixx = topology.link_router_pair(axx, ixx, te_metric=3230)
topology.link_router_pair(axx, dxx, te_metric=1839)

jxx_ixx = topology.link_router_pair(jxx, ixx, te_metric=412)
topology.link_router_pair(lxx, ayy, te_metric=717)
topology.link_router_pair(jxx, oxx, te_metric=1976)

jxx_lxx = topology.link_router_pair(jxx, lxx, te_metric=10000)
topology.link_router_pair(ixx, ayy, te_metric=10000)
topology.link_router_pair(ixx, fxx, te_metric=10000)

topology.link_router_pair(dxx, oxx, te_metric=5095)
topology.link_router_pair(oxx, ixx, te_metric=3249)

topology.link_router_pair(fxx, ayy, te_metric=780)

topology.link_router_pair(outside, gxx)

topo_data = topology.get_topology()
with open("full_topology.puml", "w") as f:
    diagram = ObjectDiagram(topology.name)

    cluster1 = topo_data['clusters'][0]

    for routerdata in cluster1['systems']:
        actor = diagram.actor(routerdata['name'], type='map')
        for ifaceinfo in routerdata['interfaces']:
            actor.add_mapping(ifaceinfo['name'], ifaceinfo['address'])

    # This is kind of cheating... but still need best way to 
    # make the diagram
    for link in topo_data['links']:
        diagram.send_message(
            link['endpoint1']['system'] + "::" + link['endpoint1']['iface'],
            link['endpoint2']['system'] + "::" + link['endpoint2']['iface'])

    f.write(diagram.render_syntax())

with open("topology_component.puml", "w") as f:
    diagram = ComponentDiagram(topology.name)

    for cluster in topo_data['clusters']:
        for routerdata in cluster['systems']:
            actor = diagram.actor(routerdata['name'], group=cluster['name'])

    # This is kind of cheating... but still need best way to 
    # make the diagram
    for link in topo_data['links']:
        diagram.actor(link['endpoint1']['system']).send_message(
            diagram.actor(link['endpoint2']['system']),
            ""
        )

    f.write(diagram.render_syntax())

outside.static_route("0.0.0.0/0", "et1.0")

topology.isis_enable_all(cluster_name="backbone")
topology.isis_start_all(cluster_name="backbone")

events = topology.run_until(120000) 

print("=== GXX Routing Table ===")
gxx.routing.print_routes()
print("")


gxx.show_isis_database()

gxx.routing.add_route(
    BGPRoute(
        ipaddress.ip_network("10.1.42.0/24"),
        None,  # we don't necessarily know the iface
        ipaddress.ip_address("10.10.10.10"),  # maybe?
        ['I'],
        ayy.interface('lo.0').address().ip,
    ),
    'bgp'
)


sequence = rsvp_sequence("Building LSP", topology.routers())
gxx.create_lsp('GXX-TO-AYY', ayy.interface('lo.0').address().ip, link_protection=True)

topology.rsvp_start_all(cluster_name="backbone")
#for router in topology.routers(cluster_name="backbone"):
#    router.start_rsvp()
#    router.process['rsvp'].logger.setLevel('WARNING')

events = topology.run_another(200000)

print("=== GXX Routing Table ===")
gxx.routing.print_routes()
print("")

with open("full_rsvp.puml", "w") as f:
    for evt_data in events:
        rsvp_sequence_add_event(
            sequence,
            evt_data[0],  # source router
            evt_data[1]
        )

    f.write(sequence.render_syntax())

with open("mpls_routes.puml", "w") as f:
    diagram = ObjectDiagram("RSVP Routes")

    link_src = {}
    link_dst = {}

    for router in topology.routers():
        rsvp_routes = router.routing.inet3
        mpls_routes = router.routing.mpls

        actor = diagram.actor(router.hostname, type='map')

        for prefix in rsvp_routes:
            route = rsvp_routes[prefix][0]

            # assumption is the RSVP routes are 
            # being used to hop onto MPLS
            next_label = route.action.new_label

            link_src[str(next_label)] = router.hostname
            actor.add_mapping(str(prefix), route.lsp_name + "," + str(route.action))

        # These are incoming -> outgoing labels
        for label in mpls_routes:
            route = mpls_routes[label][0]
            next_label = route.action.new_label
            if next_label is not None:
                link_src[str(next_label)] = router.hostname

            actor.add_mapping(str(label), route.lsp_name + "," + str(route.action))
            link_dst[str(label)] = router.hostname

    for label in link_dst:
        end2 = '::'.join([link_dst[label], label])
        if label in link_src:
            end1 = '::'.join([link_src[label], label])
            diagram.send_message(end1, end2)

    f.write(diagram.render_syntax())

#print("=== GXX Forwarding Table ===")
#gxx.pfe.forwarding.print_fib()
#print("")

outside.ping(ipaddress.ip_address("10.1.42.2"), count=1)

print("=== JXX Forwarding Table ===")
jxx.pfe.forwarding.print_fib()

events = topology.run_another(2000)

# Now, we bring down the link that would go to JXX
#gxx_jxx.down()
#jxx_ixx.down()
#axx_ixx.down()

outside.ping(ipaddress.ip_address("10.1.42.2"), count=1)

events.extend(topology.run_another(3000))

#print("=== GXX Routing Table ===")
#gxx.routing.print_routes()
#print("")

#print("=== GXX Forwarding Table ===")
#gxx.pfe.forwarding.print_fib()
#print("")

#print("=== MXX Forwarding Table ===")
#mxx.pfe.forwarding.print_fib()
#print("")

sequence = packet_sequence("Ping via MPLS", topology.routers())
with open("rsvp_ping.puml", "w") as f:
    for evt_data in events:
        packet_sequence_add_event(
            sequence,
            evt_data[0],  # source router
            evt_data[1]
        )

    f.write(sequence.render_syntax())
