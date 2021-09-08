"""This module provides various condition classes to determine
if a backup unit can be run if the unit itself is ready to be
run."""

import time

import guerillabackup

class IUnitRunCondition():
  """This is the interface of all unit run condition classes."""

  def evaluate(self):
    """Evaluate this condition.
    @return True if the condition is met, false otherwise."""
    raise NotImplementedError()


class AverageLoadLimitCondition(IUnitRunCondition):
  """This condition class allows to check the load stayed below
  a given limit for some time."""

  def __init__(self, loadLimit, limitOkSeconds):
    """Create a new load limit condition.
    @param loadLimit the 1 minute CPU load limit to stay below.
    @param limitOkSeconds the number of seconds the machine 1
    minute load value has to stay below the limit for this condition
    to be met."""
    self.loadLimit = loadLimit
    self.limitOkSeconds = limitOkSeconds
    self.limitOkStartTime = None

  def evaluate(self):
    """Evaluate this condition.
    @return True when the condition is met."""
    loadFile = open('/proc/loadavg', 'rb')
    loadData = loadFile.read()
    loadFile.close()
    load1Min = float(loadData.split(b' ')[0])
    if load1Min >= self.loadLimit:
      self.limitOkStartTime = None
      return False
    currentTime = time.time()
    if self.limitOkStartTime is None:
      self.limitOkStartTime = currentTime
    return (self.limitOkStartTime + self.limitOkSeconds <= currentTime)


class LogicalAndCondition(IUnitRunCondition):
  """This condition checks if all subconditions evaluate to true.
  Even when a condition fails to evaluate to true all other conditions
  are still checked to allow time sensitive conditions keep track
  of time elapsed."""

  def __init__(self, conditionList):
    """Create a logical and condition.
    @param conditionList the list of conditions to be met."""
    self.conditionList = conditionList

  def evaluate(self):
    """Evaluate this condition.
    @return True when the condition is met."""
    result = True
    for condition in self.conditionList:
      if not condition.evaluate():
        result = False
    return result


class MinPowerOnTimeCondition():
  """This class checks if the machine was in powered on long
  enough to be in stable state and ready for backup load."""

  def __init__(self, minPowerOnSeconds):
    """Create a condition to check machine power up time.
    @param minPowerOnSeconds the minimum number of seconds the
    machine has to be powered on."""
    self.minPowerOnSeconds = minPowerOnSeconds

  def evaluate(self):
    """Evaluate this condition.
    @return True when the condition is met."""
    uptimeFile = open('/proc/uptime', 'rb')
    uptimeData = uptimeFile.read()
    uptimeFile.close()
    uptime = float(uptimeData.split(b' ')[0])
    return (uptime >= self.minPowerOnSeconds)
