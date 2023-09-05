#!/usr/bin/env python3 

import atexit
import sys
import os
import time
import json
import random
import select
import socket
import subprocess
from functools import reduce
from collections import defaultdict

def die(msg):
  raise ValueError("Error: %s" % msg)

start = time.time()

def log(caller, msg):
  print("[%02.4f  %11s]: %s" % (time.time() - start, caller, msg))
  pass

#### PARAMETERS

DEFAULT_PACKET_START_WAIT = 2
DEFAULT_PACKET_STOP_WAIT = 1
EXECUTABLE_NAME = "3700bridge"
MESSAGE_DELAY = 0.01

#### JSON CHECKING CODE

def check_json(config, val, required, required_type, test=None):
  if required and val not in config:
    die("Missing field %s" % val)

  if val in config and type(config[val]) != required_type:
    die("Invalid type for field %s; was %s must be %s" % (val, type(config[val]), required_type))
  
  if val in config and test and not test(config[val]):
    die("Invalid value '%s' for %s" % (config[val], val))

  return True

#### CONFIG FILE CODE

def get_config(config_file):
  # Load config file
  if not os.path.exists(config_file):
    die("Could not find config file '%s'" % config_file)

  try:
    with open(config_file) as f:
      config_data = f.read()
  except Exception as e:
    die("Unable to read data from config file '%s': %s" % (config_file, e))

  try:
    config = json.loads(config_data)
  except Exception as e:
    die("Unable to parse JSON in config file '%s': %s" % (config_file, e))

  def check_config(config, val, required, required_type, test=None):
    try:
      return check_json(config, val, required, required_type, test)
    except ValueError as e:
      die("Invalid config file: %s" % e)

  check_config(config, "lifetime", True, int, lambda a: a > 0)
  check_config(config, "hosts", True, int, lambda a: a > 0)
  check_config(config, "packets", True, int, lambda a: a > 0)
  check_config(config, "seed", False, int)
  check_config(config, "wait", False, int, lambda a: a > 0 and a < config["lifetime"])
  check_config(config, "bridges", True, list, 
    lambda a: len(a) > 0 and 
      all(map(lambda bridge: type(bridge) == dict and 
                check_config(bridge, "id", True, str, lambda a: len(a) == 4) and 
                check_config(bridge, "start", False, int, lambda a: a > 0 and a < config["lifetime"]) and
                check_config(bridge, "stop", False, int, lambda a: a > 0 and a < config["lifetime"] and (not "start" in bridge or a > bridge["start"])) and
                check_config(bridge, "lans", True, list, lambda l: len(l) > 0 and 
                                                          all(map(lambda lan: type(lan) == int and lan > 0, l))), a)))

  return config

#### EXECUTABLE FILE CODE

def get_executable():
  if not os.path.exists(EXECUTABLE_NAME):
    die("Could not find bridge program '%s'" % EXECUTABLE_NAME)

  if not os.access(EXECUTABLE_NAME, os.X_OK):
    die("Could not execute bridge program '%s'" % EXECUTABLE_NAME)

#### EVENT CODE

EVENTS = []

class Event:
  def __init__(self, time, func):
    self.time = time
    self.func = func

  def __str__(self):
    return "{ event at time: %.4f }" % (self.time)

  def execute(self):
    self.func()


def add_event(time, func):
  global EVENTS
  EVENTS.append(Event(time, func))
  EVENTS = sorted(EVENTS, key=lambda e: -1 * e.time)

def next_event_time():
  global EVENTS
  return EVENTS[len(EVENTS)-1].time

def next_event_pop():
  global EVENTS
  return EVENTS.pop()

#### FD WRAPPER

class FDWrapper:
  def __init__(self, fd, parent):
    self.fd = fd
    self.parent = parent

  def fileno(self):
    return self.fd.fileno()

#### BRIDGE CODE

BRIDGES = {}

def _cleanup_proc(p):
  if p.poll() is None:
    p.kill()

class Bridge:
  def __init__(self, id, lans):
    self.id = id
    self.lans = lans
    self.process = None

  def __str__(self):
    return self.id

  def is_started(self):
    return self.process is not None

  def start(self):
    args = "%s %s %s" % (os.path.join(".", EXECUTABLE_NAME), self.id, " ".join(map(lambda l: str(l.port), self.lans)))
    log("Simulator", "Starting bridge %s with command '%s'" % (self.id, args))
    self.process = subprocess.Popen(args, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def make_non_blocking(fd):
      try:
        from fcntl import fcntl, F_GETFL, F_SETFL
        flags = fcntl(fd, F_GETFL) # get current p.stdout flags
        fcntl(fd, F_SETFL, flags | os.O_NONBLOCK) 
      except ImportError:
        print("Warning:  Unable to load fcntl module; things may not work as expected.")

    make_non_blocking(self.process.stdout)
    make_non_blocking(self.process.stderr)

    for lan in self.lans:
      lan.add_bridge(self)

    atexit.register(self.stop)

  def stop(self):
    if self.process and self.process.poll() is None:
      self.process.terminate()
    self.process = None

    for lan in self.lans:
      lan.remove_bridge(self)
    self.lans = []

  def get_fds(self):
    if self.process:
      return [FDWrapper(self.process.stdout, self), FDWrapper(self.process.stderr, self)]
    else:
      return []

  def read(self, fd):
    data = fd.fd.read(1500).decode('utf-8')
    if self.process.returncode is not None or len(data) == 0:
      die("Bridge %s crashed; exiting" % self.id)

    for line in data.strip().split("\n"):
      log("Bridge %s" % self.id, line)

def create_bridge(bridge_data):
  lans = list(map(lambda lan: add_lan(lan), bridge_data["lans"]))
  bridge = Bridge(bridge_data["id"], lans)

  add_event(bridge_data["start"] if "start" in bridge_data else 0, lambda: bridge.start())

  if "stop" in bridge_data:
    add_event(bridge_data["stop"], lambda: bridge.stop())

  BRIDGES[bridge.id] = bridge

#### LAN CODE

LANS = {}

class LAN:
  def __init__(self, id):
    self.id = id
    self.hosts = []
    self.bridges = []
    self.clients = []
    self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.socket.bind(('localhost', 0))

    self.port = self.socket.getsockname()[1]
#    log("LAN %s" % self.id, "Bound to port %d" % self.port)

    self.bpdu_messages_sent = 0
    self.data_messages_sent = 0

  def __str__(self):
    return self.id

  def get_fds(self):
    return [FDWrapper(self.socket, self)]

  def read(self, socket):
    data, addr = self.socket.recvfrom(1500)
    if addr not in self.clients:
      self.clients.append(addr)
    
#    log("LAN %s" % self.id, "Received message from port %s" % addr[1])
    if MESSAGE_DELAY:
      add_event(MESSAGE_DELAY + time.time() - start, lambda: self.broadcast(Message.unserialize(data), addr))
    else:
      self.broadcast(Message.unserialize(data), addr)

  def add_host(self, host):
    self.hosts.append(host)

  def add_bridge(self, bridge):
    self.bridges.append(bridge)

  def remove_bridge(self, bridge):
    self.bridges.remove(bridge)

  def broadcast(self, message, skip=None):
#    log("LAN %s" % self.id, "Broadcasting message %s with %d clients" % (message, len(self.clients)))

    if message.type == "bpdu":
      self.bpdu_messages_sent += 1
    else:
      self.data_messages_sent += 1

    for addr in self.clients:
      if addr != skip:
        self.socket.sendto(message.serialize(), addr)

    for host in self.hosts:
      host.receive(message)

def add_lan(lan):
  if not lan in LANS.keys():
    LANS[lan] = LAN(lan)

  return LANS[lan]

def random_lan():
  return LANS[random.choice(list(LANS.keys()))]

#### HOST CODE

HOSTS = {}

class Host:
  def __init__(self, id, lan):
    self.id = id
    self.lan = lan
    self.msg_count = 0
    lan.add_host(self)    

    log("Host %s" % self.id, "Host created on LAN %s" % self.lan.id)

  def __str__(self):
    return self.id

  def send(self, message):
    log("Host %s" % self.id, "Sending message %s/%d to %s" % (message.source, message.id, message.dest))
    self.lan.broadcast(message)

  def receive(self, message):
    if message.dest == self.id:
      log("Host %s" % self.id, "Received message %s/%d for self" % (message.source, message.id))
      get_packet(message.source, message.id).set_delivered()
#    else:
#      log("Host %s" % self.id, "Ignoring message %s" % message)

  def add_packet(self, config):
    dest = random_host(self)
    packet = Packet(self.msg_count, self, dest)

    add_event(random.uniform(config["wait"] if "wait" in config else DEFAULT_PACKET_START_WAIT, config["lifetime"] - DEFAULT_PACKET_STOP_WAIT), lambda: packet.send())
    self.msg_count += 1

def add_host():
  id = "%x%x%x%x" % (random.randrange(0, 15), random.randrange(0, 15), random.randrange(0, 15), random.randrange(0, 15))
  lan = random_lan()

  HOSTS[id] = Host(id, lan)

def random_host(exclude = None):
  source = list(HOSTS.keys())
  if exclude:
    source.remove(exclude.id)
  return HOSTS[random.choice(source)]

#### MESSAGE CODE
# Messages are things on the wire

class Message:
  def __init__(self, source, dest, id, kind, message):
    self.source = source
    self.dest = dest
    self.id = id
    self.type = kind
    self.message = message

  def __str__(self):
    return "{ source: %s, dest: %s, type: %s, message: %s }" % (self.source, self.dest, self.type, self.message)

  def serialize(self):
    return json.dumps({ "source": self.source, "dest": self.dest, "msg_id": self.id, "type": self.type, "message": self.message }).encode('utf-8')

  def unserialize(raw):
    try:
      data = json.loads(raw.decode('utf-8'))
    except Exception as e:
      raise ValueError("Cannot parse JSON message: '%s'" % raw.decode('utf-8'))

    def check_message(data, val, required, required_type, test=None):
      try:
        return check_json(data, val, required, required_type, test)
      except ValueError as e:
        die("Incorrectly formatted message '%s': %s" % (data, e))
        
    check_message(data, "source", True, str, lambda a: len(a) == 4)
    check_message(data, "dest", True, str, lambda a: len(a) == 4)
    check_message(data, "type", True, str, lambda a: a == "bpdu" or a == "data")
    check_message(data, "msg_id", True, int, lambda b: b >= 0)
    check_message(data, "message", True, dict, lambda a: 
                                                  (data["type"] == "bpdu" and check_message(a, "id", True, str, lambda b: len(b) == 4) and
                                                                              check_message(a, "root", True, str, lambda b: len(b) == 4) and
                                                                              check_message(a, "cost", True, int, lambda b: b >= 0) and
                                                                              check_message(a, "port", True, int, lambda b: b >= 0)) or 
                                                  (data["type"] == "data"))


    return Message(data["source"], data["dest"], data["msg_id"], data["type"], data["message"])

#### PACKET CODE

PACKETS = defaultdict(lambda: {})

class Packet:
  def __init__(self, id, source, dest):
    self.id = id
    self.source = source
    self.dest = dest
    self.sent = False
    self.received_count = 0
    self.data = ''.join([random.choice("0123456789abcdef") for x in range(32)])

    PACKETS[source.id][id] = self

  def __str__(self):
    return "{ id: %s, source: %s, dest: %s, data: %s}" % (self.id, self.source, self.dest, self.data)

  def send(self):
    self.sent = True
    self.source.send(self.to_message())

  def to_message(self):
    return Message(self.source.id, self.dest.id, self.id, "data", { "data": self.data })

  def set_delivered(self):
    self.received_count += 1

def get_packet(source, id):
  return PACKETS[source][id]

#### MAIN PROGRAM

if len(sys.argv) != 2:
  die("Usage: ./run config-file")

get_executable()
config = get_config(sys.argv[1])

if "seed" in config:
  random.seed(config["seed"])

# Set up the bridges, get LAN info
for bridge in config["bridges"]:
  create_bridge(bridge)

# Set up the hosts
for i in range(config["hosts"]):
  add_host()

# Set up the packets
for i in range(config["packets"]):
  random_host().add_packet(config)

def now():
  return time.time() - start

done = False
def finish():
  all_packets = [PACKETS[source][id] for source in PACKETS.keys() for id in PACKETS[source]]

  packets_sent = list(filter(lambda p: p.sent, all_packets))
  packets_received = list(filter(lambda p: p.received_count > 0, all_packets))
  packets_not_delivered = [p for p in packets_sent if p not in packets_received]
  packets_duplicated = list(filter(lambda p: p.received_count > 1, all_packets))

  bpdu_messages_sent = sum(map(lambda l: l.bpdu_messages_sent, LANS.values()))
  data_messages_sent = sum(map(lambda l: l.data_messages_sent, LANS.values()))

  print("Simulation finished.\n\n")

  print("CORRECTNESS:")
  print("Packets sent: %d" % len(packets_sent))
  print("Packets not delivered: %d (%.2f%%, msg_ids %s)" % (len(packets_not_delivered), len(packets_not_delivered)*100.0/len(packets_sent), list(map(lambda p: "%s/%s" % (p.source, p.id), packets_not_delivered))))
  print("Percentage packets delivered: %.4f%%" % (len(packets_received)*100.0/len(packets_sent)))

  print("")

  print("PERFORMANCE:")
  print("Messages sent on wire: %d (%d BPDUs, %d data)" % (bpdu_messages_sent + data_messages_sent, bpdu_messages_sent, data_messages_sent))
  print("Packets delivered multiple times: %d (%.2f%%, msg_ids %s)" % (sum(map(lambda p: p.received_count, packets_duplicated)), len(packets_duplicated)*100.0/len(packets_sent), ", ".join(map(lambda p: "%s/%s [x%d]" % (p.source, p.id, p.received_count), packets_duplicated))))
  print("Effective goodput: %.4f%%" % (len(packets_received) * 100.0/(data_messages_sent + bpdu_messages_sent)))

  sys.exit(0)

add_event(config["lifetime"], finish)

try:
  while not done:
    time_to_event = next_event_time() - now()

    if time_to_event > 0:
      bridge_fds = list(reduce(lambda a, b: a + b.get_fds(), filter(lambda b: b.is_started(), BRIDGES.values()), []))
      lan_fds = list(reduce(lambda a, b: a + b.get_fds(), LANS.values(), []))
      readable, _, exceptable = select.select(bridge_fds + lan_fds, [], bridge_fds + lan_fds, time_to_event)

      # handle any data
      for fd in readable:
        fd.parent.read(fd)

      # handle any exceptions
      for fd in exceptable:
        fd.parent.exception(fd)

    
    time_to_event = next_event_time() - now()
    if time_to_event <= 0:
      next_event_pop().execute()
except ValueError as e:
  print(e)