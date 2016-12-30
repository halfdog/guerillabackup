"""This unit provides support for full and incremental tar backups.
All tar backups within the same unit are created sequentially,
starting with the one most overdue.

For incremental backups, backup indices are kept in the persistency
storage of this backup unit. Those files might be compressed by
the backup unit and are kept for a limited timespan. An external
process might also remove them without causing damage."""

import base64
import datetime
import errno
import guerillabackup
from guerillabackup.BackupElementMetainfo import BackupElementMetainfo
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback

# This is the key to the list of tar backups to schedule and perform
# using the given unit. Each entry has to be a dictionary containing
# entries to create TarBackupUnitDescription objects. See there
# for more information.
CONFIG_LIST_KEY = 'TarBackupUnitConfigList'


class TarBackupUnitDescription:
  """This class collects all the information about a single tar
  backup to be scheduled by a unit."""
  def __init__(self, sourceUrl, descriptionDict):
    """Initialize a single tar backup description using values
    from a dictionary, e.g. extracted directly from the CONFIG_LIST_KEY
    parameter.
    @param sourceUrl the URL which will identify the backups from
    this subunit. It is used also to store persistency information
    for that unit.
    @param descriptionDict dictionary containing the parameters
    for a single tar backup task.
    * PreBackupCommand: execute this command given as list of
      arguments before starting the backup, e.g. create a filesystem
      or virtual machine snapshot, perform cleanup.
    * PostBackupCommand: execute this command after starting the
      backup.
    * Root: root directory of tar backup, "/" when missing.
    * Include: list of pathes to include, ["."] when missing.
    * Exclude: list of patterns to exclude from backup (see tar
      documentation "--exclude"). When missing and Root is "/",
      list ["./var/lib/guerillabackup/data"] is used.
    * IgnoreBackupRaces: flag to indicate if races during backup
      are acceptable, e.g. because the directories are modified,
      files changed or removed. When set, such races will not
      result in non-zero exit status. Off course, it would be
      more sensible to deploy a snapshot based backup variant
      using the Pre/PostBackupCommand functions.
    * FullBackupTiming: tuple with minimum and maximum interval
      between full backup invocations and modulo base and offset,
      all in seconds. Without modulo invocation (all values None),
      full backups will run as soon as minimum interval is exceeded.
      With modulo timing, modulo trigger is ignored when below
      minimum time. When gap above maximum interval, immediate
      backup is started.
    * IncBackupTiming: When set, incremental backups are created
      to fill the time between full backups. Timings are specified
      as tuple with same meaning as in FullBackupTiming parameter.
      This will also trigger generation of tar file indices when
      running full backups.
    * FullOverrideCommand: when set, parameters Exclude, Include,
      Root are ignored and exactly the given command is executed.
    * IncOverrideCommand: when set, parameters Exclude, Include,
      Root are ignored and exactly the given command is executed.
    * KeepIndices: number of old incremental tar backup indices
      to keep. With -1 keep all, otherwise keep one the given
      number. Default is 0.
    * Policy: If not none, include this string as handling policy
      within the manifest.
    * EncryptionKey: If not None, encrypt the input using the
      named key. Otherwise default encryption key from global
      configuration might be used."""

    if not isinstance(sourceUrl, str):
      raise Exception('Source URL has to be string')
    guerillabackup.assertSourceUrlSpecificationConforming(sourceUrl)
    self.sourceUrl = sourceUrl

    if not isinstance(descriptionDict, dict):
      raise Exception('Input description has to be dictionary')

    self.preBackupCommandList = None
    self.postBackupCommandList = None
    self.backupRoot = None
    self.backupIncludeList = None
    self.backupExcludeList = None
    self.ignoreBackupRacesFlag = False
    self.fullBackupTiming = None
    self.incBackupTiming = None
    self.fullBackupOverrideCommand = None
    self.incBackupOverrideCommand = None
    self.handlingPolicyName = None
    self.encryptionKeyName = None
    self.keepOldIndicesCount = 0

    for configKey, configValue in descriptionDict.iteritems():
      if ((configKey == 'PreBackupCommand') or
          (configKey == 'PostBackupCommand') or
          (configKey == 'FullOverrideCommand') or
          (configKey == 'IncOverrideCommand')):
        if not guerillabackup.isValueListOfType(configValue, str):
          raise Exception('Parameter %s has to be list of string' % configKey)
        if configKey == 'PreBackupCommand':
          self.preBackupCommandList = configValue
        elif configKey == 'PostBackupCommand':
          self.postBackupCommandList = configValue
        elif configKey == 'FullOverrideCommand':
          self.fullBackupOverrideCommand = configValue
        elif configKey == 'IncOverrideCommand':
          self.incBackupOverrideCommand = configValue
        else:
          raise Exception('Logic error')
      elif configKey == 'Root':
        self.backupRoot = configValue
      elif configKey == 'Include':
        self.backupIncludeList = configValue
      elif configKey == 'Exclude':
        self.backupExcludeList = configValue
      elif configKey == 'IgnoreBackupRaces':
        self.ignoreBackupRacesFlag = configValue
      elif ((configKey == 'FullBackupTiming') or
          (configKey == 'IncBackupTiming')):
        if (not isinstance(configValue, list)) or (len(configValue) != 4):
          raise Exception(
              'Parameter %s has to be list with 4 values' % configKey)
        if configValue[0] == None:
          raise Exception('Parameter %s minimum interval value must not be None' % configKey)
        for timeValue in configValue:
          if (timeValue != None) and (not isinstance(timeValue, int)):
            raise Exception(
                'Parameter %s contains non-number element' % configKey)
        if configValue[2] != None:
          if ((configValue[2] <= 0) or (configValue[3] < 0) or
              (configValue[3] >= configValue[2])):
            raise Exception(
                'Parameter %s modulo timing values invalid' % configKey)
        if configKey == 'FullBackupTiming':
          self.fullBackupTiming = configValue
        else: self.incBackupTiming = configValue
      elif configKey == 'KeepIndices':
        if not isinstance(configValue, int):
          raise Exception('KeepIndices has to be integer value')
        self.keepOldIndicesCount = configValue
      elif configKey == 'Policy':
        self.handlingPolicyName = configValue
      elif configKey == 'EncryptionKey':
        self.encryptionKeyName = configValue
      else:
        raise Exception('Unsupported parameter %s' % configKey)

    if self.fullBackupTiming == None:
      raise Exception('Mandatory FullBackupTiming parameter missing')

# The remaining values are not from the unit configuration but
# unit state persistency instead.
    self.lastFullBackupTime = None
    self.lastAnyBackupTime = None
    self.lastUuidValue = None
# When not None, delay execution of any any backup for that resource
# beyond the given time. This is intended for backups that failed
# to run to avoid invocation loops. This value is not persistent
# between multiple software invocations.
    self.nextRetryTime = None

  def getNextInvocationInfo(self, currentTime):
    """Get the next invocation time for this unit description.
    @return a tuple with the the number of seconds till invocation
    or a negative value if invocation is already overdue and the
    type of backup to generate, full or incremental (inc)."""

# See if backup generation is currently blocked.
    if self.nextRetryTime != None:
      if currentTime < self.nextRetryTime:
        return (self.nextRetryTime-currentTime, None)
      self.nextRetryTime = None

    if self.lastFullBackupTime == None:
      return (-self.fullBackupTiming[1], 'full')
# Use this as default value. At invocation time, unit may still
# decide if backup generation is really neccessary.

    lastOffset = currentTime-self.lastFullBackupTime
    result = (self.fullBackupTiming[1]-lastOffset, 'full')
    if self.fullBackupTiming[2] != None:
      delta = self.fullBackupTiming[3]-(currentTime%self.fullBackupTiming[2])
      if delta < 0:
        delta += self.fullBackupTiming[2]
      if delta+lastOffset < self.fullBackupTiming[0]:
        delta += self.fullBackupTiming[2]
      if delta+lastOffset > self.fullBackupTiming[1]:
        delta = self.fullBackupTiming[1]-lastOffset
      if delta < result[0]:
        result = (delta, 'full')
# When a full backup is overdue, report it. Do not care if there
# are incremental backups more overdue.
    if result[0] <= 0:
      return result

    lastOffset = currentTime-self.lastAnyBackupTime
    if self.incBackupTiming[2] == None:
# Normal minimum, maximum timing mode.
      delta = self.incBackupTiming[0]-lastOffset
      if delta < result[0]:
        result = (delta, 'inc')
    else:
      delta = self.incBackupTiming[3]-(currentTime%self.incBackupTiming[2])
      if delta < 0:
        delta += self.incBackupTiming[2]
      if delta+lastOffset < self.incBackupTiming[0]:
        delta += self.incBackupTiming[2]
      if delta+lastOffset > self.incBackupTiming[1]:
        delta = self.incBackupTiming[1]-lastOffset
      if delta < result[0]:
        result = (delta, 'inc')
    return result

  def getBackupCommand(self, backupType, indexPathname):
    """Get the command to execute to create the backup.
    @param backupType use this mode to create the backup.
    @param indexPathname path to the index file name, None when
    backup without indexing is requested."""
    if (backupType == 'full') and (self.fullBackupOverrideCommand != None):
      return self.fullBackupOverrideCommand
    if (backupType == 'inc') and (self.incBackupOverrideCommand != None):
      return self.incBackupOverrideCommand

    backupCommand = ['tar']
    if self.ignoreBackupRacesFlag:
      backupCommand.append('--ignore-failed-read')
    backupCommand.append('-C')
    backupCommand.append(self.backupRoot)
    if self.incBackupTiming != None:
      backupCommand.append('--listed-incremental')
      backupCommand.append(indexPathname)
    if self.backupExcludeList != None:
      for excludePattern in self.backupExcludeList:
        backupCommand.append('--exclude=%s' % excludePattern)
    backupCommand.append('-c')
    backupCommand.append('--')
    backupCommand += self.backupIncludeList
    return backupCommand

  def getJsonData(self):
    """Return the state of this object in a format suitable for
    JSON serialization."""
    return [self.lastFullBackupTime, self.lastAnyBackupTime,
        base64.b64encode(self.lastUuidValue)]


class TarBackupUnit(guerillabackup.SchedulableGeneratorUnitInterface):
  """This class allows to schedule regular runs of tar backups.
  The unit supports different scheduling modes: modulo timing
  and maximum gap timing. The time stamps considered are always
  those from starting the tar backup, not end time.
  The unit will keep track of the last UUID reported for each
  resource and generate a new one for each produced file using
  json-serialized state data. The state data is a dictionary with
  the resource name as key to refer to a tuple of values: the
  last successful run timestamp as seconds since 1970, the timestamp
  of the last full backup run and the UUID value of the last run."""

  def __init__(self, unitName, configContext):
    """Initialize this unit using the given configuration."""
    self.unitName = unitName
    self.configContext = configContext

    self.testModeFlag = configContext.get(guerillabackup.CONFIG_GENERAL_DEBUG_TEST_MODE_KEY, False)
    if not isinstance(self.testModeFlag, bool):
      raise Exception('Configuration parameter %s has to be boolean' % guerillabackup.CONFIG_GENERAL_DEBUG_TEST_MODE_KEY)

    backupConfigList = configContext.get(CONFIG_LIST_KEY, None)
    if (backupConfigList == None) or (not isinstance(backupConfigList, dict)):
      raise Exception('Configuration parameter %s missing or of wrong type' % CONFIG_LIST_KEY)
    self.backupUnitDescriptions = {}
    for sourceUrl, configDef in backupConfigList.iteritems():
      self.backupUnitDescriptions[sourceUrl] = TarBackupUnitDescription(
          sourceUrl, configDef)

# Start loading the persistency information.
    persistencyDirFd = None
    persistencyFileHandle = None
    stateData = None
    try:
      persistencyDirFd = guerillabackup.openPersistencyFile(
          configContext, os.path.join('generators', self.unitName),
          os.O_DIRECTORY|os.O_RDONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_NOCTTY, 0700)

      try:
        persistencyFileHandle = guerillabackup.secureOpenAt(
            persistencyDirFd, 'state.current',
            fileOpenFlags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NOCTTY)
      except OSError as openError:
        if openError.errno != errno.ENOENT:
          raise

# See if the state.previous file exists, if yes, the unit is likely
# to be broken. Refuse to do anything while in this state.
      try:
        statResult = guerillabackup.guerillaOsFstatatFunction(
            persistencyDirFd, 'state.previous', 0)
        raise Exception(
            'Persistency data inconsistencies: found stale previous state file')
      except OSError as statError:
        if statError.errno != errno.ENOENT:
          raise
# So there is only the current state file, if any.
      if persistencyFileHandle != None:
        stateData = ''
        while True:
          data = os.read(persistencyFileHandle, 1<<20)
          if len(data) == 0:
            break
          stateData += data
        os.close(persistencyFileHandle)
        persistencyFileHandle = None
    finally:
      if persistencyFileHandle != None:
        os.close(persistencyFileHandle)
      if persistencyDirFd != None:
        os.close(persistencyDirFd)

# Start mangling of data after closing all file handles.
    if stateData == None:
      print >>sys.stderr, '%s: first time activation, no persistency data found' % self.unitName
    else:
      stateInfo = json.loads(stateData)
      if not isinstance(stateInfo, dict):
        raise Exception('Persistency data structure mismatch')
      for url, stateData in stateInfo.iteritems():
        description = self.backupUnitDescriptions.get(url, None)
        if description == None:
# Ignore this state, user might have removed a single tar backup
# configuration without deleting the UUID and timing data.
          print >>sys.stderr, 'No tar backup configuration for %s resource state data %s' % (url, repr(stateData))
          continue
        description.lastFullBackupTime = stateData[0]
        description.lastAnyBackupTime = stateData[1]
# The UUID is kept internally as binary data string. Only for
# persistency, data will be base64 encoded.
        description.lastUuidValue = base64.b64decode(stateData[2])


  def findNextInvocationUnit(self):
    """Find the next unit to invoke.
    @return a tuple containing the seconds till next invocation
    and the corresponding TarBackupUnitDescription. Next invocation
    time might be negative if unit invocation is already overdue."""
    currentTime = int(time.time())
    nextInvocationTime = None
    nextDescription = None
    for url, description in self.backupUnitDescriptions.iteritems():
      info = description.getNextInvocationInfo(currentTime)
      if (nextInvocationTime == None) or (info[0] < nextInvocationTime):
        nextInvocationTime = info[0]
        nextDescription = description
    if nextInvocationTime == None:
      return None
    return (nextInvocationTime, nextDescription)


  def getNextInvocationTime(self):
    """Get the time in seconds until this unit should called again.
    If a unit does not know (yet) as invocation needs depend on
    external events, it should report a reasonable low value to
    be queried again soon.
    @return 0 if the unit should be invoked immediately, the seconds
    to go otherwise."""
    nextUnitInfo = self.findNextInvocationUnit()
    if nextUnitInfo == None:
      return 3600
    if nextUnitInfo[0] < 0:
      return 0
    return nextUnitInfo[0]


  def processInput(self, tarUnitDescription, sink, persistencyDirFd):
    """Process a single input description by creating the tar
    stream and updating the indices, if any. When successful,
    persistency information about this subunit is updated also."""
# Keep time of invocation check and start of backup procedure
# also for updating the unit data.
    currentTime = int(time.time())
    (invocationTime, backupType) = tarUnitDescription.getNextInvocationInfo(
        currentTime)

    indexFilenamePrefix = None
    indexFilePathname = None
    if tarUnitDescription.incBackupTiming != None:
# We will have to create an index, open the index directory at
# first.
      indexFilenamePrefix = tarUnitDescription.sourceUrl[1:].replace('/', '-')
# Make sure the filename cannot get longer than 256 bytes, even
# with ".index(.bz2).yyyymmddhhmmss" (25 chars) appended.
      if len(indexFilenamePrefix) > 231:
        indexFilenamePrefix = indexFilenamePrefix[:231]

# Create the new index file.
      nextIndexFileName = '%s.index.next' % indexFilenamePrefix
      nextIndexFileHandle = guerillabackup.secureOpenAt(
          persistencyDirFd, nextIndexFileName,
          fileOpenFlags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_NOCTTY, fileCreateMode=0600)
      indexFilePathname = os.path.join(
          guerillabackup.getPersistencyBaseDirPathname(self.configContext),
          'generators', self.unitName, nextIndexFileName)

      if backupType == 'inc':
# See if there is an old index. When missing, change the mode
# to "full".
        indexStatResult = None
        try:
          indexStatResult = guerillabackup.guerillaOsFstatatFunction(
              persistencyDirFd, '%s.index' % indexFilenamePrefix, 0)
        except OSError as statError:
          if statError.errno != errno.ENOENT:
            raise
        if indexStatResult == None:
          backupType = 'full'
        else:
# Copy content from current index to new one.
          currentIndexFileHandle = guerillabackup.secureOpenAt(
              persistencyDirFd, '%s.index' % indexFilenamePrefix,
              fileOpenFlags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NOCTTY)
          while True:
            data = os.read(currentIndexFileHandle, 1<<20)
            if len(data) == 0:
              break
            os.write(nextIndexFileHandle, data)
          os.close(currentIndexFileHandle)
      os.close(nextIndexFileHandle)

# Everything is prepared for backup, start it.
    if tarUnitDescription.preBackupCommandList != None:
      if self.testModeFlag:
        print >>sys.stderr, 'No invocation of PreBackupCommand in test mode'
      else:
        process = subprocess.Popen(tarUnitDescription.preBackupCommandList)
        returnCode = process.wait()
        if returnCode != 0:
          raise Exception('Pre backup command %s failed in %s, source %s' % (repr(tarUnitDescription.preBackupCommandList)[1:-1], self.unitName, tarUnitDescription.sourceUrl))

# Start the unit itself.
    backupCommand = tarUnitDescription.getBackupCommand(
        backupType, indexFilePathname)
    completePipleline = [guerillabackup.OSProcessPipelineElement(
        '/bin/tar', backupCommand, allowedExitStatusList=[0, 2])]
# Get the downstream transformation pipeline elements.
    completePipleline += guerillabackup.getDefaultDownstreamPipeline(
        self.configContext, tarUnitDescription.encryptionKeyName)

# Build the transformation pipeline instance.
    sinkHandle = sink.getSinkHandle(tarUnitDescription.sourceUrl)
    sinkStream = sinkHandle.getSinkStream()

# Get the list of started pipeline instances.
    pipelineInstances = guerillabackup.instantiateTransformationPipeline(
        completePipleline, None, sinkStream, doStartFlag=True)
    try:
      guerillabackup.runTransformationPipeline(pipelineInstances)
    except:
# Just cleanup the incomplete index file.
      guerillabackup.internalUnlinkAt(
          persistencyDirFd, nextIndexFileName, 0)
      raise

    digestData = pipelineInstances[-1].getDigestData()

    metaInfoDict = {}
    metaInfoDict['BackupType'] = backupType
    if tarUnitDescription.handlingPolicyName != None:
      metaInfoDict['HandlingPolicy'] = [tarUnitDescription.handlingPolicyName]
    lastUuid = tarUnitDescription.lastUuidValue
    currentUuidDigest = hashlib.sha512()
    if lastUuid != None:
      metaInfoDict['Predecessor'] = lastUuid
      currentUuidDigest.update(lastUuid)
# Add the compressed file digest to make UUID different for different
# content.
    currentUuidDigest.update(digestData)
# Also include the timestamp and source URL in the UUID calculation
# to make UUID different for backup of identical data at (nearly)
# same time.
    currentUuidDigest.update(b'%d %s' % (currentTime, tarUnitDescription.sourceUrl))
    currentUuid = currentUuidDigest.digest()
    metaInfoDict['DataUuid'] = currentUuid
    metaInfoDict['StorageFileChecksumSha512'] = digestData
    metaInfoDict['Timestamp'] = currentTime

    metaInfo = BackupElementMetainfo(metaInfoDict)
    sinkHandle.close(metaInfo)
    if self.testModeFlag:
      raise Exception('No completion of tar backup in test mode')

    if tarUnitDescription.postBackupCommandList != None:
      process = subprocess.Popen(tarUnitDescription.postBackupCommandList)
      returnCode = process.wait()
      if returnCode != 0:
# Still raise an exception and thus prohibit completion of this
# tar backup. The PostBackupCommand itself cannot have an influence
# on the backup created before but the failure might indicate,
# that the corresponding PreBackupCommand was problematic. Thus
# let the user resolve the problem manually.
        raise Exception('Post backup command %s failed in %s, source %s' % (repr(tarUnitDescription.postBackupCommandList)[1:-1], self.unitName, tarUnitDescription.sourceUrl))

    if tarUnitDescription.incBackupTiming != None:
# See if there is an old index to compress and move, but only
# if it should be really kept. Currently fstatat function is not
# available, so use open/fstat instead.
      currentIndexFd = None
      currentIndexName = '%s.index' % indexFilenamePrefix
      try:
        currentIndexFd = guerillabackup.secureOpenAt(
            persistencyDirFd, currentIndexName,
            fileOpenFlags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NOCTTY)
      except OSError as indexOpenError:
        if indexOpenError.errno != errno.ENOENT:
          raise

      targetFileName = None
      if currentIndexFd != None:
        if tarUnitDescription.keepOldIndicesCount == 0:
          os.close(currentIndexFd)
          guerillabackup.internalUnlinkAt(persistencyDirFd, currentIndexName, 0)
        else:
          statData = os.fstat(currentIndexFd)
          targetFileTime = int(statData.st_mtime)
          targetFileHandle = None
          while True:
            date = datetime.datetime.fromtimestamp(targetFileTime)
            dateStr = date.strftime('%Y%m%d%H%M%S')
            targetFileName = '%s.index.bz2.%s' % (indexFilenamePrefix, dateStr)
            try:
              targetFileHandle = guerillabackup.secureOpenAt(
                  persistencyDirFd, targetFileName,
                  fileOpenFlags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_NOCTTY,
                  fileCreateMode=0600)
              break
            except OSError as indexBackupOpenError:
              if indexBackupOpenError.errno != errno.EEXIST:
                raise
            targetFileTime += 1
# Now both handles are valid, use external bzip2 binary to perform
# compression.
          process = subprocess.Popen(
              ['/bin/bzip2', '-c9'], stdin=currentIndexFd,
              stdout=targetFileHandle)
          returnCode = process.wait()
          if returnCode != 0:
            raise Exception('Failed to compress the old index: %s' % returnCode)
          os.close(currentIndexFd)
# FIXME: we should use futimes, not available yet in python.
          os.utime(
              '/proc/self/fd/%d' % targetFileHandle,
              (statData.st_mtime, statData.st_mtime))
          os.close(targetFileHandle)
          guerillabackup.internalUnlinkAt(
              persistencyDirFd, currentIndexName, 0)

# Now previous index was compressed or deleted, link the next
# index to the current position.
      guerillabackup.internalLinkAt(
          persistencyDirFd, nextIndexFileName,
          persistencyDirFd, currentIndexName, 0)
      guerillabackup.internalUnlinkAt(
          persistencyDirFd, nextIndexFileName, 0)

      if tarUnitDescription.keepOldIndicesCount != -1:
# So we should apply limits to the number of index backups.
        fileList = []
        searchPrefix = '%s.index.bz2.' % indexFilenamePrefix
        searchLength = len(searchPrefix)+14
        for fileName in guerillabackup.listDirAt(persistencyDirFd):
          if ((len(fileName) != searchLength) or
              (not fileName.startswith(searchPrefix))):
            continue
          fileList.append(fileName)
        fileList.sort()

        if len(fileList) > tarUnitDescription.keepOldIndicesCount:
# Make sure that the new index file was sorted last. When not,
# the current state could indicate clock/time problems on the
# machine. Refuse to process the indices and issue a warning.
          indexBackupPos = fileList.index(targetFileName)
          if indexBackupPos+1 != len(fileList):
            raise Exception('Sorting of old backup indices inconsistent, refusing cleanup')
          for fileName in fileList[:-tarUnitDescription.keepOldIndicesCount]:
            guerillabackup.internalUnlinkAt(persistencyDirFd, fileName, 0)

# Update the UUID map as last step: if any of the steps above
# would fail, currentUuid generated in next run will be identical
# to this. Sorting out the duplicates will be easy.
    tarUnitDescription.lastUuidValue = currentUuid
# Update the timestamp.
    tarUnitDescription.lastAnyBackupTime = currentTime
    if backupType == 'full':
      tarUnitDescription.lastFullBackupTime = currentTime

# Write the new persistency data before returning.
    self.updateStateData(persistencyDirFd)


  def invokeUnit(self, sink):
    """Invoke this unit to create backup elements and pass them
    on to the sink. Even when indicated via getNextInvocationTime,
    the unit may decide, that it is not yet ready and not write
    any element to the sink.
    @return None if currently there is nothing to write to the
    sink, a number of seconds to retry invocation if the unit
    assumes, that there is data to be processed but processing
    cannot start yet, e.g. due to locks held by other parties
    or resource, e.g. network storages, currently not available.
    @throw Exception if the unit internal logic failed in any
    uncorrectable ways. Even when invoker decides to continue
    processing, it must not reinvoke this unit before complete
    reload."""

    persistencyDirFd = None
    try:
      while True:
        nextUnitInfo = self.findNextInvocationUnit()
        if nextUnitInfo == None:
          return None
        if nextUnitInfo[0] > 0:
          return nextUnitInfo[0]

        if persistencyDirFd == None:
# Not opened yet, do it now.
          persistencyDirFd = guerillabackup.openPersistencyFile(
              self.configContext, os.path.join('generators', self.unitName),
              os.O_DIRECTORY|os.O_RDONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_NOCTTY, 0600)

# Try to process the current tar backup unit. There should be
# no state change to persist or cleanup, just let any exception
# be passed on to caller.
        try:
          self.processInput(nextUnitInfo[1], sink, persistencyDirFd)
        except Exception as processException:
          print >>sys.stderr, '%s: Error processing tar %s, disabling it temporarily\n%s' % (self.unitName, repr(nextUnitInfo[1].sourceUrl), processException)
          traceback.print_tb(sys.exc_info()[2])
          nextUnitInfo[1].nextRetryTime = time.time()+3600
    finally:
      if persistencyDirFd != None:
        try:
          os.close(persistencyDirFd)
          persistencyDirFd = None
        except Exception as closeException:
          print >>sys.stderr, 'FATAL: Internal Error: failed to close persistency directory handle %d: %s' % (persistencyDirFd, str(closeException))


  def updateStateData(self, persistencyDirFd):
    """Replace the current state data file with one containing
    the current unit internal state.
    @throw Exception is writing fails for any reason. The unit
    will be in incorrectable state afterwards."""

# Create the data structures for writing.
    stateData = {}
    for sourceUrl, description in self.backupUnitDescriptions.iteritems():
      stateData[sourceUrl] = description.getJsonData()
    writeData = json.dumps(stateData)

# Try to replace the current state file. At first unlink the old
# one.
    try:
      guerillabackup.internalUnlinkAt(persistencyDirFd, 'state.old', 0)
    except OSError as unlinkError:
      if unlinkError.errno != errno.ENOENT:
        raise
# Link the current to the old one.
    try:
      guerillabackup.internalLinkAt(
          persistencyDirFd, 'state.current', persistencyDirFd, 'state.old', 0)
    except OSError as relinkError:
      if relinkError.errno != errno.ENOENT:
        raise
# Unlink the current state. Thus we can then use O_EXCL on create.
    try:
      guerillabackup.internalUnlinkAt(persistencyDirFd, 'state.current', 0)
    except OSError as relinkError:
      if relinkError.errno != errno.ENOENT:
        raise
# Create the new file.
    fileHandle = None
    try:
      fileHandle = guerillabackup.secureOpenAt(
          persistencyDirFd, 'state.current',
          fileOpenFlags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_NOCTTY, fileCreateMode=0600)
      os.write(fileHandle, writeData)
# Also close handle within try, except block to catch also delayed
# errors after write.
      os.close(fileHandle)
      fileHandle = None
    except Exception as stateSaveException:
# Writing of state information failed. Print out the state information
# for manual reconstruction as last resort.
      exceptionInfo = sys.exc_info()
      print >>sys.stderr, 'Writing of state information failed: %s\nCurrent state: %s' % (str(stateSaveException), repr([self.lastInvocationTime, self.resourceUuidMap]))
      raise
    finally:
      if fileHandle != None:
        os.close(fileHandle)


# Declare the main unit class so that the backup generator can
# instantiate it.
backupGeneratorUnitClass = TarBackupUnit
