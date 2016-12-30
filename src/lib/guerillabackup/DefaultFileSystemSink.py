"""This module defines the classes for writing backup data elements
to the file system."""

import datetime
import errno
import guerillabackup
import hashlib
import os
import random

class DefaultFileSystemSink(guerillabackup.SinkInterface):
  """This class defines a sink to store backup data elements to
  the filesystem. In test mode it will unlink the data file during
  close and report an error."""
  SINK_BASEDIR_KEY = 'DefaultFileSystemSinkBaseDir'
  def __init__(self, configContext):
    self.testModeFlag = False
    storageDirName = configContext.get(
        DefaultFileSystemSink.SINK_BASEDIR_KEY, None)
    if storageDirName == None:
      raise Exception('Mandatory sink configuration parameter %s missing' % DefaultFileSystemSink.SINK_BASEDIR_KEY)
    self.storageDirName = None
    self.storageDirFd = -1
    self.openStorageDir(storageDirName, configContext)

  def openStorageDir(self, storageDirName, configContext):
    """Open the storage behind the sink. This method may only
    be called once."""
    if self.storageDirName != None:
      raise Exception('Already defined')
    self.storageDirName = storageDirName
    self.storageDirFd = guerillabackup.secureOpenAt(
        -1, self.storageDirName, symlinksAllowedFlag=False,
        dirOpenFlags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOCTTY,
        dirCreateMode=None,
        fileOpenFlags=os.O_DIRECTORY|os.O_RDONLY|os.O_NOFOLLOW|os.O_NOCTTY,
        fileCreateMode=0700)

    self.testModeFlag = configContext.get(
        guerillabackup.CONFIG_GENERAL_DEBUG_TEST_MODE_KEY, False)
    if not isinstance(self.testModeFlag, bool):
      raise Exception('Configuration parameter %s has to be boolean' % guerillabackup.CONFIG_GENERAL_DEBUG_TEST_MODE_KEY)

  def getSinkHandle(self, sourceUrl):
    """Get a handle to perform transfer of a single backup data
    element to a sink."""
    return DefaultFileSystemSinkHandle(
        self.storageDirFd, self.testModeFlag, sourceUrl)

  @staticmethod
  def internalGetElementIdParts(sourceUrl, metaInfo):
    """Get the parts forming the element ID as tuple. The tuple
    elements are directory part, timestamp string, storage file
    name main part including the backup type. The storage file
    name can be created easily by adding separators, an optional
    serial after the timestamp and the file type suffix.
    @return the tuple with all fields filled when metaInfo is not
    None, otherwise only directory part is filled. The directory
    will be an empty string for top level elements or the absolute
    sourceUrl path up to but excluding the last slash."""
    fileTimestampStr = None
    backupTypeStr = None
    if metaInfo != None:
      fileTimestampStr = datetime.datetime.fromtimestamp(
          metaInfo.get('Timestamp')).strftime('%Y%m%d%H%M%S')
      backupTypeStr = metaInfo.get('BackupType')
    lastPartSplitPos = sourceUrl.rfind('/')
    return((sourceUrl[:lastPartSplitPos], sourceUrl[lastPartSplitPos+1:],
        fileTimestampStr, backupTypeStr))


class DefaultFileSystemSinkHandle(guerillabackup.SinkHandleInterface):
  """This class defines a handle for writing a backup data to
  the file system."""

  def __init__(self, storageDirFd, testModeFlag, sourceUrl):
    """Create a temporary storage file and a handle to it."""
    self.testModeFlag = testModeFlag
    self.sourceUrl = sourceUrl
    guerillabackup.assertSourceUrlSpecificationConforming(sourceUrl)
    self.elementIdParts = DefaultFileSystemSink.internalGetElementIdParts(
        sourceUrl, None)

    self.storageDirFd = None
    if self.elementIdParts[0] == '':
      self.storageDirFd = os.dup(storageDirFd)
    else:
      self.storageDirFd = guerillabackup.secureOpenAt(
          storageDirFd, self.elementIdParts[0][1:], symlinksAllowedFlag=False,
          dirOpenFlags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOCTTY,
          dirCreateMode=0700,
          fileOpenFlags=os.O_DIRECTORY|os.O_RDONLY|os.O_NOFOLLOW|os.O_CREAT|os.O_EXCL|os.O_NOCTTY,
          fileCreateMode=0700)

# Generate a temporary file name in the same directory.
    while True:
      self.tmpFileName = 'tmp-%s-%d' % (self.elementIdParts[1], random.randint(0, 1<<30))
      try:
        self.streamFd = guerillabackup.secureOpenAt(
            self.storageDirFd, self.tmpFileName, symlinksAllowedFlag=False,
            dirOpenFlags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOCTTY,
            dirCreateMode=None,
            fileOpenFlags=os.O_RDWR|os.O_NOFOLLOW|os.O_CREAT|os.O_EXCL|os.O_NOCTTY,
            fileCreateMode=0600)
        break
      except OSError as openError:
        if openError.errno != errno.EEXIST:
          os.close(self.storageDirFd)
          raise

  def getSinkStream(self):
    """Get the file descriptor to write directly to the open backup
    data element at the sink, if available.
    @return the file descriptor or None when not supported."""
    if self.streamFd == None:
      raise Exception('Illegal state, already closed')
    return self.streamFd
  def write(self, data):
    """Write data to the open backup data element at the sink."""
    os.write(self.streamFd, data)
  def close(self, metaInfo):
    """Close the backup data element at the sink and receive any
    pending or current error associated with the writing process.
    When there is sufficient risk, that data written to the sink
    is might have been corrupted during transit or storage, the
    sink may decide to perform a verification operation while
    closing and return any verification errors here also.
    @param metaInfo python objects with additional information
    about this backup data element. This information is added
    at the end of the sink procedure to allow inclusion of checksum
    or signature fields created on the fly while writing. See
    design and implementation documentation for requirements on
    those objects."""
    if self.streamFd == None:
      raise Exception('Illegal state, already closed')
    self.elementIdParts = DefaultFileSystemSink.internalGetElementIdParts(
        self.sourceUrl, metaInfo)

# The file name main part between timestamp (with serial) and
# suffix as string.
    fileNameMainStr = '%s-%s' % (self.elementIdParts[1], self.elementIdParts[3])
    fileChecksum = metaInfo.get('StorageFileChecksumSha512')
    metaInfoStr = metaInfo.serialize()

    try:
      if fileChecksum != None:
# Reread the file and create checksum.
        os.lseek(self.streamFd, os.SEEK_SET, 0)
        digestAlgo = hashlib.sha512()
        while True:
          data = os.read(self.streamFd, 1<<20)
          if len(data) == 0:
            break
          digestAlgo.update(data)
        if fileChecksum != digestAlgo.digest():
          raise Exception('Checksum mismatch')

# Link the name to the final pathname.
      serial = -1
      storageFileName = None
      while True:
        if serial < 0:
          storageFileName = '%s-%s.data' % (self.elementIdParts[2],
              fileNameMainStr)
        else:
          storageFileName = '%s%d-%s.data' % (self.elementIdParts[2],
              serial, fileNameMainStr)
        serial += 1
        try:
          guerillabackup.internalLinkAt(
              self.storageDirFd, self.tmpFileName, self.storageDirFd,
              storageFileName, 0)
          break
        except OSError as linkError:
          if linkError.errno != errno.EEXIST:
            raise

# Now unlink the old file. With malicious actors we cannot be
# sure to unlink the file we have currently opened, but in worst
# case some malicious symlink is removed.
      guerillabackup.internalUnlinkAt(self.storageDirFd, self.tmpFileName, 0)

# Now create the meta-information file. As the data file acted
# as a lock, there is nothing to fail except for severe system
# failure or malicious activity. So do not attempt to correct
# any errors at this stage. Create a temporary version first and
# then link it to have atomic completion operation instead of
# risk, that another system could pick up the incomplete info
# file.
      metaInfoFileName = storageFileName[:-4]+'info'
      metaInfoFd = guerillabackup.secureOpenAt(
          self.storageDirFd, metaInfoFileName+'.tmp',
          symlinksAllowedFlag=False,
          dirOpenFlags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOCTTY,
          dirCreateMode=None,
          fileOpenFlags=os.O_RDWR|os.O_NOFOLLOW|os.O_CREAT|os.O_EXCL|os.O_NOCTTY,
          fileCreateMode=0600)
      os.write(metaInfoFd, metaInfoStr)
      os.close(metaInfoFd)
      if self.testModeFlag:
# Unlink all artefacts when operating in test mode to avoid accidential
        guerillabackup.internalUnlinkAt(self.storageDirFd, storageFileName, 0)
        guerillabackup.internalUnlinkAt(
            self.storageDirFd, metaInfoFileName+'.tmp', 0)
        raise Exception('No storage in test mode')
      guerillabackup.internalLinkAt(
          self.storageDirFd, metaInfoFileName+'.tmp', self.storageDirFd,
          metaInfoFileName, 0)
      guerillabackup.internalUnlinkAt(
          self.storageDirFd, metaInfoFileName+'.tmp', 0)
    finally:
      os.close(self.storageDirFd)
      self.storageDirFd = None
      os.close(self.streamFd)
      self.streamFd = None
