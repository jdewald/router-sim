from routersim.router import Router
from routersim.switching.switch import Switch
from routersim.server import Server
from routersim.observers import GlobalQueueManager, EventCollector
import ipaddress
import logging
from functools import reduce, partial
import copy


# This doesn't feel like it belongs here but I don't have a better place yet
class Clock():
    
    def __init__(self):
        self.tick = 0

    def next_tick(self) -> int:
        self.delayfn(1)
        return self.tick

    def clockfn(self) -> int:
        return self.tick

    def delayfn(self, delay):
        self.tick = self.tick + delay


class Topology():
    """Representation of a router topology
    """

    def __init__(self, name="Test Topology", loopback_network=None,
                 area_id="49.0001", clock=None):

        self.clusters = {
            'default': {}
        }
        # TODO: might not keep this
        self._routers = []
        self.logger = logging.getLogger("topology." + name)
        self.collector = EventCollector()
        self.name = name

        self.area_id = area_id

        if clock is None:
            clock = Clock()
            GlobalQueueManager.setup(clock.clockfn, clock.delayfn)
        self.clock = clock

        # When using auto-addressing, addresses will be allocated
        # from here for loopbacks
        if loopback_network is None:
            self.loopback_network = ipaddress.ip_network("192.168.50.0/24")
        else:
            self.loopback_network = loopback_network

        self._loopback_iter = iter(self.loopback_network.hosts())

        # When using auto-addressing, /31s will be allocated from this range
        self.point_to_point_network = ipaddress.ip_network("100.65.0.0/16")

        self._p2p_iter = iter(
            self.point_to_point_network.subnets(new_prefix=31)
            )

    @property
    def now(self):
        return self.clock.time()

    # Return version of topology which can be used to be loaded later
    def get_topology(self,layer2=True):
        topo = {
            'clusters': [],
            'links': []
        }

        for clustername in self.clusters:
            cluster = self.clusters[clustername]
            clusterinfo = {'name': clustername, 'systems': []}
            topo['clusters'].append(clusterinfo)

            for routername in cluster:
                router = cluster[routername]
                routerinfo = {'name': router.hostname, 'interfaces': []}
                clusterinfo['systems'].append(routerinfo)

                # connections are on physical, addressing is on logical
                # but we'll combine them here.. ?
                # May need to reconsider when loading
                seen = {}
                for ifacename in router.interfaces:
                    iface = router.interfaces[ifacename]
                    physiface = None
                    if iface.is_physical():
                        physiface = iface
                        iface = physiface.logical()
                    else:
                        physiface = iface.parent


                    addr = ""
                    if iface is not None:
                        if iface.name in seen:
                            continue
                        addr = iface.address()
                        if addr is None:
                            addr = ""
                        seen[iface.name] = True
               
                    
                    # Treat it as if the address is on the logical interface for now
                    if physiface.link is not None and addr != "":
                        ifaceinfo = {'name': iface.name, 'address': str(addr)}
                        routerinfo['interfaces'].append(ifaceinfo)

                    if physiface.name in seen:
                        continue

                    if layer2 and (physiface.link is not None):
                        ifaceinfo = {'name': physiface.name, 'address': str(physiface.hw_address)}
                        routerinfo['interfaces'].append(ifaceinfo)
                    
                    # So this is probably confusing here, but note that we are outputting
                    # the link as if it's on the logical
                    if physiface.link is None or physiface.link.endpoint1 != physiface:
                        continue
                    if (physiface.link is not None and
                       physiface.link.endpoint1 == physiface):
                        link = physiface.link
                        linkinfo = { 
                            'endpoint1': {'system': routername, 'iface': physiface.name},
                            'endpoint2': {'system': link.endpoint2.parent.hostname, 'iface': link.endpoint2.name},
                        }
                        topo['links'].append(linkinfo)
                        seen[physiface.name] = True

        return topo

    def add_server(self, name: str,
                    extra_interfaces=None, cluster_name: str = 'default',
                    interface_addr: str = None) -> Server:

        if cluster_name not in self.clusters:
            self.clusters[cluster_name] = {}

        switch = Server(name)

        if interface_addr is not None:
            switch.add_ip_address(switch.main_interface.name, interface_addr)

        # For now, you can only set the first addrss
        if extra_interfaces is not None:
            for ifacename in extra_interfaces:
                switch.add_physical_interface(ifacename)


        self.clusters[cluster_name][name] = switch

        self.logger.info(f"Added Server {name}")
        switch.event_manager.listen('*', self.collector.observer(name))
    #    self._routers.append(switch)



        return switch

    def add_switch(self, name: str,
                    interfaces=None, cluster_name: str = 'default') -> Switch:

        if cluster_name not in self.clusters:
            self.clusters[cluster_name] = {}

        switch = Switch(name)

        if interfaces is not None:
            for ifacename in interfaces:
                switch.add_physical_interface(ifacename)

        self.clusters[cluster_name][name] = switch

        self.logger.info(f"Added switch {name}")
        switch.event_manager.listen('*', self.collector.observer(name))
        self._routers.append(switch)

        return switch

    def add_router(self, name: str,
                   interfaces=None, cluster_name: str = 'default') -> Router:

        if cluster_name not in self.clusters:
            self.clusters[cluster_name] = {}
        loopback = next(self._loopback_iter)
        router = Router(name, loopback_address=loopback)

        # implied interface name
        # we could wait until IS-IS is enabled, but alas
        # TODO: should we just have this happen in the router? 
        router.interface('lo.0').addresses['iso'] = Topology.build_iso_address(
            self.area_id, loopback)

        if interfaces is not None:
            for ifacename in interfaces:
                router.add_physical_interface(ifacename)

        self.clusters[cluster_name][name] = router

        self.logger.info(f"Added router {name}")
        router.event_manager.listen('*', self.collector.observer(name))
        self._routers.append(router)
        return router

    def routers(self):
        return self._routers

    def link_router_pair(self, r1, r2, latency_ms=10, te_metric=10):
        """
        Link this pair of routers by finding the first open
        interface on each one. If no point-to-point address
        is assigned it will do so at this time
        """

        p2p = next(self._p2p_iter)
        hosts = p2p.hosts()

        host1 = next(hosts)
        host2 = next(hosts)

        r1int = None
        r2int = None
        for ifacename in r1.phy_interfaces:
            iface = r1.interfaces[ifacename]
            if iface.is_physical() and iface.link is None and not iface.is_loopback:
                r1int = iface
                break

        for ifacename in r2.phy_interfaces:
            iface = r2.interfaces[ifacename]
            if iface.is_physical() and iface.link is None and not iface.is_loopback:
                r2int = iface
                break

        r1new = r1.add_logical_interface(r1int, r1int.name + ".0", addresses={'ip': str(host1) + "/31"})
        r2new = r2.add_logical_interface(r2int, r2int.name + ".0", addresses={'ip': str(host2) + "/31"})
        r1new.te_metric = te_metric
        r2new.te_metric = te_metric

        self.logger.info(f"Linked {r1.hostname}/{r1new.name} to {r2.hostname}/{r2new.name}")

        return r1int.connect(r2int, latency_ms=latency_ms)

    # Go through each router we know about and enable IS-IS on each
    # of its current interfaces
    def isis_enable_all(self, cluster_name='default'):
        routers = self.clusters[cluster_name]
        for routername in routers:
            router = routers[routername]

            for ifacename in router.interfaces:
                iface = router.interfaces[ifacename]

                if iface.is_physical():
                    continue
        
                # Not part of same cluster, assume we don't want it enabled
                if iface.parent.link is not None and iface.parent.link.endpoint1.parent.hostname not in self.clusters[cluster_name]:
                    continue
                if iface.parent.link is not None and iface.parent.link.endpoint2.parent.hostname not in self.clusters[cluster_name]:
                    continue

                if not iface.is_physical():
                    self.logger.info(f"Requested IS-IS enable on {router.hostname}/{iface.name}")
                    router.enable_isis(iface, passive=iface.parent.is_loopback, metric=iface.te_metric)

    def isis_start_all(self, cluster_name='default'):
        routers = self.clusters[cluster_name]
        for routername in routers:
            router = routers[routername]
            self.logger.info(f"Starting IS-IS on {routername}")
            router.start_isis()

    def rsvp_start_all(self, cluster_name='default'):
        routers = self.clusters[cluster_name]
        for routername in routers:
            router = routers[routername]
            self.logger.info(f"Starting RSVP on {routername}")
            router.start_rsvp()


    @staticmethod
    def build_iso_address(area_id: str, ipaddr: ipaddress.IPv4Address) -> str:

        def to_segment(old, incoming):
            return old + str(incoming).rjust(3, '0')

        segments = reduce(to_segment, ipaddr.packed, "")

        i = 0
        sys_id = ""
        for c in segments:
            if i > 0 and i % 4 == 0:
                sys_id += "."
            sys_id += c
            i += 1

        addr = f"{area_id}.{sys_id}.0001.00"
        return addr

    # !!! TODO: These methods don't really belong here
    # But would be part of some larger simulation or
    # provided as "magic" methods
    # But the useful thing would be to have an iteratble
    # returned of the events that occurred during this run
    # which can then be passed into any number of things that
    # might care
    # Returns list of (aggregator, event)
    def run_another(self, relative_ticks):
        return self.run_until(self.clock.clockfn() + relative_ticks)

    # Returns list of (aggregator, event)
    def run_until(self, tick):
        """
        Run simulation of this topology until tick has been reached
        """
        # for now we assume each time we run more we want to dump
        # the collected events
        self.collector.clear()
        try:
            delay = GlobalQueueManager.run()
            while self.clock.clockfn() < tick:
                if delay is None:
                    delay = 1
                self.clock.delayfn(delay)
                delay = GlobalQueueManager.run()
        except Exception as e:
            self.logger.exception("Caught exception during run")

        return copy.copy(self.collector.events())

    def schedule(self, delay, func):
        GlobalQueueManager.enqueue(delay, func)
