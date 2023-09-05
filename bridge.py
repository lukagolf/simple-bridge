#!/usr/bin/env python3

import socket
import select
import json
import argparse
import threading 
import time

# First, grab our arguments from the command line
#  bridge_id is our bridge ID ("1234" or whatever)
#  lan_ports are the local UDP ports that we use to send/receive packets on our LAN(s)
parser = argparse.ArgumentParser(description='CS 3700 bridge')
parser.add_argument('bridge_id', type=str, help="Bridge ID (e.g., 02ab)")
parser.add_argument('lan_ports', metavar='lan_port', type=int, nargs='+', help="UDP ports to connect to LANs")
args = parser.parse_args()


class BridgeInfo:
  """
  A class which acts as a container for important information about a bridge.

  Attributes
  ----------
  root_port : int
      the port of the bridge thats sends messages to the root
  root_id : int
      id of the bridge currently considered the root bridge
  cost : int
      current cost of a message going from this bridge to the root
  next_hop : int
      id of the bridge that is believed to be the next
  unconfirmed : int
      used for timing out BPDUs older than 1000ms. acts like a counter in a way
  """

  def __init__(self, bridge_id):
    """
    Parameters
    ----------
    bridge_id : int
        initial bridge id to be used for the root_id and next_hop value
    """
    self.bridge_id = bridge_id
    self.root_port = -1
    self.root_id = bridge_id
    self.cost = 0
    self.next_hop = bridge_id 
    self.unconfirmed = 0

  def get_bridge_id(self):
    """ Returns the value of the bridge id """
    return self.bridge_id

  def get_root_port(self):
    """ Returns the value of the root port """
    return self.root_port

  def set_root_port(self, port):
    """ Sets the value of the root port for this bridge """
    self.root_port = port

  def get_root_id(self):
    """ Returns the ID of the root """
    return self.root_id

  def set_root_id(self, id):
    """ Sets the ID of the root for this bridge """
    self.root_id = id
  
  def get_cost(self):
    """ Returns the value of the current cost to root """
    return self.cost

  def set_cost(self, new_cost):
    """ Sets the cost to root for this bridge"""
    self.cost = new_cost

  def get_next_hop(self):
    """ Returns the ID of the next connected bridge """
    return self.next_hop

  def set_next_hop(self, hop):
    """ Sets the ID of the bridge to be next hopped to """
    self.next_hop = hop

  def get_unconfirmed(self):
    """ Gets the value of the BPDU time out counter."""
    return self.unconfirmed

  def increase_unconfirmed(self):
    """ Increases the BPDU time out counter by 1."""  
    self.unconfirmed = self.unconfirmed + 1

  def reset_unconfirmed(self):
    """ Resets the BPDU time out counter to 0."""
    self.unconfirmed = 0
    

# Definition of a port
class Port:
  """
    Represents a UDP port belonging to a bridge.

    Attributes
    ----------
    id : int
        id of this port
    lan_port : 
        UDP port that this object will use to communicate with its LAN
    socket : socket
        socket object that lets us send and receive message
    enabled : boolean
        boolean that represents whether or not this port is enabled
    min_cost : int
        the min cost from this port
    permanently_disabled : boolean
        boolean that represents whether or not this port is permanently disabled

  """
  def __init__(self, id, lan_port, permanently_disabled = False):
    """
    Parameters
    ==========
    id : int
      The ID for this Port
    lan_port : int
      The UDP this port will use in communication with its LAN
    permanently_disabled : boolean
      Represents whether this Port is permamently disabled or not
    """
    self.id = id
    self.lan_port = lan_port
    self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.socket.bind(('localhost', 0))
    self.enabled = True
    self.min_cost = 0
    self.permanently_disabled = permanently_disabled
    self.set_enabled(not permanently_disabled)

  def get_id(self):
    """ Returns the Ports ID. """
    return self.id 

  def set_permanently_disabled(self):
    """ Sets this port as permanently disabled. """
    self.permanently_disabled = True

  def is_permanently_disabled(self):
    """ Returns whether or not this port has been permanently disabled. """
    return self.permanently_disabled

  def set_min_cost(self, cost):
    """ Sets the minimum cost from this port. """
    self.min_cost = cost

  def update_min_cost(self, cost):
    """ 
    Updates the minimum cost of this port if the given cost is less than
    the current minimum cost.
    """
    if self.min_cost > cost:
      self.min_cost = cost

  def get_min_cost(self):
    """ Returns the minimum cost from this port. """
    return self.min_cost

  def get_lan_port(self):
    """ Returns the UDP port number used by this Port. """
    return self.lan_port

  def set_enabled(self, enabled):
    """
    Sets this port as either enabled (True) or disabled (False) and prints
    corresponding message.
    """
    if enabled:
      print ("Designated port: %d" % self.id )
    else:
      print ("Disabled port: %d" % self.id)
        
    self.enabled=enabled

  def is_enabled(self):
    """ Returns whether or not this port is enabled. """
    return self.enabled and not self.permanently_disabled

  
  def send_bpdu(self, root_id, cost):
    """
    This method sends a BPDU on this port. 
    """
    if not(self.permanently_disabled):
      self.send(json.dumps({"source": args.bridge_id, 
                          "dest": "ffff", 
                          "msg_id": 0,
                          "type": "bpdu", 
                          "message": { "id": args.bridge_id, 
                                      "root": root_id, 
                                      "cost": cost, 
                                      "port": self.id }
                        }).encode('utf-8'))

  
  def send(self, data):
    """
    This method sends the provided byte array "data" to the LAN, using the 
    UDP connection.
    """
    if not(self.permanently_disabled):
      self.socket.sendto(data, ('localhost', self.lan_port))


def get_port_from_lan_port(lan_port):
  """ Returns the LAN port from the arguments at the given index. """
  return args.lan_ports.index(lan_port)


def send_bpdus(PORTS, root_id, cost):
  """ Sends a BPDU on all ports. """
  for port in PORTS:
    port.send_bpdu(root_id, cost)

def send_bpdus_thread(PORTS, ADDR_TABLE, bridgeInfo):
  """ Runs send_bpdus() with a half second timer loop. """
  while True:
    send_bpdus(PORTS, bridgeInfo.get_root_id(), bridgeInfo.get_cost())
    bridgeInfo.increase_unconfirmed()
    time.sleep(0.5)
    if bridgeInfo.get_unconfirmed() > 2:
      bridgeInfo.set_root_id(bridgeInfo.get_bridge_id())
      bridgeInfo.set_next_hop(bridgeInfo.get_bridge_id())
      bridgeInfo.set_root_port(none)
      bridgeInfo.set_cost(0)
      for i in ADDR_TABLE:
        ADDR_TABLE.remove(i)

def update_bpdu(message, curr_port, PORTS, bridgeInfo):
  """ 
  Updates the information of this bridge based on the message received.
  
  Parameters
  ----------
  message : dict
      dictionary (converted from JSON) that contains the message data
  curr_port : int
      Value of the current LAN port
  PORTS : list of Port objects
      List containing all the ports of this bridge
  bridgeInfo : BridgeInfo
      Object containing root id, cost, next_hop, and root port of this bridge
  """
  root_id = bridgeInfo.get_root_id()
  cost = bridgeInfo.get_cost()
  next_hop = bridgeInfo.get_next_hop()

  msg_root_id = message['message']['root']
  msg_cost = int(message['message']['cost'])
  msg_source = message['source']

  updated = False

  # Here, we update our bridge information if the BPDU we get is better our
  # current information.
  if ((msg_root_id < root_id)
    or (msg_root_id == root_id and msg_cost + 1 < cost)
    or (msg_root_id == root_id and msg_cost == cost 
      and msg_source < next_hop)):
    if(msg_root_id < root_id):
      bridgeInfo.set_root_id(msg_root_id)
      # Refresh the value of root_id after we update it
      root_id = bridgeInfo.get_root_id()
      print("New root: %s cost %d" % (root_id, message['message']['cost']+1))

    # Update our cost, hops, and root port in our bridgeInfo
    bridgeInfo.set_cost(msg_cost + 1)
    bridgeInfo.set_next_hop(msg_source)
    bridgeInfo.set_root_port(curr_port)

    # Update our min_costs in our PORTS list
    for port in PORTS:
      if port.get_id()!=curr_port:
        port.set_min_cost(999999)
      else:
        port.set_min_cost(bridgeInfo.get_cost() - 1)
    print("Root port: %d" % curr_port)
    send_bpdus(PORTS, bridgeInfo.get_root_id(), bridgeInfo.get_cost())
    updated = True
  elif((msg_root_id == root_id and msg_cost + 1 == cost and msg_source == next_hop)
    or root_id==bridgeInfo.get_bridge_id()):
    bridgeInfo.reset_unconfirmed ()

  # Update our min-cost if needed and enable or disable the current port if needed.
  if msg_root_id == bridgeInfo.get_root_id():
    PORTS[curr_port].update_min_cost(msg_cost)
    if (not(PORTS[curr_port].is_permanently_disabled()) and 
      (PORTS[curr_port].get_min_cost() >= bridgeInfo.get_cost() + 1 or 
      (PORTS[curr_port].get_min_cost() == bridgeInfo.get_cost() and msg_source >= args.bridge_id) or 
      (PORTS[curr_port].get_min_cost() == bridgeInfo.get_cost() - 1 and curr_port == bridgeInfo.get_root_port()))):
      if not(PORTS[curr_port].is_enabled()): 
        PORTS[curr_port].set_enabled(True)
    else:  
      if PORTS[curr_port].is_enabled(): 
        PORTS[curr_port].set_enabled(False)
  return updated

def broadcast_data(data, PORTS):
  """ Sends a message to all ports of this bridge. """
  for port in PORTS:
    port.send(data)

def sending_data(data, message, curr_port, PORTS, ADDR_TABLE):
  """ Forwards the given data to all other Ports on this bridge. """
  if message['source'] not in ADDR_TABLE:
    ADDR_TABLE[message['source']]=curr_port

  if message['dest'] in ADDR_TABLE: 
    port_id = ADDR_TABLE[message['dest']] 
    if port_id != curr_port and PORTS[port_id].is_enabled():
      print("Forwarding %s/%d to port %d"  % (message['source'], message['msg_id'], port_id))
      PORTS[port_id].send(data)
    else:
      print("Not forwarding %s/%d"  % (message['source'], message['msg_id']))
      
  else:
    print("Broadcasting %s/%d to all active ports"  % (message['source'], message['msg_id']))
    for port in PORTS:
      if(port!=PORTS[curr_port] and port.is_enabled()):
        port.send(data)

def main():
  """ Main function of this program. Sets up ports, threading, and the loop for sending/receiving messages. """

  # This variable represents our bridge's ports.  It is a 0-indexed array, as per the project spec
  PORTS = []

  # Holds the sources of the messages we get
  ADDR_TABLE = {}

  print("Bridge starting up")

  # All the important info of this bridge. Initialize with the bridge_id given in the commandline args
  bridgeInfo = BridgeInfo(args.bridge_id)

  # Set up our ports 
  for i, lan_port in enumerate(args.lan_ports):
    PORTS.append(Port(i, lan_port, get_port_from_lan_port(lan_port)< i))
  
  # Print the initial bridge status message
  print("New root: %s cost %d" % (bridgeInfo.get_root_id(), bridgeInfo.get_cost()))
  print("Root port: none")


  # Now we send a "hello" BPDU to all LANs to announce that we're here
  t1 = threading.Thread(target=send_bpdus_thread, args=(PORTS, ADDR_TABLE, bridgeInfo))  
  t1.start()

  # Main loop
  while True:
    sockets = list(map(lambda p: p.socket, PORTS))
    readable, _, execeptable = select.select(sockets, [], sockets)

    for s in readable:
      data, addr = s.recvfrom(1500)
      message = json.loads(data.decode('utf-8'))
      curr_port = get_port_from_lan_port(addr[1])
      
      if message['type']=='bpdu':
        # Update our bridge info if we get a BPDU
        updated = update_bpdu(message, curr_port, PORTS, bridgeInfo)  
        if updated:
          ADDR_TABLE = {}
      elif PORTS[curr_port].is_enabled(): 
        # Else, forward the message we got to the appropriate destination
        print("Received %s/%d on port %d to %s" % (message['source'], message['msg_id'], curr_port, message['dest']))
        sending_data(data, message, curr_port, PORTS, ADDR_TABLE)
        


if __name__ == "__main__":
  """Here, we run the main function of this program. """
  main()
