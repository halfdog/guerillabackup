"""This module contains only the class for in memory storage of
backup data element metadata."""

import base64
import json

class BackupElementMetainfo():
  """This class is used to store backup data element metadata
  in memory."""
  def __init__(self, valueDict=None):
    """Create a a new instance.
    @param if not None, use this dictionary to initialize the
    object. Invocation without a dictionary should only be used
    internally during deserialization."""
    self.valueDict = valueDict
    if valueDict != None:
      self.assertMetaInfoSpecificationConforming()

  def get(self, keyName):
    """Get the value for a given key.
    @return None when no value for the key was found."""
    return self.valueDict.get(keyName, None)

  def serialize(self):
    """Serialize the content of this object.
    @return the ascii-encoded JSON serialization of this object."""
    dumpMetainfo = {}
    for key, value in self.valueDict.items():
      if key in [
          'DataUuid', 'MetaDataSignature', 'Predecessor',
          'StorageFileChecksumSha512', 'StorageFileSignature']:
        if value != None:
          value = str(base64.b64encode(value), 'ascii')
      dumpMetainfo[key] = value
    return json.dumps(dumpMetainfo, sort_keys=True).encode('ascii')

  def assertMetaInfoSpecificationConforming(self):
    """Make sure, that meta information values are conforming
    to the minimal requirements from the specification for the
    in-memory object variant of meta information."""
    timestamp = self.valueDict.get('Timestamp', None)
    if (timestamp is None) or not isinstance(timestamp, int) or (timestamp < 0):
      raise Exception('Timestamp not found or not a positive integer')
    backupType = self.valueDict.get('BackupType', None)
    if backupType not in ['full', 'inc']:
      raise Exception('BackupType missing or invalid')
    checksum = self.valueDict.get('StorageFileChecksumSha512', None)
    if checksum != None:
      if not isinstance(checksum, bytes) or (len(checksum) != 64):
        raise Exception('Invalid checksum type or length')

  @staticmethod
  def unserialize(serializedMetaInfoData):
    """Create a BackupElementMetainfo object from serialized data.
    @param serializedMetaInfoData binary ascii-encoded JSON data"""
    valueDict = json.loads(str(serializedMetaInfoData, 'ascii'))
    for key, value in valueDict.items():
      if key in [
          'DataUuid', 'MetaDataSignature', 'Predecessor',
          'StorageFileChecksumSha512', 'StorageFileSignature']:
        if value != None:
          value = base64.b64decode(value)
        valueDict[key] = value
    metaInfo = BackupElementMetainfo()
    metaInfo.valueDict = valueDict
    metaInfo.assertMetaInfoSpecificationConforming()
    return metaInfo
