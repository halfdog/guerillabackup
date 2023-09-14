"""This module provides support for the backup interval checking
policy."""

import json
import sys

import guerillabackup.storagetool.Policy

class PolicyTypeInterval(guerillabackup.storagetool.Policy.Policy):
  """This policy type defines a policy checking file intervals
  between full and incremental backups (if available).

  Applying the policies will also use and modify following backup
  data element status information fields:
  * LastFull, LastInc: Timestamp of previous element in case
    the element was deleted. Otherwise policy checks would report
    policy failures when pruning data storage elements.
  * Ignore: When set ignore interval policy violations of that
    type, i.e. full, inc, both related to the previous backup
    data element.
  * Dead: When set, this source will not produce any more backups.
    Therefore ignore any gap after this last backup and report
    a policy violation if more backups are seen."""

  POLICY_NAME = 'Interval'

  def __init__(self, policyConfig):
    """Instantiate this policy object from a JSON policy configuration
    definition."""
    super().__init__(policyConfig)
    self.config = {}
    self.timeFullMin = None
    self.timeFullMax = None
# This is the minimal time between incremental backups or None
# if this source does not emit any incremental backups.
    self.timeIncMin = None
    self.timeIncMax = None

    for configKey, configValue in policyConfig.items():
      if configKey in ('Name', 'Priority'):
        continue
      self.config[configKey] = configValue
      if configKey not in ('FullMax', 'FullMin', 'IncMax', 'IncMin'):
        raise Exception('Unknown policy configuration setting "%s"' % configKey)

      timeVal = None
      if configValue is not None:
        if not isinstance(configValue, str):
          raise Exception(
              'Policy setting "%s" has to be a string' % configKey)
        timeVal = guerillabackup.Utils.parseTimeDef(configValue)
      if configKey == 'FullMax':
        self.timeFullMax = timeVal
      elif configKey == 'FullMin':
        self.timeFullMin = timeVal
      elif configKey == 'IncMax':
        self.timeIncMax = timeVal
      else:
        self.timeIncMin = timeVal

# Validate the configuration settings.
    if (self.timeFullMin is None) or (self.timeFullMax is None):
      raise Exception()
    if self.timeFullMin > self.timeFullMax:
      raise Exception()
    if self.timeIncMax is None:
      if self.timeIncMin is not None:
        raise Exception()
    elif (self.timeIncMin > self.timeIncMax) or \
        (self.timeIncMin > self.timeFullMin) or \
        (self.timeIncMax > self.timeFullMax):
      raise Exception()

  def apply(self, sourceStatus):
    """Apply this policy to a backup source status."""
    elementList = sourceStatus.getDataElementList()
    currentPolicy = None

    lastElement = None
    lastFullElementName = None
    lastFullTime = None
    lastIncTime = None
    for elem in elementList:
      policyData = elem.getPolicyData(PolicyTypeInterval.POLICY_NAME)
      ignoreType = None
      if policyData is not None:
        for key in policyData.keys():
          if key not in ('Config', 'Ignore', 'LastFull', 'LastInc'):
            raise Exception(
                'Policy status configuration for "%s" in ' \
                '"%s" corrupted: %s' % (
                    elem.getElementName(),
                    sourceStatus.getStorageStatus().getStatusFileName(),
                    repr(policyData)))
        if 'LastFull' in policyData:
          lastFullTime = policyData['LastFull']
          lastFullElementName = '?'
          lastIncTime = policyData['LastInc']
        if 'Config' in policyData:
# Use the additional policy data.
          initConfig = dict(policyData['Config'])
          initConfig['Name'] = PolicyTypeInterval.POLICY_NAME
          currentPolicy = PolicyTypeInterval(initConfig)
        ignoreType = policyData.get('Ignore', None)
      if currentPolicy is None:
# This is the first element and default policy data was not copied
# yet.
        elem.updatePolicyData(
            PolicyTypeInterval.POLICY_NAME,
            {'Config': self.config})
        currentPolicy = self
      elemTime = elem.getDatetimeSeconds()
      if lastFullTime is None:
# This is the first element.
        if elem.getType() != 'full':
          print(
              'Backup source %s starts with incremental ' \
              'backups, storage might be corrupted.' % (
                  sourceStatus.getSourceName()), file=sys.stderr)
        lastFullTime = lastIncTime = elemTime
        lastFullElementName = elem.getElementName()
      else:
# Now check the time policy.
        fullValidationOkFlag = False
        if elem.getType() == 'full':
          if ignoreType not in ('both', 'full'):
            fullDelta = elemTime - lastFullTime
            if fullDelta < currentPolicy.timeFullMin:
              print(
                  'Backup source %s emitting full backups ' \
                  'faster than expected between "%s" and "%s".' % (
                      sourceStatus.getSourceName(),
                      lastFullElementName,
                      elem.getElementName()), file=sys.stderr)
            elif fullDelta > currentPolicy.timeFullMax:
              print(
                  'Backup source "%s" full interval too big ' \
                  'between "%s" and "%s".' % (
                      sourceStatus.getSourceName(),
                      lastFullElementName,
                      elem.getElementName()), file=sys.stderr)
            else:
              fullValidationOkFlag = True

            if not fullValidationOkFlag:
              print(
                  'No interactive/automatic policy or ' \
                  'status update, consider adding this ' \
                  'manually to the status in %s:\n%s' % (
                      sourceStatus.getStorageStatus().getStatusFileName(),
                      json.dumps(
                          {elem.getElementName(): {'Interval': {'Ignore': 'full'}}}, indent=2)
                  ), file=sys.stderr)
          lastFullTime = elemTime
          lastFullElementName = elem.getElementName()
        else:
# This is an incremental backup, so incremental interval policy
# has to be defined.
          if currentPolicy.timeIncMin is None:
            raise Exception('Not expecting incremental backups')

# Always perform incremental checks if there is a policy for
# it.
        if (currentPolicy.timeIncMin is not None) and \
            (ignoreType not in ('both', 'inc')):
          incDelta = elemTime - lastIncTime
# As full backup scheduling overrides the lower priority incremental
# schedule, that may have triggered a full backup while no incremental
# would have been required yet.
          if (incDelta < currentPolicy.timeIncMin) and \
              (elem.getType() != 'full') and (not fullValidationOkFlag):
            print(
                'Backup source %s emitting inc backups ' \
                'faster than expected between "%s" and "%s".' % (
                    sourceStatus.getSourceName(),
                    lastElement.getElementName(),
                    elem.getElementName()), file=sys.stderr)
          elif incDelta > currentPolicy.timeIncMax:
            print(
                'Backup source "%s" inc interval too big ' \
                'between "%s" and "%s".' % (
                    sourceStatus.getSourceName(),
                    lastElement.getElementName(),
                    elem.getElementName()), file=sys.stderr)
            print(
                'No interactive/automatic policy or ' \
                'status update, consider adding this ' \
                'manually to the status in %s:\n%s' % (
                    sourceStatus.getStorageStatus().getStatusFileName(),
                    json.dumps(
                        {elem.getElementName(): {'Interval': {'Ignore': 'inc'}}}, indent=2)
                ), file=sys.stderr)

      lastElement = elem
      lastIncTime = elemTime

  def delete(self, sourceStatus):
    """Prepare the policy status data for deletions going to
    happen later on."""
    elementList = sourceStatus.getDataElementList()

    lastElement = None
    lastFullTime = None
    lastIncTime = None

# Keep also track of the last persistent and the current policy.
# When deleting an element with policy updates then move the
# current policy data to the first element not deleted.
    persistentPolicyConfig = currentPolicyConfig = self.config

    for elem in elementList:
      policyData = elem.getPolicyData(PolicyTypeInterval.POLICY_NAME)
      if policyData is not None:
        if 'LastFull' in policyData:
          lastFullTime = policyData['LastFull']
          lastIncTime = policyData['LastInc']
        if 'Config' in policyData:
          currentPolicyConfig = policyData['Config']
          if not elem.isMarkedForDeletion():
            persistentPolicyConfig = currentPolicyConfig

      elemTime = elem.getDatetimeSeconds()
      if lastFullTime is None:
# This is the first element.
        lastFullTime = lastIncTime = elemTime
      else:
        if (lastElement is not None) and \
            (lastElement.isMarkedForDeletion()) and \
            (not elem.isMarkedForDeletion()):
# So the previous element is to be deleted but this not. Make
# sure last timings are kept in policy data.
          if policyData is None:
            policyData = {}
            elem.setPolicyData(PolicyTypeInterval.POLICY_NAME, policyData)
          policyData['LastFull'] = lastFullTime
          policyData['LastInc'] = lastIncTime
# Also copy policy configuration if the element defining the
# current policy was not persisted.
          if persistentPolicyConfig != currentPolicyConfig:
            policyData['Config'] = currentPolicyConfig
            persistentPolicyConfig = currentPolicyConfig

        if elem.getType() == 'full':
          lastFullTime = elemTime
      lastElement = elem
      lastIncTime = elemTime
