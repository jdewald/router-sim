import sched
import random
from functools import partial

from enum import Enum


class GlobalQueueManager:

    @staticmethod
    def setup(clockfn, delayfn):
        GlobalQueueManager.clockfn = clockfn
        GlobalQueueManager.s = sched.scheduler(clockfn, delayfn)

    @staticmethod
    def enqueue(delay, action, arguments=(), kwargs={}):
        # we do random priorit to "shuffle" the events that
        # happen at the same time
        GlobalQueueManager.s.enter(
            delay, random.randint(0, 100), action, arguments)

    @staticmethod
    def run():
        return GlobalQueueManager.s.run(blocking=False)

    @staticmethod
    def now():
        return GlobalQueueManager.clockfn()


class EventType(Enum):
    INTERFACE_STATE = 1
    PACKET_SEND = 2
    PACKET_RECV = 3
    LINK_STATE = 4
    ROUTE_CHANGE = 5
    FORWARDING = 6
    MPLS = 8
    ICMP = 9

    ISIS = 10
    RSVP = 11

    def __str__(self):
        return str(self.name)


class Event:
    # TODO: standard library?
    def __init__(self, event_type, source, msg,
                 object=None, sub_type="", target=None):
        self.event_type = event_type
        self.source = source
        self.msg = msg
        self.object = object
        self.sub_type = sub_type
        self.target = target
        self.when = 0


class LoggingObserver:

    def __init__(self, prefix, logger):
        self.prefix = prefix
        self.logger = logger

    def observe(self, evt):
        self.logger.info(
            f"{evt.when} {self.prefix}:{evt.event_type} - from {evt.source}: {evt.msg}")


class EventCollector:
    def __init__(self):
        self._events = []

    def observer(self, aggregator_name):
        return partial(self._observe, aggregator_name)

    def _observe(self, aggregator_name, evt):
        self._events.append((aggregator_name, evt))

    def clear(self):
        self._events.clear()

    def events(self):
        return self._events


class EventManager:

    def __init__(self, name):
        self.name = name
        self.listeners = {}

    def observe(self, evt):
        evt.when = GlobalQueueManager.now()
        if '*' in self.listeners:
            for listener in self.listeners['*']:
                listener(evt)

        if evt.event_type in self.listeners:
            for listener in self.listeners[evt.event_type]:
                listener(evt)

    def listen(self, event_type, observer):
        if event_type not in self.listeners:
            self.listeners[event_type] = []

        self.listeners[event_type].append(observer)

    def stop_listening(self, event_type, observer):
        if event_type not in self.listeners:
            return

        self.listeners[event_type].clear()
#        self.listeners[event_type].remove(observer)
