from collections import UserDict
from .observers import Event, EventType

from abc import ABC, abstractmethod
"""
MPLS - RFC 3031

https://tools.ietf.org/html/rfc3031
"""


class MPLSPacket():

    def __init__(self, encapsulated=None, ttl=64):
        # What are we actually carrying
        self.encapsulated = encapsulated
        self.label_stack = []
        # TODO: We can also pull this from the encapsulated packet
        # 3.23. Time-to-Live (TTL)
        self.ttl = ttl

    def __str__(self):
        return f"MPLS (labels={','.join(self.label_stack)}"

    def seq_note(self):
        return f"Encapsulated: {self.encapsulated}"

class LabelStackOperation(ABC):

    def __init__(self):
        self.new_label = None
    @abstractmethod
    def apply(self, packet: MPLSPacket):
        pass

class NoOpAction(LabelStackOperation):

    def apply(self, pdu, router, event_manager=None):
        return pdu

    
class CombinedAction(LabelStackOperation):
    def __init__(self, actions):
        self.new_label = None
        self.actions = actions

    def apply(self, packet: MPLSPacket, router, event_manager=None):
        for action in self.actions:
            packet = action.apply(packet, router, event_manager)
        return packet

    def __str__(self):
        return ','.join([str(a) for a in self.actions])


class ReplaceStackOperation(LabelStackOperation):
    def __init__(self, new_label: int):
        self.new_label = new_label

    def apply(self, packet: MPLSPacket, router, event_manager=None):
        old_label = packet.label_stack.pop()
        packet.label_stack.append(str(self.new_label))

        if event_manager is not None:
            event_manager.observe(Event(EventType.MPLS,
                                  router,
                                  f"Swapped {old_label} for {self.new_label}",
                                        object=self.new_label,
                                        sub_type="LabelSwap")
                                  )
        return packet

    def __str__(self):
        return f"Swap in {self.new_label}"


class PushStackOperation(LabelStackOperation):
    def __init__(self, new_label: int):
        self.new_label = new_label

    def apply(self, pdu, router, event_manager=None):
        packet = pdu
        if not isinstance(pdu, MPLSPacket):
            packet = MPLSPacket(pdu, ttl=pdu.ttl)

        packet.label_stack.append(str(self.new_label))
        if event_manager is not None:
            event_manager.observe(Event(EventType.MPLS,
                                  router,
                                  f"Pushed {self.new_label}",
                                        object=self.new_label,
                                        sub_type="LabelPush")
                                  )
        return packet

    def __str__(self):
        return f"Push {self.new_label}"


class PopStackOperation(LabelStackOperation):
    def apply(self, packet: MPLSPacket, router, event_manager=None):
        old_label = packet.label_stack.pop()
        if event_manager is not None:
            event_manager.observe(Event(EventType.MPLS,
                                  router,
                                  f"Popped {old_label} from MPLS label stack",
                                        object=old_label,
                                        sub_type="LabelPop")
                                  )
        if len(packet.label_stack) == 0:
            return packet.encapsulated
        else:
            return packet

    def __str__(self):
        return "Pop"

# 3.10. The Next Hop Label Forwarding Entry (NHLFE)


class NextHopLabelForwardingEntry():
    def __init__(self, next_hop, label_action: LabelStackOperation):
        self.next_hop = next_hop
        self.action = label_action


# TODO: This may become referenced by the routing table
class IncomingLabelMap(UserDict):
    """
    The Incoming Label Map is just responsible for taking a label
    and deriving label actions + next hop that will be applied
    to an mpls packet with that label
    """

    def __init__(self):
        super().__init__([])

    def lookup(self, label: int) -> list[NextHopLabelForwardingEntry]:
        return self.__get(label)


