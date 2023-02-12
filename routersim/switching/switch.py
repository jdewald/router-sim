import logging
from ..netdevice import NetworkDevice
from ..observers import EventManager, LoggingObserver, EventType
from .bridging import SwitchingEngine


# TODO: We want to be able to accept packets on both "management"
# as well as "transit" interfaces
class PacketListener:
    def __init__(self, switch):
        self.switch = switch

    def observe(self, evt):
        # TODO: This stuff will move into type-specific processors
        if not evt.event_type == EventType.PACKET_RECV:
            return

        frame = evt.object
        # assuming we're not there, we now need to determine if the packet
        # should be forwarded on or is actually meant for us
        # (control plane traffic)
        # Still need to work out exactly how we distinguish these

        self.switch._bridging.process_frame(frame, source_interface=evt.source)

# Layer 2 Learning bridge
# TODO: Starting this, but likely a switch and a router will
# extend from a base class
class Switch(NetworkDevice):

    def __init__(self, hostname, interface_count=12):
        super().__init__(hostname)
        self.logger = logging.getLogger(hostname)
        self.phy_interfaces = dict()
        self.interfaces = dict()
#        self.loopback_address = loopback_address
        self.process = dict()
#        self.routing = RoutingTables(evt_manager=self.event_manager, parent_logger=self.logger)
#        self._forwarding = ForwardingTable(self.event_manager, self.logger)
#        self.pfe = PacketForwardingEngine(self._forwarding, self)
        self.pingid = 0

        self._bridging = SwitchingEngine(self,  self.interfaces, None) 

        self.event_manager.listen(
            '*', LoggingObserver(self.hostname, self.logger).observe) 
        self.event_manager.listen(
            EventType.PACKET_RECV, PacketListener(self).observe)

        # for now, assuming Ethernet interfaces
        iface_prefix = "et"
        for i in range(interface_count):
            intf = self.add_physical_interface(f"{iface_prefix}{i+1}")
            intf.add_logical_interface(f"{intf.name}.1")
