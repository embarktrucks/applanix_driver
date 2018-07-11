#! /usr/bin/env python
# -*- coding: utf-8 -*-
#     _____
#    /  _  \
#   / _/ \  \
#  / / \_/   \
# /  \_/  _   \  ___  _    ___   ___   ____   ____   ___   _____  _   _
# \  / \_/ \  / /  _\| |  | __| / _ \ | ┌┐ \ | ┌┐ \ / _ \ |_   _|| | | |
#  \ \_/ \_/ /  | |  | |  | └─┐| |_| || └┘ / | └┘_/| |_| |  | |  | └─┘ |
#   \  \_/  /   | |_ | |_ | ┌─┘|  _  || |\ \ | |   |  _  |  | |  | ┌─┐ |
#    \_____/    \___/|___||___||_| |_||_| \_\|_|   |_| |_|  |_|  |_| |_|
#            ROBOTICS™
#
#
#  Copyright © 2012 Clearpath Robotics, Inc. 
#  All Rights Reserved
#  
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of Clearpath Robotics, Inc. nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL CLEARPATH ROBOTICS, INC. BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# Please send comments, questions, or patches to skynet@clearpathrobotics.com
#

# ROS
import rospy
import applanix_msgs.msg

# Package modules
from data import DataPort
from control import ControlPort
from monitor import Monitor

# Standard
import socket
import struct
from cStringIO import StringIO
import time

import translator
from handlers import NullHandler, GroupHandler, MessageHandler, AckHandler

PORTS_DATA = {
    "realtime": 5602,
    "logging": 5603
    }
PORT_CONTROL = 5601

DEFAULT_IP = '192.168.53.100'
PREFIX_DEFAULTS = {
    "raw": True,
    "dmi": True,
    "status": True,
    "events": True
    }

SOCKET_TIMEOUT=10.0
socks = []
ports = {}
monitor = Monitor(ports)


def main():
  rospy.init_node('applanix_bridge')

  # Where to find the device. It does not support DHCP, so you'll need
  # to connect initially to the factory default IP in order to change it.
  ip = rospy.get_param('ip', DEFAULT_IP)

  # Select between realtime and logging data ports. The logging data is
  # optimized for completeness, whereas the realtime data is optimized for
  # freshness.
  data_port = PORTS_DATA[rospy.get_param('data', "realtime")]

  # Disable this to not connect to the control socket (for example, if you
  # want to control the device using the Applanix POS-LV software rather
  # than ROS-based services.
  control_enabled = rospy.get_param('control', True)

  # Disable any of these to hide auxiliary topics which you may not be
  # interested in.
  exclude_prefixes = []
  for prefix, default in PREFIX_DEFAULTS.items():
    if not rospy.get_param('include_%s' % prefix, default):
      exclude_prefixes.append(prefix)

  # Pass this parameter to use pcap data rather than a socket to a device.
  # For testing the node itself--to exercise downstream algorithms, use a bag.
  pcap_file_name = rospy.get_param('pcap_file', False)

  # handle shutdown, even when we're still starting up
  rospy.on_shutdown(shutdown)
  
  if not pcap_file_name:
    sock = create_sock('data', ip, data_port)
  else:
    sock = create_test_sock(pcap_file_name)

  ports['data'] = DataPort(sock, exclude_prefixes=exclude_prefixes)

  if control_enabled:
    ports['control'] = ControlPort(create_sock('control', ip, PORT_CONTROL))

  for name, port in ports.items():
    port.start()
    rospy.loginfo("Port %s thread started." % name)
  monitor.start()

  rospy.spin()


def create_sock(name, ip, port):
  try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ip_port = (ip, port)
    socks.append(sock)
    sock.connect(ip_port)
    rospy.loginfo("Successfully connected to %%s port at %s:%d" % ip_port % name)
  except socket.error as e:
    rospy.logfatal("Couldn't connect to %%s port at %s:%d: %%s" % ip_port % (name, str(e)))
    exit(1)
  return sock


def create_test_sock(pcap_filename):
  rospy.sleep(0.1)

  import pcapy
  from StringIO import StringIO
  from impacket import ImpactDecoder

  body_list = []
  cap = pcapy.open_offline(pcap_filename)
  decoder = ImpactDecoder.EthDecoder()

  while True:
    header, payload = cap.next()
    if not header: break
    udp = decoder.decode(payload).child().child()
    body_list.append(udp.child().get_packet())

  data_io = StringIO(''.join(body_list))

  class MockSocket(object):
    def recv(self, byte_count):
      rospy.sleep(0.0001)
      data = data_io.read(byte_count)
      if data == "":
        rospy.signal_shutdown("Test completed.")
      return data  
    def settimeout(self, timeout):
      pass

  return MockSocket()


def shutdown():
  if monitor.is_alive():
    monitor.finish.set()
    monitor.join()
  rospy.loginfo("Thread monitor finished.") 
  for name, port in ports.items():
    if port.is_alive():
      port.finish.set()
      port.join()
    rospy.loginfo("Port %s thread finished." % name) 
  for sock in socks:
    sock.shutdown(socket.SHUT_RDWR)
    sock.close()
  rospy.loginfo("Sockets closed.") 
