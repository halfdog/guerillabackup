"""This module provides a default file storage that allows storage
of new element using the sink interface. The storage used 3 files,
the main data file, an info file holding the meta information
and a lock file to allow race-free operation when multiple processes
use the same storage directory."""

import errno
import os
import stat

import guerillabackup
from guerillabackup.BackupElementMetainfo import BackupElementMetainfo

class DefaultFileStorage(
    guerillabackup.DefaultFileSystemSink, guerillabackup.StorageInterface):
  """This is the interface of all stores for backup data elements
  providing access to content data and metainfo but also additional
  storage attributes. The main difference to a generator unit
  is, that data is just retrieved but not generated on invocation."""

  def __init__(self, storageDirName, configContext):
    """Initialize this store with parameters from the given configuration
    context."""
    self.storageDirName = None
    self.openStorageDir(storageDirName, configContext)

  def getBackupDataElement(self, elementId):
    """Retrieve a single stored backup data element from the storage.
    @throws Exception when an incompatible query, update or read
    is in progress."""
    return FileStorageBackupDataElement(self.storageDirFd, elementId)

  def getBackupDataElementForMetaData(self, sourceUrl, metaData):
    """Retrieve a single stored backup data element from the storage.
    @param sourceUrl the URL identifying the source that produced
    the stored data elements.
    @param metaData metaData dictionary for the element of interest.
    @throws Exception when an incompatible query, update or read
    is in progress.
    @return the element or None if no matching element was found."""
# At first get an iterator over all elements in file system that
# might match the given query.
    guerillabackup.assertSourceUrlSpecificationConforming(sourceUrl)
    elementIdParts = \
        guerillabackup.DefaultFileSystemSink.internalGetElementIdParts(
            sourceUrl, metaData)
# Now search the directory for all files conforming to the specifiction.
# As there may exist multiple files with the same time stamp and
# type, load also the meta data and check if matches the query.
    elementDirFd = None
    if len(elementIdParts[0]) == 0:
      elementDirFd = os.dup(self.storageDirFd)
    else:
      try:
        elementDirFd = guerillabackup.secureOpenAt(
            self.storageDirFd, elementIdParts[0][1:], symlinksAllowedFlag=False,
            dirOpenFlags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOCTTY,
            dirCreateMode=0o700,
            fileOpenFlags=os.O_DIRECTORY|os.O_RDONLY|os.O_NOFOLLOW|os.O_CREAT|os.O_EXCL|os.O_NOCTTY)
      except OSError as dirOpenError:
# Directory does not exist, so there cannot be any valid element.
        if dirOpenError.errno == errno.ENOENT:
          return None
        raise
    searchPrefix = elementIdParts[2]
    searchSuffix = '-%s-%s.data' % (elementIdParts[1], elementIdParts[3])
    result = None
    try:
      fileList = guerillabackup.listDirAt(elementDirFd)
      for fileName in fileList:
        if ((not fileName.startswith(searchPrefix)) or
            (not fileName.endswith(searchSuffix))):
          continue
# Just verify, that the serial part is really an integer but no
# need to handle the exception. This would indicate storage corruption,
# so we need to stop anyway.
        serialStr = fileName[len(searchPrefix):-len(searchSuffix)]
        if serialStr != '':
          int(serialStr)
# So file might match, load the meta data.
        metaDataFd = -1
        fileMetaInfo = None
        try:
          metaDataFd = guerillabackup.secureOpenAt(
              elementDirFd, './%s.info' % fileName[:-5],
              symlinksAllowedFlag=False,
              dirOpenFlags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOCTTY,
              dirCreateMode=None,
              fileOpenFlags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NOCTTY)
          metaInfoData = guerillabackup.readFully(metaDataFd)
          fileMetaInfo = BackupElementMetainfo.unserialize(metaInfoData)
        finally:
          if metaDataFd >= 0:
            os.close(metaDataFd)
        if fileMetaInfo.get('DataUuid') != metaData.get('DataUuid'):
          continue
        elementId = '%s/%s' % (elementIdParts[0], fileName[:-5])
        result = FileStorageBackupDataElement(self.storageDirFd, elementId)
        break

    finally:
      os.close(elementDirFd)
    return result

  def queryBackupDataElements(self, query):
    """Query this storage.
    @param query if None, return an iterator over all stored elements.
    Otherwise query has to be a function returning True or False
    for StorageBackupDataElementInterface elements.
    @return BackupDataElementQueryResult iterator for this query.
    @throws Exception if there are any open queries or updates
    preventing response."""
    return FileBackupDataElementQueryResult(self.storageDirFd, query)


class FileStorageBackupDataElement(
    guerillabackup.StorageBackupDataElementInterface):
  """This class implements a file based backup data element."""
  def __init__(self, storageDirFd, elementId):
    """Create a file based backup data element and make sure the
    storage files are at least accessible without reading or validating
    the content."""
# Extract the source URL from the elementId.
    fileNameSepPos = elementId.rfind('/')
    if (fileNameSepPos < 0) or (elementId[0] != '/'):
      raise Exception('Invalid elementId without a separator')
    lastNameStart = elementId.find('-', fileNameSepPos)
    lastNameEnd = elementId.rfind('-')
    if ((lastNameStart < 0) or (lastNameEnd < 0) or
        (lastNameStart+1 >= lastNameEnd)):
      raise Exception('Malformed last name in elementId')
    self.sourceUrl = elementId[:fileNameSepPos+1]+elementId[lastNameStart+1:lastNameEnd]
    guerillabackup.assertSourceUrlSpecificationConforming(self.sourceUrl)
# Now try to create the StorageBackupDataElementInterface element.
    self.storageDirFd = storageDirFd
# Just stat the data and info file, that are mandatory.
    os.stat('.'+elementId+'.data', dir_fd=self.storageDirFd)
    os.stat('.'+elementId+'.info', dir_fd=self.storageDirFd)
    self.elementId = elementId
# Cache the metainfo once loaded.
    self.metaInfo = None

  def getElementId(self):
    """Get the storage element ID of this data element."""
    return self.elementId

  def getSourceUrl(self):
    """Get the source URL of the storage element."""
    return self.sourceUrl

  def getMetaData(self):
    """Get only the metadata part of this element.
    @return a BackupElementMetainfo object"""
    if self.metaInfo != None:
      return self.metaInfo
    metaInfoData = b''
    metaDataFd = -1
    try:
      metaDataFd = self.openElementFile('info')
      metaInfoData = guerillabackup.readFully(metaDataFd)
      self.metaInfo = BackupElementMetainfo.unserialize(metaInfoData)
    finally:
      if metaDataFd >= 0:
        os.close(metaDataFd)
    return self.metaInfo

  def getDataStream(self):
    """Get a stream to read data from that element.
    @return a file descriptor for reading this stream."""
    dataFd = self.openElementFile('data')
    return dataFd

  def assertExtraDataName(self, name):
    """Make sure that file extension is a known one."""
    if ((name in ['', 'data', 'info', 'lock']) or (name.find('/') >= 0) or
        (name.find('-') >= 0) or (name.find('.') >= 0)):
      raise Exception('Invalid extra data name')

  def setExtraData(self, name, value):
    """Attach or detach extra data to this storage element. This
    function is intended for agents to use the storage to persist
    this specific data also.
    @param value the extra data content or None to remove the
    element."""
    self.assertExtraDataName(name)
    valueFileName = '.'+self.elementId+'.'+name
    if value is None:
      try:
        os.unlink(valueFileName, dir_fd=self.storageDirFd)
      except OSError as unlinkError:
        if unlinkError.errno != errno.ENOENT:
          raise
      return
# . and - are forbidden in name, so such a temporary file should
# be colissionfree.
    temporaryExtraDataFileName = '.%s.%s-%d' % (
        self.elementId, name, os.getpid())
    extraDataFd = backup.secureOpenAt(
        self.storageDirFd, temporaryExtraDataFileName,
        symlinksAllowedFlag=False,
        dirOpenFlags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOCTTY,
        dirCreateMode=None,
        fileOpenFlags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_TRUNC|os.O_NOFOLLOW|os.O_NOCTTY)
    try:
      os.write(extraDataFd, value)
      os.close(extraDataFd)
      extraDataFd = -1
      extraDataFileName = '.%s.%s' % (self.elementId, name)
      try:
        os.unlink(extraDataFileName, dir_fd=self.storageDirFd)
      except OSError as unlinkError:
        if unlinkError.errno != errno.ENOENT:
          raise
      os.link(
          temporaryExtraDataFileName, extraDataFileName,
          src_dir_fd=self.storageDirFd, dst_dir_fd=self.storageDirFd,
          follow_symlinks=False)
# Do not let "finally" do the cleanup to on late failures to avoid
# deletion of both versions.
      os.unlink(temporaryExtraDataFileName, dir_fd=self.storageDirFd)
    finally:
      if extraDataFd >= 0:
        os.close(extraDataFd)
        os.unlink(temporaryExtraDataFileName, dir_fd=self.storageDirFd)


  def getExtraData(self, name):
    """@return None when no extra data was found, the content
    otherwise"""
    self.assertExtraDataName(name)
    value = None
    extraDataFd = -1
    try:
      extraDataFd = self.openElementFile(name)
      value = guerillabackup.readFully(extraDataFd)
    except OSError as readError:
      if readError.errno != errno.ENOENT:
        raise
    finally:
      os.close(extraDataFd)
    return value

  def delete(self):
    """Delete this data element. This will remove all files for
    this element. The resource should be locked by the process
    attempting removal if concurrent access is possible."""
    lastFileSepPos = self.elementId.rfind('/')
    dirFd = guerillabackup.secureOpenAt(
        self.storageDirFd, '.'+self.elementId[:lastFileSepPos],
        symlinksAllowedFlag=False,
        dirOpenFlags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOCTTY,
        dirCreateMode=None,
        fileOpenFlags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOCTTY)
    try:
      fileNamePrefix = self.elementId[lastFileSepPos+1:]
      for fileName in guerillabackup.listDirAt(dirFd):
        if fileName.startswith(fileNamePrefix):
          os.unlink(fileName, dir_fd=dirFd)
    finally:
      os.close(dirFd)

  def lock(self):
    """Lock this backup data element.
    @throws Exception if the element does not exist any more or
    cannot be locked"""
    lockFd = self.openElementFile(
        'lock',
        fileOpenFlags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_NOCTTY)
    os.close(lockFd)

  def unlock(self):
    """Unlock this backup data element."""
    os.unlink('.'+self.elementId+'.lock', dir_fd=self.storageDirFd)

  def openElementFile(self, name, fileOpenFlags=None):
    """Open the element file with given name.
    @param fileOpenFlags when None, open the file readonly without
    creating it.
    @return the file descriptor to the new file."""
    if fileOpenFlags is None:
      fileOpenFlags = os.O_RDONLY|os.O_NOFOLLOW|os.O_NOCTTY
    valueFileName = '.'+self.elementId+'.'+name
    elementFd = guerillabackup.secureOpenAt(
        self.storageDirFd, valueFileName, symlinksAllowedFlag=False,
        dirOpenFlags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOCTTY,
        dirCreateMode=None,
        fileOpenFlags=fileOpenFlags)
    return elementFd


class FileBackupDataElementQueryResult(guerillabackup.BackupDataElementQueryResult):
  """This class provides results from querying a file based backup
  data element storage."""
  def __init__(self, storageDirFd, queryFunction):
    self.queryFunction = queryFunction
    self.storageDirFd = storageDirFd
# Create a stack with files and directory resources not listed yet.
# Each entry is a tuple with the file name prefix and the list
# of files.
    self.dirStack = [('.', ['.'])]

  def getNextElement(self):
    """Get the next backup data element from this query iterator.
    @return a StorageBackupDataElementInterface object."""
    while len(self.dirStack) != 0:
      lastDirStackElement = self.dirStack[-1]
      if len(lastDirStackElement[1]) == 0:
        del self.dirStack[-1]
        continue
# Check the type of the first element included in the list.
      testName = lastDirStackElement[1][0]
      del lastDirStackElement[1][0]
      testPath = lastDirStackElement[0]+'/'+testName
      if lastDirStackElement[0] == '.':
        testPath = testName
# Stat without following links.
      statData = os.stat(testPath, dir_fd=self.storageDirFd)
      if stat.S_ISDIR(statData.st_mode):
# Add an additional level of to the stack.
        fileList = guerillabackup.listDirAt(self.storageDirFd, testPath)
        if len(fileList) != 0:
          self.dirStack.append((testPath, fileList))
        continue
      if not stat.S_ISREG(statData.st_mode):
        raise Exception('Found unexpected storage data elements ' \
            'with stat data 0x%x' % statData.st_mode)
# So this is a normal file. Find the common prefix and remove
# all other files belonging to the same element from the list.
      testNamePrefixPos = testName.rfind('.')
      if testNamePrefixPos < 0:
        raise Exception('Malformed element name %s' % repr(testPath))
      testNamePrefix = testName[:testNamePrefixPos+1]
      for testPos in range(len(lastDirStackElement[1])-1, -1, -1):
        if lastDirStackElement[1][testPos].startswith(testNamePrefix):
          del lastDirStackElement[1][testPos]
# Create the element anyway, it is needed for the query.
      elementId = '/'
      if lastDirStackElement[0] != '.':
        elementId += lastDirStackElement[0]+'/'
      elementId += testNamePrefix[:-1]
      dataElement = FileStorageBackupDataElement(self.storageDirFd, elementId)
      if (self.queryFunction != None) and (not self.queryFunction(dataElement)):
        continue
      return dataElement
    return None
