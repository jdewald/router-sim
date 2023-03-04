from ..observers import GlobalQueueManager, Event, EventType
from ..interface import LogicalInterface, PhysicalInterface
from ..messaging import BROADCAST_MAC, MACAddress
from scapy.layers.l2 import Ether

from binascii import hexlify


DEFAULT_MAC_AGING_TIME_SECONDS = 300


class BridgeEntry():
    def __init__(self, mac: MACAddress, interface: LogicalInterface, used: int):
        self.mac = mac
        self.vlan_id = 1
        self.interface = interface
        self.last_seen = used

    def __str__(self):
        return f"{str(self.mac)} -> {self.interface.name}"


class BridgingTable:
    def __init__(self, event_manager, parent_logger, config=None):
        self.table = None
        self.event_manager = event_manager
        self.logger = parent_logger.getChild('bridging')

        if config is None:
            self.config = {}
        else:
            self.config = config

        if self.table is None:
            self.table = dict()

        self._apply_defaults()

    def _apply_defaults(self):
        if 'mac-aging-time' not in self.config:
            self.config['mac-aging-time'] = DEFAULT_MAC_AGING_TIME_SECONDS

    def __str__(self):
        return "Bridging Table"

    def is_expired(self, entry):
        return (entry.last_seen <
                (GlobalQueueManager.now() - (1000 * self.config['mac-aging-time']))
                )

    def set_table(self, table):
        self.table = table
        self.logger.debug("Installed new forwarding table")

    def learn(self, mac: MACAddress, interface: LogicalInterface):
        entry = self.table.get(mac)
        if entry is None or entry.interface != interface:
            self.table[mac] = BridgeEntry(mac, interface, GlobalQueueManager.now())
            self.logger.debug(f"Learned new mac entry: {self.table[mac]}")
        else:
            entry.last_seen = GlobalQueueManager.now()

    def lookup_mac(self, mac: MACAddress) -> LogicalInterface:
        entry = self.table.get(mac)

        if entry is None:
            self.logger.info(f"No entry for {mac}")
            return None

        if self.is_expired(entry):
            del self.table[mac]
            return None

        return entry.interface

    def print_bridging_table(self, target_mac=None, target_interface=None):

        print("MAC\tInterface")
        for mac in self.table:
            entry = self.table[mac]
            if not self.is_expired(entry) and (target_mac is None or mac == target_mac):
                print(f"{mac}\t{entry.interface}")


class SwitchingEngine():
    def __init__(self,
                 switch,
                 interfaces: list, bridging_table: BridgingTable = None):
        self.switch = switch
        self.bridging = bridging_table
        self.interfaces = interfaces
        self.logger = switch.logger.getChild("bridingengine")

        if self.bridging is None:
            self.bridging = BridgingTable(switch.event_manager, self.logger)

    # Intended for internal communications

    # A frame always comes over a PhysicalInterface, and then may get
    # interpreted as a LogicalInterface depending on data in the frame
    def process_frame(self, frame: Ether, source_interface: PhysicalInterface):
        self.logger.info("processing frame")
        # TODO: This is where we would look at the encapsulation to work
        # out where this is really intended

        out_interface = None
        if frame.dest != BROADCAST_MAC:
            out_interface = self.bridging.lookup_mac(frame.dest)

        # Right now still assuming single physical interface
        for logical in source_interface.interfaces.values():
            self.bridging.learn(frame.src, logical)
            break

        # TODO: actually when an interface comes up, we just need to add
        # it to the table with an "Interface" of the switch itself
        if out_interface is None:
            # This can mean either that we haven't learned it, or its one of our own
            found = False
            for logical in source_interface.interfaces.values():
                if frame.dest == logical.hw_address:
                    self.switch.process_frame(frame, logical)
                    found = True

            if not found:
                self.broadcast_frame(frame,
                                        source_interface=source_interface
                                        )

        else:
            self.logger.info(f"Successfully found entry for {frame.dest}")
            out_interface.send_frame(frame)

    def broadcast_frame(self, frame: Ether, source_interface: PhysicalInterface):
        self.logger.info(f"Broadcasting {frame}")
        for interface in self.interfaces:
            if interface != source_interface.name:
                self.interfaces[interface].send_frame(frame)

