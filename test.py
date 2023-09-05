#!/usr/bin/env python3

import os
import subprocess
import sys
import re

EXECUTABLE_NAME = "3700bridge"
RUN_SCRIPT_NAME = "run"
CONFIG_DIR = "configs"

def get_files():
  if not os.path.exists(EXECUTABLE_NAME):
    die("Could not find bridge program '%s'" % EXECUTABLE_NAME)

  if not os.access(EXECUTABLE_NAME, os.X_OK):
    die("Could not execute bridge program '%s'" % EXECUTABLE_NAME)

  if not os.path.exists(RUN_SCRIPT_NAME):
    die("Could not find simulator '%s'" % EXECUTABLE_NAME)

  if not os.access(RUN_SCRIPT_NAME, os.X_OK):
    die("Could not execute simulator '%s'" % RUN_SCRIPT_NAME)


get_files()

def runTest(problem, config, expected_percentage, expected_goodput=0):
  print("%s" % ("%s (%s)" % (problem, config)).ljust(60, ' '), end='')

  result = subprocess.check_output([os.path.join(os.getcwd(), RUN_SCRIPT_NAME), os.path.join(CONFIG_DIR, config)]).decode('utf-8')
  
  pattern = re.compile("Percentage packets delivered: ([0-9\.]+)%.*Effective goodput: ([0-9\.]+)%", re.DOTALL)
  m = re.search(pattern, result)
  if m:
    percentage = float(m.group(1))
    goodput = float(m.group(2))
    if percentage >= expected_percentage and goodput >= expected_goodput:
      print("[PASS]")
    else:
      print("[FAIL]")
      if percentage < expected_percentage:
        print("  percentage was %.4f%%, required %.4f%%" % (percentage, expected_percentage))
      if goodput < expected_goodput:
        print("  goodput was %.4f%%, required %.4f%%" % (goodput, expected_goodput))
  else:
    print("[ERROR]")

print("Starter (single bridge) tests (delivery = 100%)")
runTest("One bridge, one LAN", "simple-1.conf", 100)
runTest("One bridge, two LANs", "simple-2.conf", 100)

print("\nBasic (no failures, no new bridges) tests (delivery = 100%, goodput >= 5%)")
runTest("One bridge, three LANs", "simple-3.conf", 100, 5)
runTest("Two bridges, two LANs", "simple-5.conf", 100, 5)
runTest("Three bridges, eight LANs", "simple-6.conf", 100, 5)
runTest("Eight bridges, eight LANs", "simple-7.conf", 100, 5)

print("\nIntermediate (no failures, new bridges) tests (delivery >= 80%, goodput >= 1%)")
runTest("Three bridges, two LANs", "intermediate-1.conf", 80, 1)
runTest("Four bridges, three LANs", "intermediate-2.conf", 80, 1)
runTest("Eight bridges, eight LANs", "intermediate-3.conf", 80, 1)
runTest("Eight bridges, eight LANs", "intermediate-4.conf", 80, 1)

print("\nAdvanced (failures, new bridges) tests (delivery >= 60.0%, goodput >= 0.1%)")
runTest("Three bridges, two LANs", "advanced-1.conf", 60, 0.1)
runTest("Four bridges, three LANs", "advanced-2.conf", 60, 0.1)
runTest("Eight bridges, eight LANs", "advanced-3.conf", 60, 0.1)