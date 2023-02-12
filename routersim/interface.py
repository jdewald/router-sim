from enum import Enum
import ipaddress
import binascii
from .observers import Event, EventType, GlobalQueueManager
from .messaging import Frame, FrameType, MACAddress
from copy import deepcopy


class ConnectionState(Enum):
    UP = 1
    DOWN = 2

    def __str__(self):
        return str(self.name)


class PhysicalInterface:
    def __init__(self, name=None, address=None, owner=None, is_loopback=False):
        # This would end up as a MAC address
        self.name = name
        self.address = address
        self.interfaces = dict()
        self.admin_state = ConnectionState.UP
        self.state = ConnectionState.UP
        self.link = None
        self.event_manager = None
        self.parent = owner
        self.is_loopback = is_loopback

    @property
    def hw_address(self):
        return self.address

    def __str__(self):
        return f"PHY/{self.name} ({self.address}) "

    def is_up(self):
        return (
            self.link is not None and
            self.state == ConnectionState.UP and
            self.admin_state == ConnectionState.UP
        )

    def is_physical(self):
        return True

    def add_logical_interface(self, name, addresses=None):
        self.interfaces[name] = LogicalInterface(
            name, self, addresses=addresses)
        self.interfaces[name].event_manager = self.event_manager
        return self.interfaces[name]

    # Should only be called to indicate that both sides are up
    def up(self):
        self.state = ConnectionState.UP
        self.event_manager.observe(
            Event(EventType.LINK_STATE, self, f"{self} is now UP"))

        for intname in self.interfaces:
            self.interfaces[intname].up()

    def down(self):
        self.state = ConnectionState.DOWN
        self.event_manager.observe(
            Event(EventType.LINK_STATE, self, f"{self} is now DOWN"))

        for intname in self.interfaces:
            self.interfaces[intname].down()

    def connect(self, other, latency_ms=10):
        self.link = PhysicalLink(self, other, latency_ms=latency_ms)
        self.link.up()

        return self.link

    def _send(self, frame_type, pdu, logical=None):
        # no "arp" yet
        frame = Frame(self.hw_address, "Unknown", frame_type, pdu)
        self.send_frame(frame, logical=logical)

    def send_frame(self, frame, logical=None):
        if not self.is_up():
            return
        if self.link is not None:
            self.link.send(frame, sender=self, logical=logical)
        else:
            self.parent.logger.error(f"{self.name} being used to send a frame, but don't have a link!")
            print(f"{self.parent.hostname}/{self.name} being used to send a frame, but don't have a link!")

    def receive(self, frame):
        if self.is_up():
            self.event_manager.observe(
                Event(
                    EventType.PACKET_RECV,
                    self,
                    f"Received {frame.pdu}",
                    object=frame)
            )


class LogicalInterface:
    def __init__(self, name, physical_interface, addresses=None):
        self.name = name
        self.phy = physical_interface
        self.admin_state = ConnectionState.UP
        self.state = ConnectionState.DOWN
        self.addresses = {}
        self.parent = physical_interface
        self.te_metric = 10

        if addresses is not None:
            if 'ip' in addresses:
                self.addresses['ipv4'] = ipaddress.ip_interface(
                    addresses['ip'])

            if 'iso' in addresses:
                self.addresses['iso'] = addresses['iso']

    @property
    def hw_address(self):
        return self.parent.hw_address

    def address(self, type='ipv4'):
        return self.addresses.get(type)

    def __str__(self):
        return f"LOG/{self.name}"

    def is_physical(self):
        return False

    def send_frame(self, frame: Frame):
        self.parent.send_frame(frame, logical=self)

    def send(self,
             dest_address: MACAddress,
             frame_type: FrameType,
             pdu):

        frame = Frame(self.hw_address, dest_address, frame_type, pdu)
        self.send_frame(frame)

    def _send_ip(self, pdu):
        self.phy.send(FrameType.IPV4, pdu, logical=self)

    def send_clns(self, pdu):
        frame = Frame('000', '0000', FrameType.CLNS, pdu)
        self.phy.send_frame(frame, logical=self)

    def is_up(self):
        return (
            self.state == ConnectionState.UP and
            self.admin_state == ConnectionState.UP
        )

    def up(self):
        self.state = ConnectionState.UP

        if self.is_up():
            self.event_manager.observe(
                Event(EventType.LINK_STATE, self, f"{self} is now UP"))

    def down(self):
        self.state = ConnectionState.DOWN
        self.event_manager.observe(
            Event(EventType.LINK_STATE, self, f"{self} is now DOWN"))

    def receive(self, frame):
        pass
#        self.event_manager.observe(
#            Event(
#                EventType.PACKET_RECV,
#                self,
#                f"Received {frame.pdu}",
#                object=frame)
#        )


class PhysicalLink:

    # TODO: add jitter parameter
    def __init__(self, endpoint1, endpoint2, latency_ms=10):
        self.endpoint1 = endpoint1
        self.endpoint2 = endpoint2
        self.endpoint2.link = self
        self.state = ConnectionState.DOWN
        self.latency_ms = latency_ms

    def up(self):
        self.state = ConnectionState.UP
        GlobalQueueManager.enqueue(
            self.latency_ms / 2,
            self.endpoint1.up
        )
        GlobalQueueManager.enqueue(
            self.latency_ms / 2,
            self.endpoint2.up
        )

    def down(self):
        self.state = ConnectionState.DOWN

        GlobalQueueManager.enqueue(
            self.latency_ms / 2,
            self.endpoint1.down
        )
        GlobalQueueManager.enqueue(
            self.latency_ms / 2,
            self.endpoint2.down
        )

    def send(self, frame, sender, logical=None):

        if self.state == ConnectionState.DOWN:
            return

        # enqueue in the message bus for "next tick"
        receiver = self.endpoint1
        if sender == self.endpoint1:
            receiver = self.endpoint2

        if sender.is_up():
            event = Event(
                EventType.PACKET_SEND,
                sender, f"Sending {frame.type}", object=frame, target=receiver)

            # This is so we don't lose event between observations
            GlobalQueueManager.enqueue(
                0,
                sender.parent.event_manager.observe,
                arguments=(event, )
            )
            #sender.parent.event_manager.observe()

            # receiver.receive(frame)
            GlobalQueueManager.enqueue(self.latency_ms, receiver.receive, arguments=(deepcopy(frame),))
