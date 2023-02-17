from routersim.observers import EventType
from plantuml import Sequence, ObjectDiagram, ComponentDiagram


def topology_diagram(title, topo_data, events=None):
    diagram = ObjectDiagram(title)

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

    return diagram


def isis_sequence(title, routers, events=None):
    """
    Start a Sequence diagram which will be used to render IS-IS convergence
    
    Most usefully used in conjunction with isis_sequence_add_event which
    knows which events to look for

    Also assumes that it'll be fed events where the src name corresponds to the
    router hostname
    """
    sequence = Sequence(title)

    for router in routers:
        sequence.actor(router.hostname, type='entity', group=router.hostname)
        sequence.actor(f"{router.hostname}.ISIS", type='control', group=router.hostname)
        sequence.actor(f"{router.hostname}.routing", type="database", group=router.hostname)

    start_time = 0
    if events is not None:
        for evt_data in events:
            if start_time == 0:
                start_time = evt_data[1].when
            isis_sequence_add_event(
                sequence,
                evt_data[0],  # source router
                evt_data[1],
                start_time=start_time
            )

    return sequence

def frame_sequence(title, routers, events=None,l3=True):
    sequence = Sequence(title)

    for router in routers:
        sequence.actor(router.hostname, type='entity', group=router.hostname)
        sequence.actor(f"{router.hostname}.pfe", type='entity', group=router.hostname)

    start_time = 0
    if events is not None:
        for evt_data in events:
            if start_time == 0:
                start_time = evt_data[1].when
            frame_sequence_add_event(
                sequence,
                evt_data[0],  # source router
                evt_data[1],
                start_time=start_time,
                l3=l3,
            )


    return sequence


def packet_sequence(title, routers, events=None):

    sequence = Sequence(title)

    for router in routers:
        sequence.actor(router.hostname, type='entity', group=router.hostname)
        sequence.actor(f"{router.hostname}.pfe", type='entity', group=router.hostname)

    start_time = 0
    if events is not None:
        for evt_data in events:
            if start_time == 0:
                start_time = evt_data[1].when
            packet_sequence_add_event(
                sequence,
                evt_data[0],  # source router
                evt_data[1],
                start_time=start_time
            )


    return sequence
    
def rsvp_sequence(title, routers, events=None):
    """
    Start a Sequence diagram which will be used to render RSVP/MPLS events
    
    """
    sequence = Sequence(title)

    for router in routers:
        sequence.actor(router.hostname, type='entity', group=router.hostname)
#        sequence.actor(f"{router.hostname}.pfe", type='entity', group=router.hostname)
#        sequence.actor(f"{router.hostname}.RSVP", type='control', group=router.hostname)
        sequence.actor(f"{router.hostname}.routing", type="database", group=router.hostname)

    if events is not None:
        for evt_data in events:
            rsvp_sequence_add_event(
                sequence,
                evt_data[0],  # source router
                evt_data[1]
            )

    return sequence

# Add event intended to track IS-IS convergence
def isis_sequence_add_event(sequence, src_name, evt, start_time=0):
    # TODO: I would like this to all be unified so
    # there isn't a bunch of complex logic
    # but need to develop the use caess first

    # TODO: Dynamically discover group membership


    if evt.event_type == EventType.PACKET_SEND:
        notefn = getattr(evt.object.pdu, "seq_note", None)
        if notefn is not None:
            note = notefn()
        else:
            note = None

        if evt.sub_type == "LOCAL_SEND":
            hostname = f"{src_name}"
            note = None
        else:
            src_name = f"{src_name}"
            iface = evt.target
            routeroriface = iface.parent
            hostname = getattr(routeroriface, "hostname", None)
            if hostname is None:
                hostname = routeroriface.parent.hostname

        sequence.actor(src_name).send_message(
            sequence.actor(hostname),
            f"[{evt.when-start_time}] {evt.object.pdu}",
            note=note
        )
    elif evt.event_type == EventType.ISIS:

        sequence.actor(f"{src_name}.ISIS").send_message(
            sequence.actor(f"{src_name}.ISIS"),
            evt.msg,
        )
    elif evt.event_type == EventType.ROUTE_CHANGE:

        src = src_name
        if str(evt.source) != src_name:
            src = f"{src_name}.{evt.source}"
        sequence.actor(f"{src}").send_message(
            sequence.actor(f"{src_name}.routing"),
            evt.msg,
            note=evt.object.seq_note()
        )

def frame_sequence_add_event(sequence, src_name, evt, start_time=0,l3=True):
    # TODO: I would like this to all be unified so
    # there isn't a bunch of complex logic
    # but need to develop the use caess first

    # TODO: Dynamically discover group membership

    if evt.event_type == EventType.PACKET_SEND:

        if evt.object.type.name == 'CLNS':
            return

        notefn = getattr(evt.object.pdu, "seq_note", None)
        if notefn is not None:
            note = notefn()
        else:
            note = None

        if evt.sub_type == "LOCAL_SEND":
            hostname = f"{src_name}.pfe"
            note = None
        else:
            src_name = f"{src_name}.pfe"
            iface = evt.target
            routeroriface = iface.parent    
            hostname = getattr(routeroriface, "hostname", None)
            if hostname is None:
                hostname = routeroriface.parent.hostname

        sequence.actor(src_name).send_message(
            sequence.actor(f"{hostname}"),
            f"[{evt.when-start_time}] {evt.object}",
            note=note
        )
    elif evt.event_type == EventType.MPLS:
        sequence.actor(f"{src_name}.pfe").send_message(
           sequence.actor(f"{src_name}.pfe"),
           f"[{evt.when-start_time}] {evt.msg}"
        )

def packet_sequence_add_event(sequence, src_name, evt, start_time=0):
    # TODO: I would like this to all be unified so
    # there isn't a bunch of complex logic
    # but need to develop the use caess first

    # TODO: Dynamically discover group membership

    if evt.event_type == EventType.PACKET_SEND:

        if evt.object.type.name == 'CLNS':
            return

        notefn = getattr(evt.object.pdu, "seq_note", None)
        if notefn is not None:
            note = notefn()
        else:
            note = None

        if evt.sub_type == "LOCAL_SEND":
            hostname = f"{src_name}.pfe"
            note = None
        else:
            src_name = f"{src_name}.pfe"
            iface = evt.target
            routeroriface = iface.parent
            hostname = getattr(routeroriface, "hostname", None)
            if hostname is None:
                hostname = routeroriface.parent.hostname

        sequence.actor(src_name).send_message(
            sequence.actor(f"{hostname}"),
            f"[{evt.when-start_time}] {evt.object.pdu}",
            note=note
        )
    elif evt.event_type == EventType.MPLS:
        sequence.actor(f"{src_name}.pfe").send_message(
           sequence.actor(f"{src_name}.pfe"),
           f"[{evt.when-start_time}] {evt.msg}"
        )


# Add event intended to track IS-IS convergence
def rsvp_sequence_add_event(sequence, src_name, evt):
    # TODO: I would like this to all be unified so
    # there isn't a bunch of complex logic
    # but need to develop the use caess first

    # TODO: Dynamically discover group membership

    if evt.event_type == EventType.PACKET_SEND:
        if evt.object.type.name == 'CLNS':
            return
        notefn = getattr(evt.object.pdu, "seq_note", None)
        if notefn is not None:
            note = notefn()
        else:
            note = None

        if evt.sub_type == "LOCAL_SEND":
            return
            hostname = f"{src_name}.pfe"
            note = None
        else:
            iface = evt.target
            routeroriface = iface.parent
            hostname = getattr(routeroriface, "hostname", None)
            if hostname is None:
                hostname = routeroriface.parent.hostname
#            src_name = f"{src_name}.pfe"
            src_name = f"{src_name}"
            iface = evt.target
            routeroriface = iface.parent
            hostname = getattr(routeroriface, "hostname", None)
            if hostname is None:
                hostname = routeroriface.parent.hostname

        sequence.actor(src_name).send_message(
            sequence.actor(hostname),
            evt.object.pdu,
            note=note
        )
    elif evt.event_type == EventType.RSVP:

        sequence.actor(f"{src_name}").send_message(
            sequence.actor(f"{src_name}"),
            evt.msg,
        )
#        sequence.actor(f"{src_name}.RSVP").send_message(
#            sequence.actor(f"{src_name}.RSVP"),
#            evt.msg,
#        )
    elif evt.event_type == EventType.ROUTE_CHANGE:
        src = src_name
        if str(evt.source) != src_name:
            src = f"{src_name}.{evt.source}"

        #notefn = getattr(evt.object.pdu, "seq_note", None)
        sequence.actor(f"{src}").send_message(
            sequence.actor(f"{src_name}.routing"),
            evt.msg,
            note=evt.object.seq_note()
        )
    elif evt.event_type == EventType.MPLS:
        sequence.actor(f"{src_name}.pfe").send_message(
           sequence.actor(f"{src_name}.pfe"),
           evt.msg
        )


def topology_component(title, topo_data):
    
    diagram = ComponentDiagram(title)
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

    return diagram


def topology_object(title, topo_data):
    diagram = ObjectDiagram(title)

    for cluster in topo_data['clusters']:
        for routerdata in cluster['systems']:
            actor = diagram.actor(routerdata['name'], type='map', group=cluster['name'])
            for ifaceinfo in routerdata['interfaces']:
                actor.add_mapping(ifaceinfo['name'], ifaceinfo['address'])

    # This is kind of cheating... but still need best way to 
    # make the diagram
    for link in topo_data['links']:
        diagram.send_message(
            link['endpoint1']['system'] + "::" + link['endpoint1']['iface'],
            link['endpoint2']['system'] + "::" + link['endpoint2']['iface'])

    return diagram
