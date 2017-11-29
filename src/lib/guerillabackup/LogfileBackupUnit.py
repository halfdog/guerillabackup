"""This module provides all classes required for logfile backup."""

import base64
import errno
import hashlib
import json
import os
import re
import sys
import time
import traceback

import guerillabackup
from guerillabackup.BackupElementMetainfo import BackupElementMetainfo
from guerillabackup.TransformationProcessOutputStream import TransformationProcessOutputStream

# This is the key to the list of source files to include using
# a LogfileBackupUnit. The list is extracted from the configContext
# at invocation time of a backup unit, not at creation time. The
# structure of the parameter content is a list of source description
# entries. Each entry in the list is used to create an input description
# object of class LogfileBackupUnitInputDescription.
CONFIG_INPUT_LIST_KEY = 'LogBackupUnitInputList'

class LogfileBackupUnitInputDescription():
  """This class stores information about one set of logfiles to
  be processed."""

  def __init__(self, descriptionTuple):
    """Initialize a single input description using a 5-value tuple,
    e.g. extracted directly from the CONFIG_INPUT_LIST_KEY parameter.
    @param descriptionTuple the tuple, the meaning of the 5 values
    to be extracted is:
    * Input directory: directory to search for logfiles
    * Input file regex: regular expression to select compressed
      or uncompressed logfiles for inclusion.
    * Source URL transformation: If None, the first named group
      of the "input file regex" is used as source URL. When not
      starting with a "/", the transformation string is the name
      to include literally in the URL after the "input directory"
      name.
    * Policy: If not none, include this string as handling policy
      within the manifest.
    * Encryption key name: If not None, encrypt the input using
      the named key."""

# Accept list also.
    if ((not isinstance(descriptionTuple, tuple)) and
        (not isinstance(descriptionTuple, list))):
      raise Exception('Input description has to be list or tuple')
    if len(descriptionTuple) != 5:
      raise Exception('Input description has to be tuple with 5 elements')
    self.inputDirectoryName = os.path.normpath(descriptionTuple[0])
# "//..." is a normalized path, get rid of double slashes.
    self.sourceUrlPath = self.inputDirectoryName.replace('//', '/')
    if self.sourceUrlPath[-1] != '/':
      self.sourceUrlPath += '/'
    self.inputFileRegex = re.compile(descriptionTuple[1])
    self.sourceTransformationPattern = descriptionTuple[2]
    try:
      if self.sourceTransformationPattern is None:
        guerillabackup.assertSourceUrlSpecificationConforming(
            self.sourceUrlPath+'testname')
      elif self.sourceTransformationPattern[0] != '/':
        guerillabackup.assertSourceUrlSpecificationConforming(
            self.sourceUrlPath+self.sourceTransformationPattern)
      else:
        guerillabackup.assertSourceUrlSpecificationConforming(
            self.sourceTransformationPattern)
    except Exception as assertException:
      raise Exception('Source URL transformation malformed: '+assertException.args[0])

    self.handlingPolicyName = descriptionTuple[3]
    self.encryptionKeyName = descriptionTuple[4]

  def getTransformedSourceName(self, matcher):
    """Get the source name for logfiles matching the input description."""
    if self.sourceTransformationPattern is None:
      return self.sourceUrlPath+matcher.group(1)
    if self.sourceTransformationPattern[0] != '/':
      return self.sourceUrlPath+self.sourceTransformationPattern
    return self.sourceTransformationPattern

def tryIntConvert(value):
  """Try to convert a value to an integer for sorting. When conversion
  fails, the value itself returned, thus sorting will be performed
  lexigraphically afterwards."""
  try:
    return int(value)
  except:
    return value


class LogfileSourceInfo():
  """This class provides support to collect logfiles from one
  LogfileBackupUnitInputDescription that all map to the same source
  URL. This is needed to process all of them in the correct order,
  starting with the oldest one."""

  def __init__(self, sourceUrl):
    self.sourceUrl = sourceUrl
    self.serialTypesConsistentFlag = True
    self.serialType = None
    self.fileList = []

  def addFile(self, fileName, matcher):
    """Add a logfile that will be mapped to the source URL of
    this group."""
    groupDict = matcher.groupdict()
    serialType = None
    if 'serial' in groupDict:
      serialType = 'serial'
    if 'oldserial' in groupDict:
      if serialType != None:
        self.serialTypesConsistentFlag = False
      else:
        serialType = 'oldserial'

    if self.serialType is None:
      self.serialType = serialType
    elif self.serialType != serialType:
      self.serialTypesConsistentFlag = False

    serialData = []
    if serialType != None:
      serialValue = groupDict[serialType]
      if (serialValue != None) and (len(serialValue) != 0):
        serialData = [tryIntConvert(x) for x in re.findall('(\\d+|\\D+)', serialValue)]
# This is not very efficient but try to detect duplicate serialData
# values here already and tag the whole list as inconsistent.
# This may happen with broken regular expressions or when mixing
# compressed and uncompressed files with same serial.
    for elemFileName, elemMatcher, elemSerialData in self.fileList:
      if elemSerialData == serialData:
        self.serialTypesConsistentFlag = False
    self.fileList.append((fileName, matcher, serialData,))

  def getSortedFileList(self):
    """Get the sorted file list starting with the oldest entry.
    The oldest one should be moved to backup first."""
    if not self.serialTypesConsistentFlag:
      raise Exception('No sorting in inconsistent state')

    fileList = sorted(self.fileList, key=lambda x: x[2])
    if self.serialType is None:
      if len(fileList) > 1:
        raise Exception('No serial type and more than one file')
    elif self.serialType == 'serial':
# Larger serial numbers denote newer files, only elements without
# serial data have to be moved to the end.
      moveCount = 0
      while (moveCount < len(fileList)) and (len(fileList[moveCount][2]) == 0):
        moveCount += 1
      fileList = fileList[moveCount:]+fileList[:moveCount]
    elif self.serialType == 'oldserial':
# Larger serial numbers denote older files. File without serial would
# be first, so just reverse is sufficient.
      fileList.reverse()
    else:
      raise Exception('Unsupported serial type %s' % self.serialType)
    return fileList


class LogfileBackupUnit(guerillabackup.SchedulableGeneratorUnitInterface):
  """This class allows to schedule regular searches in a list
  of log file directories for files matching a pattern. If files
  are found and not open for writing any more, they are processed
  according to specified transformation pipeline and deleted afterwards.
  The unit will keep track of the last UUID reported for each
  resource and generate a new one for each handled file using
  json-serialized state data. The state data is a list with the
  timestamp of the last run as seconds since 1970, the next list
  value contains a dictionary with the resource name for each
  logfile group as key and the last UUID as value."""

  def __init__(self, unitName, configContext):
    """Initialize this unit using the given configuration."""
    self.unitName = unitName
    self.configContext = configContext
# This is the maximum interval in seconds between two invocations.
# When last invocation was more than that number of seconds in
# the past, the unit will attempt invocation at first possible
# moment.
    self.maxInvocationInterval = 3600
# When this value is not zero, the unit will attempt to trigger
# invocation always at the same time using this value as modulus.
    self.moduloInvocationUnit = 3600
# This is the invocation offset when modulus timing is enabled.
    self.moduloInvocationTime = 0
# As immediate invocation cannot be guaranteed, this value defines
# the size of the window, within that the unit should still be
# invoked, even when the targeted time slot has already passed
# by.
    self.moduloInvocationTimeWindow = 10

    self.testModeFlag = configContext.get(
        guerillabackup.CONFIG_GENERAL_DEBUG_TEST_MODE_KEY, False)
    if not isinstance(self.testModeFlag, bool):
      raise Exception('Configuration parameter %s has to be ' \
          'boolean' % guerillabackup.CONFIG_GENERAL_DEBUG_TEST_MODE_KEY)

# Timestamp of last invocation end.
    self.lastInvocationTime = -1
# Map from resource name to UUID of most recent file processed.
# The UUID is kept internally as binary data string. Only for
# persistency, data will be base64 encoded.
    self.resourceUuidMap = {}
    self.persistencyDirFd = guerillabackup.openPersistencyFile(
        configContext, os.path.join('generators', self.unitName),
        os.O_DIRECTORY|os.O_RDONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_NOCTTY, 0o700)

    handle = None
    try:
      handle = guerillabackup.secureOpenAt(
          self.persistencyDirFd, 'state.current',
          fileOpenFlags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NOCTTY)
    except OSError as openError:
      if openError.errno != errno.ENOENT:
        raise
# See if the state.previous file exists, if yes, the unit is likely
# to be broken. Refuse to do anything while in this state.
    try:
      os.stat(
          'state.previous', dir_fd=self.persistencyDirFd, follow_symlinks=False)
      raise Exception('Persistency data inconsistencies: found stale previous state file')
    except OSError as statError:
      if statError.errno != errno.ENOENT:
        raise
# So there is only the current state file, if any.
    stateInfo = None
    if handle != None:
      stateData = b''
      while True:
        data = os.read(handle, 1<<20)
        if len(data) == 0:
          break
        stateData += data
      os.close(handle)
      stateInfo = json.loads(str(stateData, 'ascii'))
      if ((not isinstance(stateInfo, list)) or (len(stateInfo) != 2) or
          (not isinstance(stateInfo[0], int)) or
          (not isinstance(stateInfo[1], dict))):
        raise Exception('Persistency data structure mismatch')
      self.lastInvocationTime = stateInfo[0]
      self.resourceUuidMap = stateInfo[1]
      for url, uuidData in self.resourceUuidMap.items():
        self.resourceUuidMap[url] = base64.b64decode(uuidData)

  def getNextInvocationTime(self):
    """Get the time in seconds until this unit should called again.
    If a unit does not know (yet) as invocation needs depend on
    external events, it should report a reasonable low value to
    be queried again soon.
    @return 0 if the unit should be invoked immediately, the seconds
    to go otherwise."""
    currentTime = int(time.time())
    maxIntervalDelta = self.lastInvocationTime+self.maxInvocationInterval-currentTime
# Already overdue, activate immediately.
    if maxIntervalDelta <= 0:
      return 0
# No modulo time operation, just return the next delta value.
    if self.moduloInvocationUnit == 0:
      return maxIntervalDelta

# See if currentTime is within invocation window
    moduloIntervalDelta = (currentTime%self.moduloInvocationUnit)-self.moduloInvocationTime
    if moduloIntervalDelta < 0:
      moduloIntervalDelta += self.moduloInvocationUnit
# See if immediate modulo invocation is possible.
    if moduloIntervalDelta < self.moduloInvocationTimeWindow:
# We could be within the window, but only if last invocation happened
# during the previous modulo unit.
      lastInvocationUnit = (self.lastInvocationTime-self.moduloInvocationTime)/self.moduloInvocationUnit
      currentInvocationUnit = (currentTime-self.moduloInvocationTime)/self.moduloInvocationUnit
      if lastInvocationUnit != currentInvocationUnit:
        return 0
# We are still within the same invocation interval. Fall through
# to the out-of-window case to calculate the next invocation time.
    moduloIntervalDelta = self.moduloInvocationUnit-moduloIntervalDelta
    return min(maxIntervalDelta, moduloIntervalDelta)


  def processInput(self, unitInput, sink):
    """Process a single input description by searching for files
    that could be written to the sink."""
    inputDirectoryFd = None
    getFileOpenerInformationErrorMode = guerillabackup.OPENER_INFO_FAIL_ON_ERROR
    if os.geteuid() != 0:
      getFileOpenerInformationErrorMode = guerillabackup.OPENER_INFO_IGNORE_ACCESS_ERRORS
    try:
      inputDirectoryFd = guerillabackup.secureOpenAt(
          None, unitInput.inputDirectoryName,
          fileOpenFlags=os.O_DIRECTORY|os.O_RDONLY|os.O_NOFOLLOW|os.O_NOCTTY)

      sourceDict = {}
      for fileName in guerillabackup.listDirAt(inputDirectoryFd):
        matcher = unitInput.inputFileRegex.match(fileName)
        if matcher is None:
          continue
        sourceUrl = unitInput.getTransformedSourceName(matcher)
        sourceInfo = sourceDict.get(sourceUrl, None)
        if sourceInfo is None:
          sourceInfo = LogfileSourceInfo(sourceUrl)
          sourceDict[sourceUrl] = sourceInfo
        sourceInfo.addFile(fileName, matcher)

# Now we know all files to be included for each URL. Sort them
# to fulfill Req:OrderedProcessing and start with the oldest.
      for sourceUrl, sourceInfo in sourceDict.items():
        if not sourceInfo.serialTypesConsistentFlag:
          print('Inconsistent serial types in %s, ignoring ' \
              'source.' % sourceInfo.sourceUrl, file=sys.stderr)
          continue

# Get the downstream transformation pipeline elements.
        downstreamPipelineElements = \
            guerillabackup.getDefaultDownstreamPipeline(
                self.configContext, unitInput.encryptionKeyName)
        fileList = sourceInfo.getSortedFileList()
        fileInfoList = guerillabackup.getFileOpenerInformation(
            ['%s/%s' % (unitInput.inputDirectoryName, x[0]) for x in fileList],
            getFileOpenerInformationErrorMode)
        for fileListIndex in range(0, len(fileList)):
          fileName, matcher, serialData = fileList[fileListIndex]
# Make sure, that the file is not written any more.
          logFilePathName = os.path.join(
              unitInput.inputDirectoryName, fileName)
# Build the transformation pipeline instance.
          fileHandle = guerillabackup.secureOpenAt(
              inputDirectoryFd, fileName,
              fileOpenFlags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NOCTTY)
          isOpenForWritingFlag = False
          if fileInfoList[fileListIndex] != None:
            for pid, fdInfoList in fileInfoList[fileListIndex]:
              for fdNum, fdOpenFlags in fdInfoList:
                if fdOpenFlags == 0o100001:
                  print('File %s is still written by pid %d, ' \
                      'fd %d' % (logFilePathName, pid, fdNum), file=sys.stderr)
                  isOpenForWritingFlag = True
                elif fdOpenFlags != 0o100000:
                  print('File %s unknown open flags 0x%x by pid %d, ' \
                      'fd %d' % (
                          logFilePathName, fdOpenFlags, pid, fdNum), file=sys.stderr)
                  isOpenForWritingFlag = True
# Files have to be processed in correct order, so we have to stop
# here.
          if isOpenForWritingFlag:
            break
          completePipleline = downstreamPipelineElements
          compressionType = matcher.groupdict().get('compress', None)
          if compressionType != None:
# Source file is compressed, prepend a suffix/content-specific
# decompression element.
            compressionElement = None
            if compressionType == 'gz':
              compressionElement = guerillabackup.OSProcessPipelineElement(
                  '/bin/gzip', ['/bin/gzip', '-cd'])
            else:
              raise Exception('Unkown compression type %s for file %s/%s' % (
                  compressionType, unitInput.inputDirectoryName, fileName))
            completePipleline = [compressionElement]+completePipleline[:]

          logFileFd = guerillabackup.secureOpenAt(
              inputDirectoryFd, fileName,
              fileOpenFlags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NOCTTY)
          logFileStatData = os.fstat(logFileFd)
          logFileOutput = TransformationProcessOutputStream(logFileFd)

          sinkHandle = sink.getSinkHandle(sourceInfo.sourceUrl)
          sinkStream = sinkHandle.getSinkStream()

# Get the list of started pipeline instances.
          pipelineInstances = guerillabackup.instantiateTransformationPipeline(
              completePipleline, logFileOutput, sinkStream, doStartFlag=True)
          guerillabackup.runTransformationPipeline(pipelineInstances)
          digestData = pipelineInstances[-1].getDigestData()

          metaInfoDict = {}
          metaInfoDict['BackupType'] = 'full'
          if unitInput.handlingPolicyName != None:
            metaInfoDict['HandlingPolicy'] = [unitInput.handlingPolicyName]
          lastUuid = self.resourceUuidMap.get(sourceInfo.sourceUrl, None)
          currentUuidDigest = hashlib.sha512()
          if lastUuid != None:
            metaInfoDict['Predecessor'] = lastUuid
            currentUuidDigest.update(lastUuid)
# Add the compressed file digest. The consequence is, that it
# will not be completely obvious when the same file was processed
# with twice with encryption enabled and processing failed in
# late phase. Therefore identical file content cannot be detected.
          currentUuidDigest.update(digestData)
# Also include the timestamp and original filename of the source
# file in the UUID calculation: Otherwise retransmissions of files
# with identical content cannot be distinguished.
          currentUuidDigest.update(bytes('%d %s' % (
              logFileStatData.st_mtime, fileName), sys.getdefaultencoding()))
          currentUuid = currentUuidDigest.digest()
          metaInfoDict['DataUuid'] = currentUuid
          metaInfoDict['StorageFileChecksumSha512'] = digestData
          metaInfoDict['Timestamp'] = int(logFileStatData.st_mtime)
          os.close(logFileFd)

          metaInfo = BackupElementMetainfo(metaInfoDict)
          sinkHandle.close(metaInfo)
          if self.testModeFlag:
            raise Exception('No completion of logfile backup in test mode')
# Delete the logfile.
          os.unlink(fileName, dir_fd=inputDirectoryFd)

# Update the UUID map as last step: if any of the steps above
# would fail, currentUuid generated in next run will be identical
# to this. Sorting out the duplicates will be easy.
          self.resourceUuidMap[sourceInfo.sourceUrl] = currentUuid
    finally:
      if inputDirectoryFd != None:
        os.close(inputDirectoryFd)

  def invokeUnit(self, sink):
    """Invoke this unit to create backup elements and pass them
    on to the sink. Even when indicated via getNextInvocationTime,
    the unit may decide, that it is not yet ready and not write
    any element to the sink.
    @return None if currently there is nothing to write to the
    source, a number of seconds to retry invocation if the unit
    assumes, that there is data to be processed but processing
    cannot start yet, e.g. due to locks held by other parties
    or resource, e.g. network storages, currently not available."""
    nextInvocationDelta = self.getNextInvocationTime()
    invocationAttemptedFlag = False

    try:
      if nextInvocationDelta == 0:
# We are now ready for processing. Get the list of source directories
# and search patterns to locate the target files.
        unitInputListConfig = self.configContext.get(CONFIG_INPUT_LIST_KEY, None)
        invocationAttemptedFlag = True
        nextInvocationDelta = None

        if unitInputListConfig is None:
          print('Suspected configuration error: LogfileBackupUnit ' \
              'enabled but %s configuration list empty' % CONFIG_INPUT_LIST_KEY,
                file=sys.stderr)
        else:
          for configItem in unitInputListConfig:
            unitInput = None
            try:
              unitInput = LogfileBackupUnitInputDescription(configItem)
            except Exception as configReadException:
              print('LogfileBackupUnit: failed to use configuration ' \
                  '%s: %s' % (
                      repr(configItem), configReadException.args[0]),
                    file=sys.stderr)
              continue
# Configuration parsing worked, start processing the inputs.
            self.processInput(unitInput, sink)
    finally:
      if invocationAttemptedFlag:
        try:
# Update the timestamp.
          self.lastInvocationTime = int(time.time())
# Write back the new state information immediately after invocation
# to avoid data loss when program crashes immediately afterwards.
# Keep one old version of state file.
          try:
            os.unlink('state.old', dir_fd=self.persistencyDirFd)
          except OSError as relinkError:
            if relinkError.errno != errno.ENOENT:
              raise
          try:
            os.link(
                'state.current', 'state.old', src_dir_fd=self.persistencyDirFd,
                dst_dir_fd=self.persistencyDirFd, follow_symlinks=False)
          except OSError as relinkError:
            if relinkError.errno != errno.ENOENT:
              raise
          try:
            os.unlink('state.current', dir_fd=self.persistencyDirFd)
          except OSError as relinkError:
            if relinkError.errno != errno.ENOENT:
              raise
          handle = guerillabackup.secureOpenAt(
              self.persistencyDirFd, 'state.current',
              fileOpenFlags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_NOCTTY,
              fileCreateMode=0o600)
          writeResourceUuidMap = {}
          for url, uuidData in self.resourceUuidMap.items():
            writeResourceUuidMap[url] = str(base64.b64encode(uuidData), 'ascii')
          os.write(
              handle,
              json.dumps([
                  self.lastInvocationTime,
                  writeResourceUuidMap]).encode('ascii'))
          os.close(handle)
        except Exception as stateSaveException:
# Writing of state information failed. Print out the state information
# for manual reconstruction as last resort.
          print('Writing of state information failed: %s\nCurrent ' \
              'state: %s' % (
                  str(stateSaveException),
                  repr([self.lastInvocationTime, self.resourceUuidMap])),
                file=sys.stderr)
          traceback.print_tb(sys.exc_info()[2])
          raise


# Declare the main unit class so that the backup generator can
# instantiate it.
backupGeneratorUnitClass = LogfileBackupUnit
