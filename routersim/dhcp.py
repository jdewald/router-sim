from scapy.layers.dhcp import DHCP,BOOTP
from scapy.layers.inet import IP,UDP
from ipaddress import ip_address,ip_network,IPv4Address,IPv4Network
from random import randint
from .messaging import BROADCAST_MAC, FrameType
from .interface import LogicalInterface
from .observers import GlobalQueueManager, EventType, Event


# https://en.wikipedia.org/wiki/Dynamic_Host_Configuration_Protocol

# https://en.wikipedia.org/wiki/Broadcast_domain
# Send to all devices on this subnet
# https://www.rfc-editor.org/rfc/rfc919
BROADCAST_IP = ip_address("255.255.255.255")

BOOTP_CLIENT_PORT = 68
BOOTP_SERVER_PORT = 67

DHCP_DISCOVER = 'discover'
DHCP_OFFER = "offer"
DHCP_REQUEST = "request"
DHCP_ACK = "ack"

DEFAULT_SUBNET = ip_network("192.168.1.0/24")
DEFAULT_GW = ip_address("192.168.1.1")
DEFAULT_RANGE = (
    ip_address("192.168.1.100"), 
    ip_address("192.168.1.200")
)

DHCP_OPTION_REQUESTED_ADDR = 50
DHCP_OPTION_LEASE_TIME = 51
DHCP_OPTION_ROUTER = 3
DHCP_OPTION_SUBNET_MASK = 1
DHCP_OPTION_DNS_SERVERS = 6
DHCP_OPTION_DHCP_SERVER = 54

DEFAULT_LEASE_TIME_SECONDS = 86400

class DHCPEvent(Event):
    def __init__(self, source, msg, object, sub_type):
        super().__init__(EventType.DHCP,
        source,
        msg,
        object,
        sub_type)

class DHCPClient():

    def __init__(self, host):
        self.hostname = host.hostname
        self.host = host
        self.logger = host.logger.getChild("DHCPClient")

    # Issue a DHCPDiscover request
    def discover(self, iface):

        self.host.listen_udp(BOOTP_CLIENT_PORT, self.process_msg)
        # Scapy will handle mapping these
        # to the relevant binary values
        options = [
            ('hostname', self.hostname),
            ('message-type', DHCP_DISCOVER),
            ('param_req_list', [
                DHCP_OPTION_SUBNET_MASK,   # subnet mask
                DHCP_OPTION_ROUTER,   # router
                DHCP_OPTION_DNS_SERVERS,   # dns servers
                31,  # router discovery
                33,  # static routes
            ])
        ]

        # Technically we only need to set 'B' flag
        # if we need the dhcpserver to send to
        # broadcast_ip until we have fully accepted
        # the IP address

        req = IP(
            src="0.0.0.0", dst=BROADCAST_IP
        ) / UDP(
            sport=BOOTP_CLIENT_PORT, dport=BOOTP_SERVER_PORT
        ) / BOOTP(
            chaddr=iface.hw_address, 
            xid=randint(0,10000), 
            flags="B"
        ) / DHCP(
            options=options
        )

        iface.logical().send(BROADCAST_MAC, FrameType.IPV4, req)

    def _do_request(self, offered_address, iface, bootp: BOOTP):

        options = [
            ('hostname', self.hostname),
            ('message-type', DHCP_REQUEST),
            (DHCP_OPTION_DHCP_SERVER, bootp.siaddr),
            (DHCP_OPTION_REQUESTED_ADDR, offered_address)
        ]

        # Technically we only need to set 'B' flag
        # if we need the dhcpserver to send to
        # broadcast_ip until we have fully accepted
        # the IP address

        req = IP(
            src="0.0.0.0", dst=BROADCAST_IP
        ) / UDP(
            sport=BOOTP_CLIENT_PORT, dport=BOOTP_SERVER_PORT
        ) / BOOTP(
            chaddr=iface.hw_address, 
            xid=randint(0,10000), 
            flags="B",
            siaddr=bootp.siaddr     # who's offer are we accepting
        ) / DHCP(
            options=options
        )

        iface.logical().send(BROADCAST_MAC, FrameType.IPV4, req)

    # DHCP server has OFFERED us an address, let's actually
    # REQUEST it
    def request(self, iface, bootp: BOOTP):

        # TOD: Technically we should ARP for this

        offered_address = bootp.yiaddr

        # Make sure nobody already has this address
        self.host.arp.request(offered_address, iface.logical())

        def check_and_request():

            self.logger.info(f"Verifying nobody has {offered_address}")
            existing = self.host.arp.cache.get(offered_address)
            if existing is None:
                self._do_request(offered_address, iface, bootp)
            else:
                self.logger.warn(f"Cannot accept {offered_address}, its already taken!")

        # Wait 100ms
        GlobalQueueManager.enqueue(100, check_and_request)

    # Fully apply the IP config we got from the DHCP server
    def apply_config(self, iface: LogicalInterface, ack: BOOTP):

        assigned_addr = ack.yiaddr

        # NOTE: In real DHCP this is subnet mask, which
        # ... we might want to do so it looks correct in a packet capture
        network = [v for (k,v) in ack[DHCP].options if k == DHCP_OPTION_SUBNET_MASK][0]
        prefixlen = ip_network(network).prefixlen

        # Generate an interface address
        # if we pass the actual subnet mask then we
        # can literally do addr/mask in python
        # so.... that could be better. We can also
        # do an IPv4Network
        self.host.add_ip_address(iface.parent.name, f"{assigned_addr}/{prefixlen}")

        # now add the default gateway
        gw = [v for (k, v) in ack[DHCP].options if k == DHCP_OPTION_ROUTER][0]
        self.host.static_route("0.0.0.0/0", str(gw), iface.name)

    def process_msg(self, iface: LogicalInterface, packet: IP):

        bootp = packet[BOOTP]
        if bootp.chaddr != iface.hw_address:
            return True
        clientmsg = packet[DHCP]
        for (type, val) in clientmsg.options:
            if type == 'message-type':
                if val == DHCP_OFFER:
                    self.request(iface, packet['BOOTP'])
                    return True
                elif val == DHCP_ACK:
                    self.apply_config(iface, packet['BOOTP'])
                    return True



class DHCPserver():

    def __init__(self, host, 
        subnet=DEFAULT_SUBNET, 
        gw=DEFAULT_GW,
        lease_range=DEFAULT_RANGE):
        self.host = host
        self.logger = self.host.logger.getChild("DHCPServer")
        self.event_manager = host.event_manager

        if isinstance(subnet, str):
            subnet = ip_network(subnet)
        if isinstance(gw, str):
            gw = ip_address(gw)

        self.default_subnet = subnet
        self.default_range = lease_range

        # A single DHCP Server can handle any number of networks
        # assuming it lives on multiple network interfaces or
        # has a router assisting it
        self.subnets = {}
        self.subnets[self.host.main_interface.name] = {
            'gw': gw,
            'range': lease_range,
            'network': subnet,
        }

        # maps mac -> ip
        self.leases = {}
        self.leased = {}
        self.leases[subnet] = {}

        self.holds = {}

    def start(self):

        self.host.listen_udp(BOOTP_SERVER_PORT, self.process_msg)


    def process_msg(self, iface: LogicalInterface, packet: IP):

        clientmsg = packet['DHCP']
        for (type, val) in clientmsg.options:
            if type == 'message-type':
                if val == DHCP_DISCOVER:
                    self.offer(iface, packet['BOOTP'])
                    return True
                elif val == DHCP_REQUEST:
                    self.bind_and_ack(iface, packet['BOOTP'])
                    return True

        return False
    
    def _find_addres_for_offer(self, subnet: dict, client_addr):
        self.logger.info(f"Looking for potential offer for {subnet['network']} and {client_addr}")
        existing = self.leases[subnet['network']].get(client_addr)
        if existing is not None:
            return existing

        lease_range = subnet['range']

        offer_addr = None
        if existing is None:
            # very very bad if using a /16
            # but I'm being lazy here
            for addr in subnet['network'].hosts():
                if not (addr >= lease_range[0] and addr <= lease_range[1]):
                    continue
                if addr in self.holds:
                    continue
                if addr in self.leased:
                    continue

                offer_addr = addr
                break

        self.logger.info(f"Found address {offer_addr} for offer to {client_addr}")

        return offer_addr

    def _lease(self, network: IPv4Network, client_mac, requested_addr: IPv4Address):
        leases = self.leases[network]
        leases[client_mac] = requested_addr
        self.leased[requested_addr] = True

        self.event_manager.observe(
            DHCPEvent(
                self,
                "Leased IP",
                (client_mac, requested_addr),
                "DHCP_LEASE"
            )
        )
 
    def offer(self, iface, bootp: BOOTP):

        myaddr = iface.address()
        subnet = self.subnets.get(iface.name)
        if subnet is None:
            subnet = self.subnets.get(iface.parent.name)
        client_addr = bootp.chaddr

        offer_addr = self._find_addres_for_offer(subnet, client_addr)

        if offer_addr is None:
            self.logger.warn(f"Unable to find address for offer!")
            return False

        # TODO: When using a relay agent, we would
        # pull from bootp.giaddr to determine the subnet
            
        params = [v for (k,v) in bootp[DHCP].options if k == 'param_req_list']
        self.holds[offer_addr] = client_addr
        self.holds[client_addr] = {
            'offer': offer_addr,
            'param_req_list': params[0],
            'client_addr': client_addr,
            'subnet': subnet,
            'xid': bootp.xid,
        }

        self.event_manager.observe(
            DHCPEvent(
                self,
                "Reserved IP Address",
                (client_addr, offer_addr),
                "DHCP_RESERVE"
            )
        )


        # Scapy will handle mapping these
        # to the relevant binary values
        options = [
            ('hostname', self.host.hostname),
            ('message-type', DHCP_OFFER),
        ]

        dhcpdata = bootp[DHCP]
        
        for (key, val) in dhcpdata.options:
            if key == 'param_req_list':
                for opt in val:
                    if opt == DHCP_OPTION_SUBNET_MASK: # subnet mask
                        options.append(
                            (1, subnet['network'])
                        )
                    elif opt == DHCP_OPTION_ROUTER: # router
                        options.append(
                            (3, subnet['gw'])
                        )
   

        req = IP(
            src=myaddr, dst=BROADCAST_IP
        ) / UDP(
            sport=BOOTP_SERVER_PORT, dport=BOOTP_CLIENT_PORT
        ) / BOOTP(
            chaddr=bootp.chaddr, 
            xid=bootp.xid,
            yiaddr=offer_addr,
            siaddr=myaddr,
        ) / DHCP(
            options=options
            
        )

        iface.logical().send(BROADCAST_MAC, FrameType.IPV4, req)
        return True

    def ack(self, iface: LogicalInterface, hold_info: dict(), myaddr):
        subnet = hold_info['subnet']
        requested_addr = hold_info['offer']
        client_mac = hold_info['client_addr']
        xid = hold_info['xid']
        
        options = [
            ('hostname', self.host.hostname),
            ('message-type', DHCP_ACK),
        ]

        requested_params = hold_info['param_req_list']
        

        for opt in requested_params:
            if opt == DHCP_OPTION_SUBNET_MASK: # subnet mask
                # technically is in form 255...
                # but I prefer to just do the network for clarity
                options.append(
                    (1, subnet['network'])
                )
            elif opt == DHCP_OPTION_ROUTER: # router
                options.append(
                    (3, subnet['gw'])
                )
   

        req = IP(
            src=myaddr, dst=BROADCAST_IP
        ) / UDP(
            sport=BOOTP_SERVER_PORT, dport=BOOTP_CLIENT_PORT
        ) / BOOTP(
            chaddr=client_mac, 
            xid=xid,
            yiaddr=requested_addr,
            siaddr=myaddr,
        ) / DHCP(
            options=options
            
        )

        # in case of relay, 
        iface.logical().send(BROADCAST_MAC, FrameType.IPV4, req)
        return True       
    # Assign the address lease and send out the
    # actual host parameters
    def bind_and_ack(self, iface: LogicalInterface, bootp: BOOTP):

        myaddr = iface.address()
        
        client_mac = bootp.chaddr
        if bootp.siaddr != myaddr:
            self.logger.info(f"Request is to another DHCP server, removing reservation")


        # we clear any holds regardless
        hold_info = self.holds.get(client_mac)

        if hold_info is not None:
            del self.holds[client_mac]
            del self.holds[hold_info['offer']]

            self.event_manager.observe(
                DHCPEvent(
                    self,
                    "Cleared IP Reservation",
                    (client_mac, hold_info['offer']),
                    "DHCP_CLEAR_RESERVE"
                )
            )


        # ok its actually for us
        dhcp_msg = bootp[DHCP]

        # illegal for this to not work
        requested_addr = [v for (k,v) in dhcp_msg.options if k == DHCP_OPTION_REQUESTED_ADDR][0]
        
        if hold_info is None:
            self.logger.warn(f"Received REQUEST for {requested_addr} but no matching hold found!")
            return  

        subnet = hold_info['subnet']

        self._lease(subnet['network'], client_mac, requested_addr)

        self.ack(iface, hold_info, myaddr)
