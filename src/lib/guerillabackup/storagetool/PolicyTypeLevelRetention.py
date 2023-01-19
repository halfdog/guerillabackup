"""This module provides backup data retention policy support."""

import datetime
import time
import guerillabackup.storagetool.Policy

class PolicyTypeLevelRetentionTagger():
  """This is a helper class for PolicyTypeLevelRetention to tag
  backup elements to be kept."""

# This is the specification for calender based alignment. Each
# tuple contains the name and the offset when counting does not
# start with 0.
  ALIGN_ATTR_SPEC = (
      ('year', 0), ('month', 1), ('day', 1),
      ('hour', 0), ('minute', 0), ('second', 0))

  def __init__(self, configDict):
    """Create a new aligned tagger component. The class will
    check all available backup data elements and tag those to
    be kept, that match the specification of this tagger. All
    backup data elements tagged by at least one tagger will be
    kept, the others marked for deletion.

    Configuration parameters for the tagger are:
    * KeepCount: This is the number of time intervals to search
      for matching backup data elements and thus the number of
      backups to keep at most. When there is no matching backup
      found within a time interval, the empty interval is also
      included in the count. When there is more than one backup
      within the interval, only the first one is kept. Thus e.g.
      having a "KeepCount" of 30 and a "Interval" setting of
      "day", this will cause backups to be kept from now till
      30 days ahead (or the time of the latest backup if "TimeRef"
      was set to "latest").
    * KeepInc: When true, keep also incremental backups within
      any interval where backups would be kept. This will also
      tag the previous full backup and any incremental backups
      in between for retention. Incremental backups after the
      last full backup are always kept unconditionally as the
      are required to restore the latest backup. Default is false.
    * Interval: This is the size of the retention interval to
      keep one backup per interval. Values are "year", "month",
      "day", "hour".
    * TimeRef: This defines the time reference to use to perform
      the retention policy evaluation. With "latest" the time
      of the newest backup is used, while "now" uses the current
      time. The default is "now".
    " AlignModulus: This defines the modulus when aligning backup
      retention to values other than the "Interval" unit, e.g.
      to keep one backup every three month.
    * AlignValue: When defined this will make backups to be aligned
      to that value related to the modulus, e.g. to keep backups
      of January, April, July, October an "AlignModulus" of 3
      and "AlignValue" of 1 is required."""
    self.intervalUnit = None
    self.alignModulus = 1
    self.alignValue = 0
    self.keepCount = None
    self.keepIncFlag = False
    self.timeReferenceType = 'now'

    for configKey, configValue in configDict.items():
      if configKey == 'AlignModulus':
        if (not isinstance(configValue, int)) or (configValue < 1):
          raise Exception()
        self.alignModulus = configValue
      elif configKey == 'AlignValue':
        if (not isinstance(configValue, int)) or (configValue < 0):
          raise Exception()
        self.alignValue = configValue
      elif configKey == 'Interval':
        if configValue not in ['year', 'month', 'day', 'hour']:
          raise Exception()
        self.intervalUnit = configValue
      elif configKey == 'KeepCount':
        if (not isinstance(configValue, int)) or (configValue < 1):
          raise Exception()
        self.keepCount = configValue
      elif configKey == 'KeepInc':
        if not isinstance(configValue, bool):
          raise Exception()
        self.keepIncFlag = configValue
      elif configKey == 'TimeRef':
        if configValue not in ['latest', 'now']:
          raise Exception()
        self.timeReferenceType = configValue
      else:
        raise Exception(
            'Unsupported configuration parameter %s' % repr(configKey))

    if self.keepCount is None:
      raise Exception('Mandatory KeepCount parameter not set')
    if (self.intervalUnit is not None) and \
        (self.alignModulus <= self.alignValue):
      raise Exception('Align value has to be smaller than modulus')

  def tagBackups(self, backupList, tagList):
    """Check which backup elements should be kept and tag them
    in the tagList.
    @param backupList the sorted list of backup data elements.
    @param tagList list of boolean values of same length as the
    backupList. The list should be initialized to all False values
    before calling tagBackups for the first time."""

    if len(backupList) != len(tagList):
      raise Exception()

# Always tag the newest backup.
    tagList[-1] = True

    referenceTime = None
    if self.timeReferenceType == 'now':
      referenceTime = datetime.datetime.fromtimestamp(time.time())
    elif self.timeReferenceType == 'latest':
      referenceTime = datetime.datetime.fromtimestamp(
          backupList[-1].getDatetimeSeconds())
    else:
      raise Exception('Logic error')

# Prefill the data with the default field offsets.
    alignedTimeData = [x[1] for x in self.ALIGN_ATTR_SPEC]
    alignFieldValue = None
    for alignPos in range(0, len(self.ALIGN_ATTR_SPEC)):
      alignedTimeData[alignPos] = getattr(
          referenceTime, self.ALIGN_ATTR_SPEC[alignPos][0])
      if self.intervalUnit == self.ALIGN_ATTR_SPEC[alignPos][0]:
        alignFieldValue = alignedTimeData[alignPos]
        break

    startSearchTime = datetime.datetime(*alignedTimeData).timestamp()
# Handle alignment and modulus rules.
    if (self.alignModulus != 1) and (self.alignValue is not None):
      startSearchTime = self.decreaseTimeField(
          startSearchTime,
          (alignFieldValue - self.alignValue) % self.alignModulus)

    keepAttempts = self.keepCount + 1
    while keepAttempts != 0:
      for pos, backupElement in enumerate(backupList):
        backupElement = backupList[pos]
        if (backupElement.getDatetimeSeconds() >= startSearchTime) and \
            ((backupElement.getType() == 'full') or self.keepIncFlag):
          tagList[pos] = True
# Tag all incrementals within the interval.
          if not self.keepIncFlag:
            break

# Move down units of intervalUnit size.
      startSearchTime = self.decreaseTimeField(
          startSearchTime, self.alignModulus)
      keepAttempts -= 1

# Now after tagging select also those incremental backups in between
# to guaranteee that they can be really restored.
    forceTaggingFlag = True
    for pos in range(len(backupList) - 1, -1, -1):
      if forceTaggingFlag:
        tagList[pos] = True
        if backupList[pos].getType() == 'full':
          forceTaggingFlag = False
      elif (tagList[pos]) and (backupList[pos].getType() == 'inc'):
        forceTaggingFlag = True

  def decreaseTimeField(self, timestamp, decreaseCount):
    """Decrease a given time value."""
    timeValue = datetime.datetime.fromtimestamp(timestamp)
    if self.intervalUnit == 'year':
      timeValue = timeValue.replace(year=timeValue.year-decreaseCount)
    elif self.intervalUnit == 'month':
# Decrease the month values. As the timestamp was aligned to
# the first of the month already, the month value can be simple
# decreased.
      for modPos in range(0, decreaseCount):
        if timeValue.month == 1:
          timeValue = timeValue.replace(year=timeValue.year-1, month=12)
        else:
          timeValue = timeValue.replace(month=timeValue.month-1)
    elif self.intervalUnit == 'day':
      timeValue = timeValue - datetime.timedelta(days=decreaseCount)
    else:
      raise Exception('Logic error')
    return timeValue.timestamp()


class PolicyTypeLevelRetention(guerillabackup.storagetool.Policy.Policy):
  """This policy type defines a data retention policy keeping
  a number of backups for each time level. The policy itself
  does not rely on the backup source status but only on the list
  of backup data elmeents. The policy will flag elements to be
  deleted when this retention policy has no use for those elmements
  and will fail if another, concurrent policy or manual intervention,
  has flagged elements for deletion which should be kept according
  to this policy."""

  POLICY_NAME = 'LevelRetention'

  def __init__(self, policyConfig):
    """Instantiate this policy object from a JSON policy configuration
    definition."""
    super().__init__(policyConfig)

# This is the list of retention level definitions.
    self.levelList = []

    for configKey, configValue in policyConfig.items():
      if configKey in ('Name', 'Priority'):
        continue
      if configKey == 'Levels':
        self.parseLevelConfig(configValue)
        continue
      raise Exception('Unknown policy configuration setting "%s"' % configKey)

# Validate the configuration settings.
    if not self.levelList:
      raise Exception()

  def parseLevelConfig(self, levelConfigList):
    """Parse the retention policy level configuration."""
    if not isinstance(levelConfigList, list):
      raise Exception()
    for levelConfig in levelConfigList:
      if not isinstance(levelConfig, dict):
        raise Exception()
      self.levelList.append(PolicyTypeLevelRetentionTagger(levelConfig))

  def apply(self, sourceStatus):
    """Apply this policy to a backup source status."""
    elementList = sourceStatus.getDataElementList()
    tagList = [False] * len(elementList)
    for levelTagger in self.levelList:
      levelTagger.tagBackups(elementList, tagList)
    for tagPos, element in enumerate(elementList):
      element.markForDeletion(not tagList[tagPos])

  def delete(self, sourceStatus):
    """Prepare the policy status data for deletions going to
    happen later on."""
