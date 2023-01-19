"""This module provides support for the backup size checking
policy."""

import json
import sys

import guerillabackup.storagetool.Policy

class PolicyTypeSize(guerillabackup.storagetool.Policy.Policy):
  """This policy type defines a policy checking file sizes of
  full and incremental backups.

  Applying the policies will also use and modify following backup
  data element status information fields:
  * FullSizeExpect: The expected size of full backups in bytes.
  * FullSizeMax: The maximum size of backups still accepted as
    normal.
  * FullSizeMin: The minimum size of backups still accepted as
    normal.
  * IncSizeExpect: The expected size of incremental backups in
    bytes."""

  POLICY_NAME = 'Size'

  def __init__(self, policyConfig):
    """Instantiate this policy object from a JSON policy configuration
    definition."""
    super().__init__(policyConfig)
    self.config = {}
    self.fullSizeExpect = None
    self.fullSizeMax = None
    self.fullSizeMaxRel = None
    self.fullSizeMin = None
    self.fullSizeMinRel = None

    self.incSizeExpect = None
    self.incSizeExpectRel = None
    self.incSizeMax = None
    self.incSizeMaxRel = None
    self.incSizeMin = None
    self.incSizeMinRel = None

    for configKey, configValue in policyConfig.items():
      if configKey in ('Name', 'Priority'):
        continue
      if configKey in ('FullSizeExpect', 'FullSizeMax',
          'FullSizeMin', 'IncSizeExpect', 'IncSizeMax', 'IncSizeMin'):
        if not isinstance(configValue, int):
          raise Exception(
              'Policy setting "%s" has to be a integer' % configKey)
        if configKey == 'FullSizeExpect':
          self.fullSizeExpect = configValue
        elif configKey == 'FullSizeMax':
          self.fullSizeMax = configValue
        elif configKey == 'FullSizeMin':
          self.fullSizeMin = configValue
        elif configKey == 'IncSizeExpect':
          self.incSizeExpect = configValue
        elif configKey == 'IncSizeMax':
          self.incSizeMax = configValue
        elif configKey == 'IncSizeMin':
          self.incSizeMin = configValue
      elif configKey in ('FullSizeMaxRel', 'FullSizeMinRel',
          'IncSizeExpectRel', 'IncSizeMaxRel', 'IncSizeMinRel'):
        if not isinstance(configValue, float):
          raise Exception(
              'Policy setting "%s" has to be a float' % configKey)
        if configKey == 'FullSizeMaxRel':
          self.fullSizeMaxRel = configValue
        elif configKey == 'FullSizeMinRel':
          self.fullSizeMinRel = configValue
        elif configKey == 'IncSizeExpectRel':
          self.incSizeExpectRel = configValue
        elif configKey == 'IncSizeMaxRel':
          self.incSizeMaxRel = configValue
        elif configKey == 'IncSizeMinRel':
          self.incSizeMinRel = configValue
      else:
        raise Exception('Unknown policy configuration setting "%s"' % configKey)
      self.config[configKey] = configValue

# Validate the configuration settings. Relative and absolute
# settings may not be set or unset at the same time.
    if (self.fullSizeMax is not None) == (self.fullSizeMaxRel is not None):
      raise Exception()
    if (self.fullSizeMin is not None) == (self.fullSizeMinRel is not None):
      raise Exception()
# Incremental settings might be missing when there are no incremental
# backups expected.
    if (self.incSizeMax is not None) and (self.incSizeMaxRel is not None):
      raise Exception()
    if (self.incSizeMin is not None) and (self.incSizeMinRel is not None):
      raise Exception()

    if self.fullSizeExpect is not None:
      if self.fullSizeMaxRel is not None:
        self.fullSizeMax = int(self.fullSizeMaxRel * self.fullSizeExpect)
      if self.fullSizeMinRel is not None:
        self.fullSizeMin = int(self.fullSizeMinRel * self.fullSizeExpect)
      if self.incSizeExpectRel is not None:
        self.incSizeExpect = int(self.incSizeExpectRel * self.fullSizeExpect)

    if self.incSizeExpect is not None:
      if self.incSizeMaxRel is not None:
        self.incSizeMax = int(self.incSizeMaxRel * self.incSizeExpect)
      if self.incSizeMinRel is not None:
        self.incSizeMin = int(self.incSizeMinRel * self.incSizeExpect)


  def apply(self, sourceStatus):
    """Apply this policy to a backup source status."""
    elementList = sourceStatus.getDataElementList()
    currentPolicy = self

    for elem in elementList:
# This is a new policy configuration created while checking this
# element. It has to be persisted before checking the next element.
      newConfig = None
      policyData = elem.getPolicyData(PolicyTypeSize.POLICY_NAME)
      ignoreFlag = False
      if policyData is not None:
        for key in policyData.keys():
          if key not in ('Config', 'Ignore'):
            raise Exception(
                'Policy status configuration for "%s" in ' \
                '"%s" corrupted: %s' % (
                    elem.getElementName(),
                    sourceStatus.getStorageStatus().getStatusFileName(),
                    repr(policyData)))
        if 'Config' in policyData:
# Use the additional policy data.
          initConfig = dict(policyData['Config'])
          initConfig['Name'] = PolicyTypeSize.POLICY_NAME
          currentPolicy = PolicyTypeSize(initConfig)
        ignoreFlag = policyData.get('Ignore', False)
        if not isinstance(ignoreFlag, bool):
          raise Exception(
              'Policy status configuration for "%s" in ' \
              '"%s" corrupted, "Ignore" parameter has to ' \
              'be boolean: %s' % (
                  elem.getElementName(),
                  sourceStatus.getStorageStatus().getStatusFileName(),
                  repr(policyData)))

      if elem.getType() == 'full':
# First see if the current policy has already an expected
# full backup size. If not use the current size.
        if currentPolicy.fullSizeExpect is None:
          newConfig = dict(currentPolicy.config)
          newConfig['FullSizeExpect'] = elem.getDataLength()
          newConfig['Name'] = PolicyTypeSize.POLICY_NAME
          currentPolicy = PolicyTypeSize(newConfig)
        elif ((elem.getDataLength() < currentPolicy.fullSizeMin) or \
            (elem.getDataLength() > currentPolicy.fullSizeMax)) and \
            (not ignoreFlag):
          print(
              'Full backup size %s in source %s out of ' \
              'limits, should be %d <= %d <= %d.' % (
                  elem.getElementName(),
                  sourceStatus.getSourceName(),
                  currentPolicy.fullSizeMin,
                  elem.getDataLength(),
                  currentPolicy.fullSizeMax), file=sys.stderr)
          print(
              'No interactive/automatic policy or ' \
              'status update, consider adding this ' \
              'manually to the status in %s:\n%s' % (
                  sourceStatus.getStorageStatus().getStatusFileName(),
                  json.dumps(
                      {elem.getElementName(): {'Size': {'Ignore': True}}}, indent=2)
              ), file=sys.stderr)
      else:
# This is an incremental backup, so incremental interval policy
# has to be defined.
        if currentPolicy.incSizeExpect is None:
          if currentPolicy.incSizeExpectRel is not None:
# There was no full backup seen before any incremental one.
            raise Exception(
                'Not expecting incremental backups before full ones')
          newConfig = dict(currentPolicy.config)
          newConfig['IncSizeExpect'] = elem.getDataLength()
          newConfig['Name'] = PolicyTypeSize.POLICY_NAME
          currentPolicy = PolicyTypeSize(newConfig)
        if (currentPolicy.incSizeMin is None) or \
            (currentPolicy.incSizeMax is None):
          raise Exception(
              'Incremental backups from source "%s" in ' \
              'config "%s" found but no Size policy ' \
              'for incremental data defined' % (
                  sourceStatus.getSourceName(),
                  sourceStatus.getStorageStatus().getConfig().getConfigFileName()))
        if ((elem.getDataLength() < currentPolicy.incSizeMin) or \
            (elem.getDataLength() > currentPolicy.incSizeMax)) and \
            (not ignoreFlag):
          print(
              'Incremental backup size %s in source %s out of ' \
              'limits, should be %d <= %d <= %d.' % (
                  elem.getElementName(),
                  sourceStatus.getSourceName(),
                  currentPolicy.incSizeMin,
                  elem.getDataLength(),
                  currentPolicy.incSizeMax), file=sys.stderr)
          print(
              'No interactive/automatic policy or ' \
              'status update, consider adding this ' \
              'manually to the status in %s:\n%s' % (
                  sourceStatus.getStorageStatus().getStatusFileName(),
                  json.dumps(
                      {elem.getElementName(): {'Size': {'Ignore': True}}}, indent=2)
              ), file=sys.stderr)
      if newConfig is not None:
        if policyData is None:
          policyData = {}
          elem.setPolicyData(PolicyTypeSize.POLICY_NAME, policyData)
        policyData['Config'] = newConfig


  def delete(self, sourceStatus):
    """Prepare the policy status data for deletions going to
    happen later on."""
    elementList = sourceStatus.getDataElementList()

# Keep also track of the last persistent and the current policy.
# When deleting an element with policy updates then move the
# current policy data to the first element not deleted.
    persistentPolicyConfig = currentPolicyConfig = self.config

    for elem in elementList:
      policyData = elem.getPolicyData(PolicyTypeSize.POLICY_NAME)
      if (policyData is not None) and ('Config' in policyData):
        currentPolicyConfig = policyData['Config']
        if not elem.isMarkedForDeletion():
          persistentPolicyConfig = currentPolicyConfig

      if not elem.isMarkedForDeletion():
        if persistentPolicyConfig != currentPolicyConfig:
          if policyData is None:
            policyData = {}
            elem.setPolicyData(PolicyTypeSize.POLICY_NAME, policyData)
          policyData['Config'] = currentPolicyConfig
          persistentPolicyConfig = currentPolicyConfig
