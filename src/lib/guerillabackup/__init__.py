"""This is the main guerillabackup module containing interfaces,
common helper functions."""

import errno
import os
import select
import sys
import time

CONFIG_GENERAL_PERSISTENCY_BASE_DIR_KEY = 'GeneralPersistencyBaseDir'
CONFIG_GENERAL_PERSISTENCY_BASE_DIR_DEFAULT = '/var/lib/guerillabackup/state'
CONFIG_GENERAL_RUNTIME_DATA_DIR_KEY = 'GeneralRuntimeDataDir'
CONFIG_GENERAL_RUNTIME_DATA_DIR_DEFAULT = '/var/run/guerillabackup'

CONFIG_GENERAL_DEBUG_TEST_MODE_KEY = 'GeneralDebugTestModeFlag'

GENERATOR_UNIT_CLASS_KEY = 'backupGeneratorUnitClass'

TRANSFER_RECEIVER_POLICY_CLASS_KEY = 'TransferReceiverPolicyClass'
TRANSFER_RECEIVER_POLICY_INIT_ARGS_KEY = 'TransferReceiverPolicyInitArgs'
TRANSFER_SENDER_POLICY_CLASS_KEY = 'TransferSenderPolicyClass'
TRANSFER_SENDER_POLICY_INIT_ARGS_KEY = 'TransferSenderPolicyInitArgs'

# Some constants not available on Python os module level yet.
AT_SYMLINK_NOFOLLOW = 0x100
AT_EMPTY_PATH = 0x1000

class TransformationPipelineElementInterface:
  """This is the interface to define data transformation pipeline
  elements, e.g. for compression, encryption, signing. To really
  start execution of a transformation pipeline, transformation
  process instances have to be created for each pipe element."""
  def getExecutionInstance(self, upstreamProcessOutput):
    """Get an execution instance for this transformation element.
    @param upstreamProcessOutput this is the output of the upstream
    process, that will be wired as input of the newly created
    process instance."""
    raise Exception('Interface method called')


class TransformationProcessOutputInterface:
  """This interface has to be implemented by all pipeline instances,
  both synchronous and asynchronous. When an instance reaches
  stopped state, it has to guarantee, that both upstream and downstream
  instance will detect EOF or an exception is raised when output
  access is attempted."""
  def getOutputStreamDescriptor(self):
    """Get the file descriptor to read output from this output
    interface. When supported, a downstream asynchronous process
    may decide to operate only using the stream, eliminating the
    need to be invoked for IO operations after starting.
    @return the file descriptor, pipe or socket or None if stream
    operation is not available."""
    raise Exception('Interface method called')
  def readData(self, length):
    """Read data from this output. This method must not block
    as it is usually invoked from synchronous pipeline elements.
    @return the at most length bytes of data, zero-length data
    if nothing available at the moment and None when end of input
    was reached."""
    raise Exception('Interface method called')
  def close(self):
    """Close this interface. This will guarantee, that any future
    access will report EOF or an error.
    @raise Exception if close is attempted there still is data
    available."""
    raise Exception('Interface method called')


class TransformationProcessInterface:
  """This is the interface of all pipe transformation process
  instances."""
  def getProcessOutput(self):
    """Get the output connector of this transformation process.
    After calling this method, it is not possible to set an output
    stream using setProcessOutputStream."""
    raise Exception('Interface method called')
  def setProcessOutputStream(self, processOutputStream):
    """Some processes may also support setting of an output stream
    file descriptor. This is especially useful if the process
    is the last one in a pipeline and hence could write directly
    to a file or network descriptor. After calling this method,
    it is not possible to switch back to getProcessOutput.
    @throw Exception if this process does not support setting
    of output stream descriptors."""
    raise Exception('Interface method called')
  def isAsynchronous(self):
    """A asynchronous process just needs to be started and will
    perform data processing on streams without any further interaction
    while running. This method may raise an exception when the
    process element was not completely connected yet: operation
    mode might not be known yet."""
    raise Exception('Interface method called')
  def start(self):
    """Start this execution process."""
    raise Exception('Interface method called')
  def stop(self):
    """Stop this execution process when still running.
    @return None when the the instance was already stopped, information
    about stopping, e.g. the stop error message when the process
    was really stopped."""
    raise Exception('Interface method called')
  def isRunning(self):
    """See if this process instance is still running.
    @return False if instance was not yet started or already stopped.
    If there are any unreported pending errors from execution,
    this method will return True until doProcess() or stop() is
    called at least once."""
    raise Exception('Interface method called')
  def doProcess(self):
    """This method triggers the data transformation operation
    of this component. For components in synchronous mode, the
    method will attempt to move data from input to output. Asynchronous
    components will just check the processing status and may raise
    an exception, when processing terminated with errors. As such
    a component might not be able to detect the amount of data
    really moved since last invocation, the component may report
    a fake single byte move.
    @throws Exception if an uncorrectable transformation state
    was reached and transformation cannot proceed, even though
    end of input data was not yet seen. Raise exception also when
    process was not started or already stopped.
    @return the number of bytes read or written or at least a
    value greater zero if any data was processed. A value of zero
    indicates, that currently data processing was not possible
    due to filled buffers but should be attemted again. A value
    below zero indicates that all input data was processed and
    output buffers were flushed already."""
    raise Exception('Interface method called')
  def getBlockingStreams(self, readStreamList, writeStreamList):
    """Collect the file descriptors that are currently blocking
    this synchronous compoment."""
    raise Exception('Interface method called')


class SchedulableGeneratorUnitInterface:
  """This is the interface each generator unit has to provide
  for interaction with a backup generator component. Therefore
  this component has to provide both information about scheduling
  and the backup data elements on request. In return, it receives
  configuration information and persistency support from the
  invoker."""

  def __init__(self, unitName, configContext):
    """Initialize this unit using the given configuration. The
    new object has to keep a reference to when needed.
    @param unitName The name of the activated unit main file in
    /etc/guerillabackup/units."""
    raise Exception('Interface method called')

  def getNextInvocationTime(self):
    """Get the time in seconds until this unit should called again.
    If a unit does not know (yet) as invocation needs depend on
    external events, it should report a reasonable low value to
    be queried again soon.
    @return 0 if the unit should be invoked immediately, the seconds
    to go otherwise."""
    raise Exception('Interface method called')

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
    raise Exception('Interface method called')


class SinkInterface:
  """This is the interface each sink has to provide to store backup
  data elements from different sources."""

  def __init__(self, configContext):
    """Initialize this sink with parameters from the given configuration
    context."""
    raise Exception('Interface method called')

  def getSinkHandle(self, sourceUrl):
    """Get a handle to perform transfer of a single backup data
    element to a sink."""
    raise Exception('Interface method called')


class SinkHandleInterface:
  """This is the common interface of all sink handles to store
  a single backup data element to a sink."""
  def getSinkStream(self):
    """Get the file descriptor to write directly to the open backup
    data element at the sink, if available. The stream should
    not be closed using os.close(), but via the close method from
    SinkHandleInterface.
    @return the file descriptor or None when not supported."""
    raise Exception('Interface method called')
  def write(self, data):
    """Write data to the open backup data element at the sink."""
    raise Exception('Interface method called')
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
    raise Exception('Interface method called')
  def getElementId(self):
    """Get the storage element ID of the previously written data.
    @throws Exception if the element ID is not yet available because
    the object is not closed yet."""
    raise Exception('Interface method called')

class StorageInterface:
  """This is the interface of all stores for backup data elements
  providing access to content data and metainfo but also additional
  storage attributes. The main difference to a generator unit
  is, that data is just retrieved but not generated on invocation."""

  def __init__(self, configContext):
    """Initialize this store with parameters from the given configuration
    context."""
    raise Exception('Interface method called')

  def getSinkHandle(self, sourceUrl):
    """Get a handle to perform transfer of a single backup data
    element to a sink. This method may never block or raise an
    exception, even other concurrent sink, query or update procedures
    are in progress."""
    raise Exception('Interface method called')

  def getBackupDataElement(self, elementId):
    """Retrieve a single stored backup data element from the storage.
    @param elementId the storage ID of the backup data element.
    @throws Exception when an incompatible query, update or read
    is in progress."""
    raise Exception('Interface method called')

  def getBackupDataElementForMetaData(self, sourceUrl, metaData):
    """Retrieve a single stored backup data element from the storage.
    @param sourceUrl the URL identifying the source that produced
    the stored data elements.
    @param metaData metaData dictionary for the element of interest.
    @throws Exception when an incompatible query, update or read
    is in progress."""
    raise Exception('Interface method called')

  def queryBackupDataElements(self, query):
    """Query this storage.
    @param query if None, return an iterator over all stored elements.
    Otherwise query has to be a function returning True or False
    for StorageBackupDataElementInterface elements.
    @return BackupDataElementQueryResult iterator for this query.
    @throws Exception if there are any open queries or updates
    preventing response."""
    raise Exception('Interface method called')


class StorageBackupDataElementInterface:
  """This class encapsulates access to a stored backup data element."""

  def getElementId(self):
    """Get the storage element ID of this data element."""
    raise Exception('Interface method called')

  def getSourceUrl(self):
    """Get the source URL of the storage element."""
    raise Exception('Interface method called')

  def getMetaData(self):
    """Get only the metadata part of this element.
    @return a BackupElementMetainfo object"""
    raise Exception('Interface method called')

  def getDataStream(self):
    """Get a stream to read data from that element.
    @return a file descriptor for reading this stream."""
    raise Exception('Interface method called')

  def setExtraData(self, name, value):
    """Attach or detach extra data to this storage element. This
    function is intended for agents to use the storage to persist
    this specific data also.
    @param value the extra data content or None to remove the
    element."""
    raise Exception('Interface method called')

  def getExtraData(self, name):
    """@return None when no extra data was found, the content
    otherwise"""
    raise Exception('Interface method called')

  def delete(self):
    """Delete this data element and all extra data element."""
    raise Exception('Interface method called')

  def lock(self):
    """Lock this backup data element.
    @throws Exception if the element does not exist any more or
    cannot be locked"""
    raise Exception('Interface method called')

  def unlock(self):
    """Unlock this backup data element."""
    raise Exception('Interface method called')


class BackupDataElementQueryResult():
  """This is the interface of all query results."""
  def getNextElement(self):
    """Get the next backup data element from this query iterator.
    @return a StorageBackupDataElementInterface object."""
    raise Exception('Interface method called')


# Define common functions:
def isValueListOfType(value, targetType):
  """Check if a give value is a list of values of given target
  type."""
  if not isinstance(value, list):
    return False
  for item in value:
    if not isinstance(item, targetType):
      return False
  return True

def assertSourceUrlSpecificationConforming(sourceUrl):
  """Assert that the source URL is according to specification."""
  if (sourceUrl[0] != '/') or (sourceUrl[-1] == '/'):
    raise Exception('Slashes not conforming')
  for urlPart in sourceUrl[1:].split('/'):
    if len(urlPart) == 0:
      raise Exception('No path part between slashes')
    if (urlPart == '.') or (urlPart == '..'):
      raise Exception('. and .. forbidden')
    for urlChar in urlPart:
      if urlChar not in '%-.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz':
        raise Exception('Invalid character %s in URL part' % repr(urlChar))


def getDefaultDownstreamPipeline(configContext, encryptionKeyName):
  """This function returns the default processing pipeline for
  locally generated backup data. It uses the GeneralDefaultCompressionElement
  and GeneralDefaultEncryptionElement parameters from the configuration
  to generate the pipeline, including a DigestPipelineElement
  at the end.
  @encryptionKeyName when not None, this method will change the
  key in the GeneralDefaultEncryptionElement when defined. Otherwise
  a default gpg encryption element is created using keys from
  /etc/guerillabackup/keys."""

  downstreamPipelineElements = []
  compressionElement = configContext.get(
      'GeneralDefaultCompressionElement', None)
  if compressionElement != None:
    downstreamPipelineElements.append(compressionElement)

  encryptionElement = configContext.get('GeneralDefaultEncryptionElement', None)
  if encryptionKeyName != None:
    if encryptionElement != None:
      encryptionElement = encryptionElement.replaceKey(encryptionKeyName)
    else:
      encryptionCallArguments = GpgEncryptionPipelineElement.gpgDefaultCallArguments
      if compressionElement != None:
        encryptionCallArguments += ['--compress-algo', 'none']
      encryptionElement = GpgEncryptionPipelineElement(
          encryptionKeyName, encryptionCallArguments)
  if encryptionElement != None:
    downstreamPipelineElements.append(encryptionElement)
  downstreamPipelineElements.append(DigestPipelineElement())
  return downstreamPipelineElements


def instantiateTransformationPipeline(
    pipelineElements, upstreamProcessOutput, downstreamProcessOutputStream,
    doStartFlag=False):
  """Create transformation instances for the list of given pipeline
  elements.
  @param upstreamProcessOutput TransformationProcessOutputInterface
  upstream output. This parameter might be None for a pipeline
  element at first position creating the backup data internally.
  @param downstreamProcessOutputStream if None, enable this stream
  as output of the last pipeline element."""
  if ((upstreamProcessOutput != None) and
      (not isinstance(
          upstreamProcessOutput, TransformationProcessOutputInterface))):
    raise Exception('upstreamProcessOutput not an instance of TransformationProcessOutputInterface')
  if doStartFlag and (downstreamProcessOutputStream is None):
    raise Exception('Cannot autostart instances without downstream')
  instanceList = []
  lastInstance = None
  for element in pipelineElements:
    if lastInstance != None:
      upstreamProcessOutput = lastInstance.getProcessOutput()
    instance = element.getExecutionInstance(upstreamProcessOutput)
    upstreamProcessOutput = None
    lastInstance = instance
    instanceList.append(instance)
  if downstreamProcessOutputStream != None:
    lastInstance.setProcessOutputStream(downstreamProcessOutputStream)
  if doStartFlag:
    for instance in instanceList:
      instance.start()
  return instanceList


def runTransformationPipeline(pipelineInstances):
  """Run all processes included in the pipeline until processing
  is complete or the first uncorrectable error is detected by
  transformation process. All transformation instances have to
  be started before calling this method.
  @param pipelineInstances the list of pipeline instances. The
  instances have to be sorted, so the one reading or creating
  the input data is the first, the one writing to the sink the
  last in the list.
  @throws Exception when first failing pipeline element is detected.
  This will not terminate the whole pipeline, other elements have
  to be stopped explicitely."""
  pollInstancesList = []
  for instance in pipelineInstances:
    if not instance.isAsynchronous():
      pollInstancesList.append(instance)
# Run all the synchronous units.
  while len(pollInstancesList) != 0:
    processState = -1
    for instance in pollInstancesList:
      result = instance.doProcess()
      processState = max(processState, result)
      if result < 0:
        pollInstancesList.remove(instance)
# Fake state and pretend something was moved. Modifying the list
# in loop might skip elements, thus cause invalid state information
# aggregation.
        processState = 1
        break
    if processState != 0:
      continue

# Not a single component was able to move data. This might be
# a deadlock, but we cannot be sure. It might be a read operation
# at the upstream side of the pipe or the downstream side write,
# that cannot be performed without blocking, e.g. due to network
# or filesystem IO issues. Update the state of all synchronous
# components and if all are still running, wait for any IO to
# end blocking.
    readStreamList = []
    writeStreamList = []
    shouldBlockFlag = True
    for instance in pipelineInstances:
# Ignore any instance not running. This state is only reached
# after reporting any pending errors in a final doProcess() call.
# When everything worked out as required to reach the stop state,
# then all outputs will be closed anyway.
      if not instance.isRunning():
        continue
      if instance.isAsynchronous():
# Just trigger the method for asynchronous jobs. Any pending errors
# will be reported but method will never block anyway.
        result = instance.doProcess()
        if result < 0:
          shouldBlockFlag = False
      else:
        instance.getBlockingStreams(readStreamList, writeStreamList)
    if not shouldBlockFlag:
      continue
# All asynchronous instances are still running, block on streams
# if any.
    select.select(readStreamList, writeStreamList, [], 1)

  for instance in pipelineInstances:
    while instance.isRunning():
      time.sleep(1)


def listDirAt(dirFd, path='.'):
  """This function provides the os.listdir() functionality to
  list files in an opened directory for python2.x. With Python
  3.x listdir() also accepts file descriptors as argument."""
  currentDirFd = os.open('.', os.O_DIRECTORY|os.O_RDONLY|os.O_NOCTTY)
  result = None
  try:
    os.fchdir(dirFd)
    result = os.listdir(path)
  finally:
    os.fchdir(currentDirFd)
    os.close(currentDirFd)
  return result


def secureOpenAt(
    dirFd, pathName, symlinksAllowedFlag=False,
    dirOpenFlags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOCTTY,
    dirCreateMode=None, fileOpenFlags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NOCTTY,
    fileCreateMode=None):
  """Perform a secure opening of the file. This function does
  not circumvent the umask in place when applying create modes.
  @param dirFd the directory file descriptor where to open a relative
  pathName, ignored for absolute pathName values.
  @param pathName open the path denotet by this string relative
  to the dirFd directory. When pathName is absolute, dirFd will
  be ignored. The pathName must not end with '/' unless the directory
  path '/' itself is specified. Distinction what should be opened
  has to be made using the flags.
  @param symlinksAllowedFlag when not set to True, O_NOFOLLOW
  will be added to each open call.
  @param dirOpenFlag those flags are used to open directory path
  components without modification. The flags have to include the
  O_DIRECTORY flag. The O_NOFOLLOW and O_NOCTTY flags are strongly
  recommended and should be omitted only in special cases.
  @param dirCreateMode if not None, missing directories will be created
  with the given mode.
  @param fileOpenFlags flags to apply when opening the last component
  @param fileCreateMode if not None, missing files will be created
  when O_CREAT was also in the fileOpenFlags."""

  if (dirOpenFlags&os.O_DIRECTORY) == 0:
    raise Exception('Directory open flags have to include O_DIRECTORY')
  if not symlinksAllowedFlag:
    dirOpenFlags |= os.O_NOFOLLOW
    fileOpenFlags |= os.O_NOFOLLOW
  if fileCreateMode is None:
    fileCreateMode = 0

  if pathName == '/':
    return os.open(pathName, os.O_RDONLY|os.O_DIRECTORY|os.O_NOCTTY)

  if pathName.endswith('/'):
    raise Exception('Invalid path value')

  currentDirFd = dirFd
  if pathName.startswith('/'):
    currentDirFd = os.open(
        '/', os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOCTTY)
    pathName = pathName[1:]

  pathNameParts = pathName.split('/')
  try:
# Traverse all the directory path parts, but just one at a time
# to avoid following symlinks.
    for pathNamePart in pathNameParts[:-1]:
      try:
        nextDirFd = os.open(pathNamePart, dirOpenFlags, dir_fd=currentDirFd)
      except OSError as openError:
        if openError.errno == errno.EACCES:
          raise
        if dirCreateMode is None:
          raise
        os.mkdir(pathNamePart, mode=dirCreateMode, dir_fd=currentDirFd)
        nextDirFd = os.open(pathNamePart, dirOpenFlags, dir_fd=currentDirFd)
      if currentDirFd != dirFd:
        os.close(currentDirFd)
      currentDirFd = nextDirFd

# Now open the last part. Always open last part separately,
# also for directories: the last open may use different flags.
    directoryCreateFlag = False
    if (((fileOpenFlags&os.O_DIRECTORY) != 0) and
        ((fileOpenFlags&os.O_CREAT) != 0)):
      directoryCreateFlag = True
# Clear the create flag, otherwise open would create a file instead
# of a directory, ignoring the O_DIRECTORY flag.
      fileOpenFlags &= ~os.O_CREAT
    resultFd = None
    try:
      resultFd = os.open(
          pathNameParts[-1], fileOpenFlags, mode=fileCreateMode,
          dir_fd=currentDirFd)
    except OSError as openError:
      if (not directoryCreateFlag) or (openError.errno != errno.ENOENT):
        raise
      os.mkdir(pathNameParts[-1], mode=dirCreateMode, dir_fd=currentDirFd)
      resultFd = os.open(
          pathNameParts[-1], fileOpenFlags, dir_fd=currentDirFd)
    return resultFd
  finally:
# Make sure to close the currentDirFd, otherwise we leak one fd
# per error.
    if currentDirFd != dirFd:
      os.close(currentDirFd)

# Fail on all errors not related to concurrent proc filesystem
# changes.
OPENER_INFO_FAIL_ON_ERROR = 0
# Do not fail on errors related to limited permissions accessing
# the information. This flag is needed when running without root
# privileges.
OPENER_INFO_IGNORE_ACCESS_ERRORS = 1

def getFileOpenerInformation(pathNameList, checkMode=OPENER_INFO_FAIL_ON_ERROR):
  """Get information about processes currently having access to
  one of the absolute pathnames from the list. This is done reading
  information from the proc filesystem. As access to proc might
  be limited for processes with limited permissions, the function
  can be forced to ignore the permission errors occurring during
  those checks.
  CAVEAT: The checks are meaningful to detect concurrent write
  access to files where e.g. a daemon did not close them on error
  or a file is currently filled. The function is always racy,
  a malicious process can also trick guerillabackup to believe
  a file is in steady state and not currently written even when
  that is not true.
  @param pathNameList a list of absolute pathnames to check in
  parallel. All those entries have to pass a call to os.path.realpath
  unmodified.
  @return a list containing one entry per pathNameList entry.
  The entry can be none if no access to the file was detected.
  Otherwise the entry is a list with tuples containing the pid
  of the process having access to the file and a list with tuples
  containing the fd within that process and a the flags."""

  for pathName in pathNameList:
    if pathName != os.path.realpath(pathName):
      raise Exception('%s is not an absolute, canonical path' % pathName)

  if checkMode not in [OPENER_INFO_FAIL_ON_ERROR, OPENER_INFO_IGNORE_ACCESS_ERRORS]:
    raise Exception('Invalid checkMode given')

  resultList = [None]*len(pathNameList)
  for procPidName in os.listdir('/proc'):
    procPid = -1
    try:
      procPid = int(procPidName)
    except ValueError:
      continue
    fdDirName = '/proc/%s/fd' % procPidName
    fdInfoDirName = '/proc/%s/fdinfo' % procPidName
    fdFileList = []
    try:
      fdFileList = os.listdir(fdDirName)
    except OSError as fdListException:
      if fdListException.errno == errno.ENOENT:
        continue
      if ((fdListException.errno == errno.EACCES) and
          (checkMode == OPENER_INFO_IGNORE_ACCESS_ERRORS)):
        continue
      raise
    for openFdName in fdFileList:
      targetPathName = None
      try:
        targetPathName = os.readlink('%s/%s' % (fdDirName, openFdName))
      except OSError as readLinkError:
        if readLinkError.errno == errno.ENOENT:
          continue
        raise

      pathNameIndex = -1
      try:
        pathNameIndex = pathNameList.index(targetPathName)
      except ValueError:
        continue
# At least one hit, read the data.
      infoFd = os.open(
          '%s/%s' % (fdInfoDirName, openFdName),
          os.O_RDONLY|os.O_NOFOLLOW|os.O_NOCTTY)
      infoData = os.read(infoFd, 1<<16)
      os.close(infoFd)
      splitPos = infoData.find(b'flags:\t')
      if splitPos < 0:
        raise Exception('Unexpected proc behaviour')
      endPos = infoData.find(b'\n', splitPos)
      infoTuple = (int(openFdName), int(infoData[splitPos+7:endPos], 8))
      while True:
        if resultList[pathNameIndex] is None:
          resultList[pathNameIndex] = [(procPid, [infoTuple])]
        else:
          pathNameInfo = resultList[pathNameIndex]
          indexPos = -1-len(pathNameInfo)
          for index in range(0, len(pathNameInfo)):
            if pathNameInfo[index][0] == procPid:
              indexPos = index
              break
            if pathNameInfo[index][0] > procPid:
              indexPos = -1-index
              break
          if indexPos >= 0:
            pathNameInfo[indexPos][1].append(infoTuple)
          else:
            indexPos = -1-indexPos
            pathNameInfo.insert(indexPos, (procPid, [infoTuple]))
        try:
          pathNameIndex = pathNameList.index(targetPathName, pathNameIndex+1)
        except ValueError:
          break
  return resultList

def getPersistencyBaseDirPathname(configContext):
  """Get the persistency data directory pathname from configuration
  or return the default value."""
  return configContext.get(
      CONFIG_GENERAL_PERSISTENCY_BASE_DIR_KEY,
      CONFIG_GENERAL_PERSISTENCY_BASE_DIR_DEFAULT)

def getRuntimeDataDirPathname(configContext):
  """Get the runtime data directory pathname from configuration
  or return the default value."""
  return configContext.get(
      CONFIG_GENERAL_RUNTIME_DATA_DIR_KEY,
      CONFIG_GENERAL_RUNTIME_DATA_DIR_DEFAULT)

def openPersistencyFile(configContext, pathName, flags, mode):
  """Open or possibly create a persistency file in the default
  persistency directory."""
  baseDir = getPersistencyBaseDirPathname(configContext)
  return secureOpenAt(
      -1, os.path.join(baseDir, pathName), symlinksAllowedFlag=False,
      dirOpenFlags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOCTTY,
      dirCreateMode=0o700, fileOpenFlags=flags|os.O_NOFOLLOW|os.O_NOCTTY,
      fileCreateMode=mode)

def readFully(readFd):
  """Read data from a file descriptor until EOF is reached."""
  data = b''
  while True:
    block = os.read(readFd, 1<<16)
    if len(block) == 0:
      break
    data += block
  return data

def execConfigFile(configFileName, configContext):
  """Load code from file and execute it with given global context."""
  configFile = open(configFileName, 'r')
  configData = configFile.read()
  configFile.close()
  configCode = compile(configData, configFileName, 'exec')
  exec(configCode, configContext, configContext)


# Load some classes into this namespace as shortcut for use in
# configuration files.
from guerillabackup.DefaultFileSystemSink import DefaultFileSystemSink
from guerillabackup.DigestPipelineElement import DigestPipelineElement
from guerillabackup.GpgEncryptionPipelineElement import GpgEncryptionPipelineElement
from guerillabackup.OSProcessPipelineElement import OSProcessPipelineElement
from guerillabackup.Transfer import SenderMoveDataTransferPolicy
from guerillabackup.UnitRunConditions import AverageLoadLimitCondition
from guerillabackup.UnitRunConditions import LogicalAndCondition
from guerillabackup.UnitRunConditions import MinPowerOnTimeCondition
import guerillabackup.Utils
