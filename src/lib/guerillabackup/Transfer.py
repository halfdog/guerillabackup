"""This module contains a collection of interfaces and classes
for agent-based transfer and synchronization."""

import errno
import json
import os
import select
import socket
import struct
import sys
import threading
import time

import guerillabackup
from guerillabackup.BackupElementMetainfo import BackupElementMetainfo


class TransferContext():
  """This class stores all information about a remote TransferAgent
  while it is attached to this TransferAgent. It is the responsibility
  of the class creating a new context to authenticate the remote
  side and to assign the correct agent id if needed.
  @param localStorage local storage to used by policies for data
  retrieval and storage."""
  def __init__(
      self, agentId, receiverTransferPolicy, senderTransferPolicy,
      localStorage):
    self.agentId = agentId
    self.receiverTransferPolicy = receiverTransferPolicy
    self.senderTransferPolicy = senderTransferPolicy
    self.localStorage = localStorage
    self.clientProtocolAdapter = None
    self.serverProtocolAdapter = None
    self.shutdownOfferedFlag = False
    self.shutdownAcceptedFlag = False

  def connect(self, clientProtocolAdapter, serverProtocolAdapter):
    """Connect this context with the client and server adapters."""
    self.clientProtocolAdapter = clientProtocolAdapter
    self.serverProtocolAdapter = serverProtocolAdapter

  def offerShutdown(self):
    """Offer protocol shutdown to the other side."""
    if self.clientProtocolAdapter is None:
      raise Exception('Cannot offer shutdown while not connected')
    if self.shutdownOfferedFlag:
      raise Exception('Shutdown already offered')
    self.clientProtocolAdapter.offerShutdown()
    self.shutdownOfferedFlag = True

  def waitForShutdown(self):
    """Wait for the remote side to offer a shutdown and accept
    it."""
    if self.shutdownAcceptedFlag:
      return
    self.clientProtocolAdapter.waitForShutdown()
    self.shutdownAcceptedFlag = True

  def isShutdownAccepted(self):
    """Check if we already accepted a remote shutdown offer."""
    return self.shutdownAcceptedFlag


class ProtocolDataElementStream:
  """This is the interface of any client protocol stream to a
  remote data element."""

  def read(self, readLength=0):
    """Read data from the current data element.
    @param readLength if not zero, return a chunk of data with
    at most the given length. When zero, return chunks with the
    default size of the underlying IO layer.
    @return the amount of data read or an empty string when end
    of stream was reached."""
    raise Exception('Interface method called')

  def close(self):
    """Close the stream. This call might discard data already
    buffered within this object or the underlying IO layer. This
    method has to be invoked also when the end of the stream was
    reached."""
    raise Exception('Interface method called')


class ClientProtocolInterface:
  """This is the client side protocol adapter to initiate retrieval
  of remote data from a remote SenderTransferPolicy. Each method
  of the interface but also the returned FileInfo objects may
  raise an IOError('Connection closed') to indicate connection
  failures."""

  def getRemotePolicyInfo(self):
    """Get information about the remote policy. The local agent
    may then check if remote SenderTransferPolicy is compatible
    to local settings and ReceiverTransferPolicy.
    @return information about the remote sender policy or None
    when no sender policy is installed, thus requesting remote
    files is impossible."""
    raise Exception('Interface method called')

  def startTransaction(self, queryData):
    """Start or restart a query transaction to retrive files from
    beginning on, even when skipped in previous round. The query
    pointer is positioned before the first FileInfo to retrieve.
    @param query data to send as query to remote side.
    @throws exception if transation start is not possible or query
    data was not understood by remote side."""
    raise Exception('Interface method called')

  def nextDataElement(self, wasStoredFlag=False):
    """Move to the next FileInfo.
    @param wasStoredFlag if true, indicate that the previous file
    was stored successfully on local side.
    @return True if a next FileInfo is available, False otherwise."""
    raise Exception('Interface method called')

  def getDataElementInfo(self):
    """Get information about the currently selected data element.
    The method can be invoked more than once on the same data
    element. Extraction of associated stream data is only be possible
    until proceeding to the next FileInfo using nextDataElement().
    @return a tuple with the source URL, metadata and the attribute
    dictionary visible to the client or None when no element is
    currently selected."""
    raise Exception('Interface method called')

  def getDataElementStream(self):
    """Get a stream to read from the remote data element. While
    stream is open, no other client protocol methods can be called.
    @throws Exception if no transaction is open or no current
    data element selected for transfer.
    @return an instance of ProtocolDataElementStream for reading."""
    raise Exception('Interface method called')

  def getFileInfos(self, count):
    """Get the next file infos from the remote side. This method
    is equivalent to calling nextDataElement() and getDataElementInfo()
    count times. This will also finish any currently open FileInfo
    indicating no sucessful storage to remote side."""
    raise Exception('Interface method called')

  def offerShutdown(self):
    """Offer remote side to shutdown the connection. The other
    side has to confirm the offer to allow real shutdown."""
    raise Exception('Interface method called')

  def waitForShutdown(self):
    """Wait for the remote side to offer a shutdown. As we cannot
    force remote side to offer shutdown using, this method may
    block."""
    raise Exception('Interface method called')

  def forceShutdown(self):
    """Force an immediate shutdown without prior anouncement just
    by terminating all connections and releasing all resources."""
    raise Exception('Interface method called')


class ServerProtocolInterface:
  """This is the server side protocol adapter to be provided to
  the transfer service to forward remote requests to the local
  SenderPolicy. Methods are named identically but have different
  service contract as in ClientProtocolInterface."""

  def getPolicyInfo(self):
    """Get information about the remote SenderTransferPolicy.
    The local agent may then check if the policy is compatible
    to local settings and ReceiverTransferPolicy.
    @return information about the installed SenderTransferPolicy
    or None without a policy."""
    raise Exception('Interface method called')

  def startTransaction(self, queryData):
    """Start or restart a query transaction to retrive files from
    beginning on, even when skipped in previous round. The query
    pointer is positioned before the first FileInfo to retrieve.
    @param query data received from remote side.
    @throws Exception if transation start is not possible or query
    data was not understood."""
    raise Exception('Interface method called')

  def nextDataElement(self, wasStoredFlag=False):
    """Move to the next FileInfo.
    @param wasStoredFlag if true, indicate that the previous file
    was stored successfully on local side.
    @return True if a next FileInfo is available, False otherwise."""
    raise Exception('Interface method called')

  def getDataElementInfo(self):
    """Get information about the currently selected data element.
    The method can be invoked more than once on the same data
    element. Extraction of associated stream data is only be possible
    until proceeding to the next FileInfo using nextDataElement().
    @return a tuple with the source URL, metadata and the attribute
    dictionary visible to the client or None when no element is
    currently selected."""
    raise Exception('Interface method called')

  def getDataElementStream(self):
    """Get a stream to read the currently selected data element.
    While stream is open, no other protocol methods can be called.
    @throws Exception if no transaction is open or no current
    data element selected for transfer."""
    raise Exception('Interface method called')


class SenderTransferPolicy():
  """This is the common superinterface of all sender side transfer
  policies. A policy implementation has perform internal consistency
  checks after data modification as needed, the applyPolicy call
  is only to notify policy about state changes due to transfers."""

  def getPolicyInfo(self):
    """Get information about the sender policy."""
    raise Exception('Interface method called')

  def queryBackupDataElements(self, transferContext, queryData):
    """Query the local sender transfer policy to return a query
    result with elements to be transfered to the remote side.
    @param queryData when None, return all elements to be transfered.
    Otherwise apply the policy specific query data to limit the
    number of elements.
    @return BackupDataElementQueryResult"""
    raise Exception('Interface method called')

  def applyPolicy(self, transferContext, backupDataElement, wasStoredFlag):
    """Apply this policy to adopt to changes due to access to
    the a backup data element within a storage context.
    @param backupDataElement a backup data element instance of
    StorageBackupDataElementInterface returned by the queryBackupDataElements
    method of this policy.
    @param wasStoredFlag flag indicating if the remote side also
    fetched the data of this object."""
    raise Exception('Interface method called')


class ReceiverTransferPolicy:
  """This is the common superinterface of all receiver transfer
  policies."""

  def isSenderPolicyCompatible(self, policyInfo):
    """Check if a remote sender policy is compatible to this receiver
    policy.
    @return True when compatible."""
    raise Exception('Interface method called')

  def applyPolicy(self, transferContext):
    """Apply this policy for the given transfer context. This
    method should be invoked only after checking that policies
    are compliant. The policy will then use access to remote side
    within transferContext to fetch data elements and modify local
    and possibly also remote storage."""
    raise Exception('Interface method called')


class SenderMoveDataTransferPolicy(SenderTransferPolicy):
  """This is a simple sender transfer policy just advertising
  all resources for transfer and removing them or marking them
  as transfered as soon as remote side confirms sucessful transfer.
  A file with a mark will not be offered for download any more."""

  def __init__(self, configContext, markAsDoneOnlyFlag=False):
    self.configContext = configContext
    self.markAsDoneOnlyFlag = markAsDoneOnlyFlag
    if self.markAsDoneOnlyFlag:
      raise Exception('FIXME: no persistency support for marking yet')

  def getPolicyInfo(self):
    """Get information about the sender policy."""
    return 'SenderMoveDataTransferPolicy'

  def queryBackupDataElements(self, transferContext, queryData):
    """Query the local sender transfer policy to return a query
    result with elements to be transfered to the remote side.
    @param queryData when None, return all elements to be transfered.
    Otherwise apply the policy specific query data to limit the
    number of elements.
    @return BackupDataElementQueryResult"""
    query = None
    if queryData != None:
      if not isinstance(queryData, list):
        raise Exception('Unsupported query data')
      queryType = queryData[0]
      if queryType == 'SourceUrl':
        raise Exception('Not yet')
      else:
        raise Exception('Unsupported query type')
    return transferContext.localStorage.queryBackupDataElements(query)

  def applyPolicy(self, transferContext, backupDataElement, wasStoredFlag):
    """Apply this policy to adopt to changes due to access to
    the a backup data element within a storage context.
    @param backupDataElement a backup data element instance of
    StorageBackupDataElementInterface returned by the queryBackupDataElements
    method of this policy.
    @param wasStoredFlag flag indicating if the remote side also
    fetched the data of this object."""
# When other side did not confirm receiving the data, keep this
# element active.
    if not wasStoredFlag:
      return
    if self.markAsDoneOnlyFlag:
      raise Exception('FIXME: no persistency support for marking yet')
# Remove the element from the storage.
    backupDataElement.delete()


class ReceiverStoreDataTransferPolicy(ReceiverTransferPolicy):
  """This class defines a receiver policy, that attempts to fetch
  all data elements offered by the remote transfer agent."""

  def __init__(self, configContext):
    """Create this policy using the given configuration."""
    self.configContext = configContext

  def isSenderPolicyCompatible(self, policyInfo):
    """Check if a remote sender policy is compatible to this receiver
    policy.
    @return True when compatible."""
    return policyInfo == 'SenderMoveDataTransferPolicy'

  def applyPolicy(self, transferContext):
    """Apply this policy for the given transfer context. This
    method should be invoked only after checking that policies
    are compliant. The policy will then use access to remote side
    within transferContext to fetch data elements and modify local
    and possibly also remote storage."""
# Just start a transaction and try to verify, that each remote
# element is also present in local storage.
    transferContext.clientProtocolAdapter.startTransaction(None)
    while transferContext.clientProtocolAdapter.nextDataElement(True):
      (sourceUrl, metaInfo, attributeDict) = \
          transferContext.clientProtocolAdapter.getDataElementInfo()
# Now we know about the remote object. See if it is already available
# within local storage.
      localElement = transferContext.localStorage.getBackupDataElementForMetaData(
          sourceUrl, metaInfo)
      if localElement != None:
# Element is already available, not attempting to copy.
        continue
# Create the sink to store the element.
      sinkHandle = transferContext.localStorage.getSinkHandle(sourceUrl)
      dataStream = transferContext.clientProtocolAdapter.getDataElementStream()
      while True:
        streamData = dataStream.read()
        if streamData == b'':
          break
        sinkHandle.write(streamData)
      sinkHandle.close(metaInfo)


class TransferAgent():
  """The TransferAgent keeps track of all currently open transfer
  contexts and orchestrates transfer."""

  def addConnection(self, transferContext):
    """Add a connection to the local agent."""
    raise Exception('Interface method called')

  def shutdown(self, forceShutdownTime=-1):
    """Trigger shutdown of this TransferAgent and all open connections
    established by it. The method call shall return as fast as
    possible as it might be invoked via signal handlers, that
    should not be blocked. If shutdown requires activities with
    uncertain duration, e.g. remote service acknowledging clean
    shutdown, those tasks shall be performed in another thread,
    e.g. the main thread handling the connections.
    @param forceShutdowTime when 0 this method will immediately
    end all service activity just undoing obvious intermediate
    state, e.g. deleting temporary files, but will not notify
    remote side for a clean shutdown or wait for current processes
    to complete. A value greater zero indicates the intent to
    terminate within that given amount of time."""
    raise Exception('Interface method called')


class SimpleTransferAgent(TransferAgent):
  """This is a minimalistic implementation of a transfer agent.
  It is capable of single-threaded transfers only, thus only a
  single connection can be attached to this agent."""

  def __init__(self):
    """Create the local agent."""
    self.singletonContext = None
    self.lock = threading.Lock()

  def addConnection(self, transferContext):
    """Add a connection to the local transfer agent. As this agent
    is only single threaded, the method will return only after
    this connection was closed already."""
    with self.lock:
      if self.singletonContext is not None:
        raise Exception(
            '%s cannot handle multiple connections in parallel' % (
                self.__class__.__name__))
      self.singletonContext = transferContext
    try:
      if not self.ensurePolicyCompliance(transferContext):
        print('Incompatible policies detected, shutting down', file=sys.stderr)
      elif transferContext.receiverTransferPolicy != None:
# So remote sender policy is compliant to local storage policy.
# Recheck local policy until we are done.
        transferContext.receiverTransferPolicy.applyPolicy(transferContext)

# Indicate local shutdown to other side.
      transferContext.offerShutdown()
# Await remote shutdown confirmation.
      transferContext.waitForShutdown()
    except OSError as communicationError:
      if communicationError.errno == errno.ECONNRESET:
        print('%s' % communicationError.args[1], file=sys.stderr)
      else:
        raise
    finally:
      transferContext.clientProtocolAdapter.forceShutdown()
      with self.lock:
        self.singletonContext = None

  def ensurePolicyCompliance(self, transferContext):
    """Check that remote sending policy is compliant to local
    receiver policy or both policies are not set."""
    policyInfo = transferContext.clientProtocolAdapter.getRemotePolicyInfo()
    if transferContext.receiverTransferPolicy is None:
# We are not expecting to receive anything, so remote policy can
# never match local one.
      return policyInfo is None
    return transferContext.receiverTransferPolicy.isSenderPolicyCompatible(
        policyInfo)

  def shutdown(self, forceShutdownTime=-1):
    """Trigger shutdown of this TransferAgent and all open connections
    established by it.
    @param forceShutdowTime when 0 this method will immediately
    end all service activity just undoing obvious intermediate
    state, e.g. deleting temporary files, but will not notify
    remote side for a clean shutdown or wait for current processes
    to complete. A value greater zero indicates the intent to
    terminate within that given amount of time."""
    transferContext = None
    with self.lock:
      if self.singletonContext is None:
        return
      transferContext = self.singletonContext

    if forceShutdownTime == 0:
# Immedate shutdown was requested.
      transferContext.clientProtocolAdapter.forceShutdown()
    else:
      transferContext.offerShutdown()


class DefaultTransferAgentServerProtocolAdapter(ServerProtocolInterface):
  """This class provides a default protocol adapter only relaying
  requests to the sender policy within the given transfer context."""

  def __init__(self, transferContext, remoteStorageNotificationFunction=None):
    """Create the default adapter. This adapter just publishes
    all DataElements from local storage but does not provide any
    support for attributes or element deletion.
    @param remoteStorageNotificationFunction when not None, this
    function is invoked with context, FileInfo and wasStoredFlag
    before moving to the next resource."""
    self.transferContext = transferContext
    self.remoteStorageNotificationFunction = remoteStorageNotificationFunction
    self.transactionIterator = None
    self.currentDataElement = None

  def getPolicyInfo(self):
    """Get information about the remote SenderTransferPolicy.
    The local agent may then check if the policy is compatible
    to local settings and ReceiverTransferPolicy.
    @return information about the installed SenderTransferPolicy
    or None without a policy."""
    if self.transferContext.senderTransferPolicy is None:
      return None
    return self.transferContext.senderTransferPolicy.getPolicyInfo()

  def startTransaction(self, queryData):
    """Start or restart a query transaction to retrive files from
    beginning on, even when skipped in previous round. The query
    pointer is positioned before the first FileInfo to retrieve.
    @param query data received from remote side.
    @throws exception if transation start is not possible or query
    data was not understood."""
    if self.currentDataElement != None:
      self.currentDataElement.invalidate()
      self.currentDataElement = None
    self.transactionIterator = \
        self.transferContext.senderTransferPolicy.queryBackupDataElements(
            self.transferContext, queryData)

  def nextDataElement(self, wasStoredFlag=False):
    """Move to the next FileInfo.
    @param wasStoredFlag if true, indicate that the previous file
    was stored successfully on local side.
    @return True if a next FileInfo is available, False otherwise."""
    if self.currentDataElement != None:
      self.transferContext.senderTransferPolicy.applyPolicy(
          self.transferContext, self.currentDataElement, wasStoredFlag)
      if self.remoteStorageNotificationFunction != None:
        self.remoteStorageNotificationFunction(
            self.transferContext, self.currentDataElement, wasStoredFlag)
      self.currentDataElement.invalidate()
      self.currentDataElement = None
    if self.transactionIterator is None:
      return False
    dataElement = self.transactionIterator.getNextElement()
    if dataElement is None:
      self.transactionIterator = None
      return False
    self.currentDataElement = WrappedStorageBackupDataElementFileInfo(
        dataElement)
    return True

  def getDataElementInfo(self):
    """Get information about the currently selected data element.
    The method can be invoked more than once on the same data
    element. Extraction of associated stream data is only be possible
    until proceeding to the next FileInfo using nextDataElement().
    @return a tuple with the source URL, metadata and the attribute
    dictionary visible to the client."""
    if self.currentDataElement is None:
      return None
    return (self.currentDataElement.getSourceUrl(), self.currentDataElement.getMetaInfo(), None)

  def getDataElementStream(self):
    """Get a stream to read the currently selected data element.
    While stream is open, no other protocol methods can be called.
    @throws Exception if no transaction is open or no current
    data element selected for transfer."""
    if self.currentDataElement is None:
      raise Exception('No data element selected')
    return self.currentDataElement.getDataStream()


class WrappedStorageBackupDataElementFileInfo():
  """This is a simple wrapper over a a StorageBackupDataElement
  to retrieve requested data directly from storage. It does not
  support any attributes as those are usually policy specific."""
  def __init__(self, dataElement):
    if not isinstance(dataElement, guerillabackup.StorageBackupDataElementInterface):
      raise Exception('Cannot wrap object not implementing StorageBackupDataElementInterface')
    self.dataElement = dataElement

  def getSourceUrl(self):
    """Get the source URL of this file object."""
    return self.dataElement.getSourceUrl()

  def getMetaInfo(self):
    """Get only the metadata part of this element.
    @return a BackupElementMetainfo object"""
    return self.dataElement.getMetaData()

  def getAttributes(self):
    """Get the additional attributes of this file info object.
    Currently attributes are not supported for wrapped objects."""
    return None

  def setAttribute(self, name, value):
    """Set an attribute for this file info."""
    raise Exception('Not supported')

  def getDataStream(self):
    """Get a stream to read data from that element.
    @return a file descriptor for reading this stream."""
    return self.dataElement.getDataStream()

  def delete(self):
    """Delete the backup data element behind this object."""
    self.dataElement.delete()
    self.dataElement = None

  def invalidate(self):
    """Make sure all resources associated with this element are
    released.
    @throws Exception if element is currently in use, e.g. read."""
# Nothing to invalidate here when using primitive, uncached wrapping.
    pass


class MultipartResponseIterator():
  """This is the interface for all response iterators. Those should
  be used, where the response is too large for a single response
  data block or where means for interruption of an ongoing large
  response are needed."""

  def getNextPart(self):
    """Get the next part from this iterator. After detecting
    that no more parts are available or calling release(), the
    caller must not attempt to invoke the method again.
    @return the part data or None when no more parts are available."""
    raise Exception('Interface method called')

  def release(self):
    """This method releases all resources associated with this
    iterator if the iterator end was not yet reached in getNextPart().
    All future calls to getNextPart() or release() will cause
    exceptions."""
    raise Exception('Interface method called')


class StreamRequestResponseMultiplexer():
  """This class allows to send requests and reponses via a single
  bidirectional in any connection. The class is not thread-safe
  and hence does not support concurrent method calls. The transfer
  protocol consists of a few packet types:
  * 'A' for aborting a running streaming request.
  * 'S' for sending a request to the remote side server interface
  * 'P' for stream response parts before receiving a final 'R'
    packet. Thus a 'P' packet identifies a stream response. Therefore
    for zero byte stream responses, there has to be at least a
    single 'P' package of zero zero size. The final 'R' packet
    at the end of the stream has to be always of zero size.
  * 'R' for the remote response packet containing the response
    data.
  Any exception due to protocol violations, multiplex connection
  IO errors or requestHandler processing failures will cause the
  multiplexer to shutdown all functionality immediately for security
  reasons."""
  def __init__(self, inputFd, outputFd, requestHandler):
    """Create this multiplexer based on the given input and output
    file descriptors.
    @param requestHandler a request handler to process the incoming
    requests."""
    self.inputFd = inputFd
    self.outputFd = outputFd
    self.requestHandler = requestHandler
# This flag stays true until the response for the last request
# was received.
    self.responsePendingFlag = False
# When true, this multiplexer is currently receiving a stream
# response from the remote side.
    self.inStreamResponseFlag = False
# This iterator will be none when an incoming request is returning
# a group of packets as response.
    self.responsePartIterator = None
    self.shutdownOfferSentFlag = False
    self.shutdownOfferReceivedFlag = False
# Input buffer of data from remote side.
    self.remoteData = b''
    self.remoteDataLength = -1

  def sendRequest(self, requestData):
    """Send request data to the remote side and await the result.
    The method will block until the remote data was received and
    will process incoming requests while waiting. The method relies
    on the caller to have fetched all continuation response parts
    for the previous requests using handleRequests, before submitting
    a new request.
    @rais Exception if multiplexer is in invalid state.
    @return response data when a response was pending and data
    was received within time. The data is is a tuple containing
    the binary content and a boolean value indicating if the received
    data is a complete response or belonging to a stream."""
    if (requestData is None) or (len(requestData) == 0):
      raise Exception('No request data given')
    if self.responsePendingFlag:
      raise Exception('Cannot queue another request while response is pending')
    if self.shutdownOfferSentFlag:
      raise Exception('Shutdown already offered')
    return self.internalIOHandler(requestData, 1000)

  def handleRequests(self, selectTime):
    """Handle incoming requests by waiting for incoming data for
    the given amount of time.
    @return None when only request handling was performed, the
    no-response continuation data for the last request if received."""
    if ((self.shutdownOfferSentFlag) and (self.shutdownOfferReceivedFlag) and
        not self.responsePendingFlag):
      raise Exception('Cannot handle requests after shutdown')
    return self.internalIOHandler(None, selectTime)

  def offerShutdown(self):
    """Offer the shutdown to the remote side. This method has
    the same limitations and requirements as the sendRequest method.
    It does not return any data."""
    if self.shutdownOfferSentFlag:
      raise Exception('Already offered')
    self.shutdownOfferSentFlag = True
    result = self.internalIOHandler(b'', 600)
    if result[1]:
      raise Exception('Received unexpected stream response')
    if len(result[0]) != 0:
      raise Exception('Unexpected response data on shutdown offer request')

  def wasShutdownOffered(self):
    """Check if shutdown was already offered by this side."""
    return self.shutdownOfferSentFlag

  def wasShutdownRequested(self):
    """Check if remote side has alredy requested shutdown."""
    return self.shutdownOfferReceivedFlag

  def close(self):
    """Close this multiplexer by closing also all underlying streams."""
    if self.inputFd == -1:
      raise Exception('Already closed')
# We were currently transfering stream parts when being shutdown.
# Make sure to release the iterator to avoid resource leaks.
    if self.responsePartIterator != None:
      self.responsePartIterator.release()
      self.responsePartIterator = None

    pendingException = None
    try:
      os.close(self.inputFd)
    except Exception as closeException:
# Without any program logic errors, exceptions here are rare
# and problematic, therefore report them immediately.
      print(
          'Closing of input stream failed: %s' % str(closeException),
          file=sys.stderr)
      pendingException = closeException
    if self.outputFd != self.inputFd:
      try:
        os.close(self.outputFd)
      except Exception as closeException:
        print(
            'Closing of output stream failed: %s' % str(closeException),
            file=sys.stderr)
        pendingException = closeException
    self.inputFd = -1
    self.outputFd = -1
    self.shutdownOfferSentFlag = True
    self.shutdownOfferReceivedFlag = True
    if pendingException != None:
      raise pendingException

  def internalIOHandler(self, requestData, maxHandleTime):
    """Perform multiplexer IO operations. When requestData was
    given, it will be sent before waiting for a response and probably
    handling incoming requests.
    @param maxHandleTime the maximum time to stay inside this
    function waiting for input data. When 0, attempt to handle
    only data without blocking. Writing is not affected by this
    parameter and will be attempted until successful or fatal
    error was detected.
    @return response data when a response was pending and data
    was received within time. The data is is a tuple containing
    the binary content and a boolean value indicating if the received
    data is a complete response or belonging to a stream.
    @throws OSError when lowlevel IO communication with the remote
    peer failed or was ended prematurely.
    @throws Exception when protocol violations were detected."""
    sendQueue = []
    writeSelectFds = []
    if requestData is None:
      if self.shutdownOfferReceivedFlag and not self.inStreamResponseFlag:
        raise Exception(
            'Request handling attempted after remote shutdown was offered')
    else:
      sendQueue.append([b'S'+struct.pack('<I', len(requestData)), 0])
      self.responsePendingFlag = True
      if len(requestData) != 0:
        sendQueue.append([requestData, 0])
      writeSelectFds = [self.outputFd]
# Always await data, no matter if we are sending a request. Without
# requestData we are waiting for incoming data. When remote side
# already offered shutdown, sending more data will raise an exception
# due to protocol violation.
    readSelectFds = [self.inputFd]
    responseData = None

    ioHandledFlag = True
    nextSelectTime = maxHandleTime
    selectEndTime = time.time()+maxHandleTime
    while True:
      if (self.shutdownOfferReceivedFlag and (len(writeSelectFds) == 0) and
          not self.responsePendingFlag):
# Sendqueue must have been drained and no more requests to await.
        break
      if not ioHandledFlag:
        nextSelectTime = selectEndTime-time.time()
        if nextSelectTime < 0:
          if len(writeSelectFds):
# Always complete sending of data.
            nextSelectTime = 1.0
          else:
            break

      readFds, writeFds, errorFds = select.select(
          readSelectFds, writeSelectFds, [], nextSelectTime)
      ioHandledFlag = False
# writeFds may only contain the filedescriptor for data sending.
      if len(writeFds):
        self.internalIOWrite(sendQueue, writeSelectFds)
        ioHandledFlag = True

# readFds may only contain the filedescriptor for data reading.
      if len(readFds):
        stayInLoopFlag, readIoHandledFlag, interimResponseData = \
            self.internalIORead(readSelectFds, writeSelectFds, sendQueue)
        if interimResponseData != None:
          if responseData != None:
            raise Exception('Logic flaw')
          responseData = interimResponseData
        if readIoHandledFlag:
          ioHandledFlag = True
        if not stayInLoopFlag:
          break
    return responseData

  def internalIORead(self, readSelectFds, writeSelectFds, sendQueue):
    """This method handles response data for the current request
    or another remote request to be received. Make sure not to
    overread the response.
    @param sendQueue when receiving e.g. shutdown requests, packets
    have to be added to the queue.
    @return a tuple with flag indicating if IO handling attempts
    should continue, one if IO was really performed in internalIORead
    and the reponseData to return to the client when leaving the
    IO handling."""
    if self.remoteDataLength < 0:
      readData = os.read(self.inputFd, 5-len(self.remoteData))
      if len(readData) == 0:
        if self.responsePendingFlag:
          raise OSError(
              errno.ECONNRESET, 'End of data while awaiting response')
        if len(self.remoteData) != 0:
          raise Exception('End of data with partial input')
# From here on, cannot read from closed descriptor anyway.
        del readSelectFds[0]
        if len(writeSelectFds) == 0:
# So this is the end of the stream. If shutdown negotiated was
# not performed as specified by the protocol, then consider that
# an unexpected connection shutdown.
          if (not(self.wasShutdownOffered()) or
              not self.wasShutdownRequested()):
            raise OSError(
                errno.ECONNRESET,
                'End of stream without shutdown negotiation')
          return (False, False, None)
# Reading is dead, but there might be the final packet of shutdown
# negotiation to be sent yet. Therefore continue IO handling.
        return (True, False, None)

# So this was a normal read. Process the received data.
      self.remoteData += readData
      if len(self.remoteData) < 5:
# Still not enough, retry immediately.
        return (True, True, None)

      self.remoteDataLength = struct.unpack('<I', self.remoteData[1:5])[0]
      if (self.remoteDataLength < 0) or (self.remoteDataLength > (1<<20)):
        raise Exception('Invalid input data chunk length 0x%x' % self.remoteDataLength)
      self.remoteDataLength += 5
      if self.remoteDataLength != 5:
# We read exactly 5 bytes but need more. Let the outer loop do that.
        return (True, True, None)
    if len(self.remoteData) < self.remoteDataLength:
      readData = os.read(
          self.inputFd, self.remoteDataLength-len(self.remoteData))
      if len(readData) == 0:
        if self.responsePendingFlag:
          raise Exception('End of data while awaiting response')
        raise Exception('End of data with partial input')
      self.remoteData += readData
    if len(self.remoteData) != self.remoteDataLength:
      return (True, True, None)

# Check the code.
    if self.remoteData[0] not in b'PRS':
      raise Exception('Invalid packet type 0x%x' % self.remoteData[0])

    if not self.remoteData.startswith(b'S'):
# Not sending a request but receiving some kind of response.
      if not self.responsePendingFlag:
        raise Exception(
            'Received %s packet while not awaiting response' % repr(self.remoteData[0:1]))
      if self.remoteData.startswith(b'P'):
# So this is the first or an additional fragment for a previous response.
        self.inStreamResponseFlag = True
      else:
        self.responsePendingFlag = False
        self.inStreamResponseFlag = False
      responseData = (self.remoteData[5:], self.inStreamResponseFlag)
      self.remoteData = b''
      self.remoteDataLength = -1
# We could receive multiple response packets while sendqueue was
# not yet flushed containing outgoing responses to requests processed.
# Although all those responses would belong to the same request,
# fusion is not an option to avoid memory exhaustion. So we have
# to delay returning of response data until sendqueue is emptied.
      return (len(sendQueue) != 0, True, responseData)

# So this was another incoming request. Handle it and queue the
# response data.
    if self.responsePartIterator != None:
      raise Exception(
          'Cannot handle additional request while previous one not done')
    if self.shutdownOfferReceivedFlag:
      raise Exception('Received request even after shutdown was offered')

    if self.remoteDataLength == 5:
# This is a remote shutdown offer, the last request from the remote
# side. Prepare for shutdown.
      self.shutdownOfferReceivedFlag = True
      sendQueue.append([b'R\x00\x00\x00\x00', 0])
      if not self.responsePendingFlag:
        del readSelectFds[0]
    else:
      handlerResponse = self.requestHandler.handleRequest(
          self.remoteData[5:])
      handlerResponseType = b'R'
      if isinstance(handlerResponse, MultipartResponseIterator):
        self.responsePartIterator = handlerResponse
        handlerResponse = handlerResponse.getNextPart()
        handlerResponseType = b'P'
# Empty files might not even return a single part. But stream
# responses have to contain at least one 'P' type packet, so send
# an empty one.
        if handlerResponse is None:
          handlerResponse = b''
      sendQueue.append([handlerResponseType+struct.pack('<I', len(handlerResponse)), 0])
# Add response as separate packet. It might be last, thus this
# will avoid an additional memory buffer copy operation.
      sendQueue.append([handlerResponse, 0])
    writeSelectFds[:] = [self.outputFd]
    self.remoteData = b''
    self.remoteDataLength = -1
    return (True, True, None)

  def internalIOWrite(self, sendQueue, writeSelectFds):
    """Try to write the data from the first queue item to the
    stream."""
    sendItem = sendQueue[0]
    offset = sendItem[1]
    writeResult = os.write(self.outputFd, sendItem[0][offset:])+offset
    if writeResult == len(sendItem[0]):
      del sendQueue[0]
      if (len(sendQueue) == 0) and (self.responsePartIterator != None):
        nextPart = self.responsePartIterator.getNextPart()
        if nextPart is None:
          sendQueue.append([b'R\x00\x00\x00\x00', 0])
# Just remove the iterator, all resources were already released
# in the getNextPart() method.
          self.responsePartIterator = None
        else:
          sendQueue.append([b'P'+struct.pack('<I', len(nextPart)), 0])
          sendQueue.append([nextPart, 0])
    else:
      sendItem[1] = writeResult
    if len(sendQueue) == 0:
      del writeSelectFds[0]

class JsonClientProtocolDataElementStream(ProtocolDataElementStream):
  """This is an implementation of the stream interface to work
  ontop of the JsonStreamClientProtocolAdapter."""

  def __init__(self, clientProtocolAdapter):
    self.clientProtocolAdapter = clientProtocolAdapter
    self.startStreamFlag = True
    self.dataBuffer = None
    self.endOfStreamFlag = False

  def read(self, readLength=0):
    """Read data from the current data element.
    @param readLength if not zero, return a chunk of data with
    at most the given length. When zero, return chunks with the
    default size of the underlying IO layer.
    @return the amount of data read or an empty string when end
    of stream was reached."""
    if self.endOfStreamFlag:
      raise Exception('Invalid state')
    result = None
    if self.dataBuffer != None:
      if readLength == 0:
        result = self.dataBuffer
        self.dataBuffer = None
      else:
        result = self.dataBuffer[:readLength]
        if len(self.dataBuffer) <= readLength:
          self.dataBuffer = None
        else:
          self.dataBuffer = self.dataBuffer[readLength:]
    else:
# Read fresh data.
      result = self.clientProtocolAdapter.internalReadDataStream(
          startStreamFlag=self.startStreamFlag)
      self.startStreamFlag = False
      if (readLength != 0) and (len(result) > readLength):
        self.dataBuffer = result[readLength:]
        result = result[:readLength]
    if len(result) == 0:
      self.endOfStreamFlag = True
    return result

  def close(self):
    """Close the stream. This call might discard data already
    buffered within this object or the underlying IO layer. This
    method has to be invoked also when the end of the stream was
    reached."""
    if self.endOfStreamFlag:
      return
    self.clientProtocolAdapter.__internalStreamAbort()
    self.endOfStreamFlag = True


class JsonStreamClientProtocolAdapter(ClientProtocolInterface):
  """This class forwards client protocol requests via stream file
  descriptors to the remote side."""

  def __init__(self, streamMultiplexer):
    """Create this adapter based on the given input and output
    file descriptors."""
    self.streamMultiplexer = streamMultiplexer
    self.inStreamReadingFlag = False

  def getRemotePolicyInfo(self):
    """Get information about the remote policy. The local agent
    may then check if remote SenderTransferPolicy is compatible
    to local settings and ReceiverTransferPolicy.
    @return information about the remote sender policy or None
    when no sender policy is installed, thus requesting remote
    files is impossible."""
    if self.inStreamReadingFlag:
      raise Exception('Illegal state')
    (responseData, inStreamReadingFlag) = self.streamMultiplexer.sendRequest(
        bytes(json.dumps(['getPolicyInfo']), 'ascii'))
    if inStreamReadingFlag:
      raise Exception('Protocol error')
    return json.loads(str(responseData, 'ascii'))

  def startTransaction(self, queryData):
    """Start or restart a query transaction to retrive files from
    beginning on, even when skipped in previous round. The query
    pointer is positioned before the first FileInfo to retrieve.
    @param query data to send as query to remote side.
    @throws exception if transation start is not possible or query
    data was not understood by remote side."""
    if self.inStreamReadingFlag:
      raise Exception('Illegal state')
    (responseData, inStreamReadingFlag) = self.streamMultiplexer.sendRequest(
        bytes(json.dumps(['startTransaction', queryData]), 'ascii'))
    if inStreamReadingFlag:
      raise Exception('Protocol error')
    if len(responseData) != 0:
      raise Exception('Unexpected response received')

  def nextDataElement(self, wasStoredFlag=False):
    """Move to the next FileInfo.
    @param wasStoredFlag if true, indicate that the previous file
    was stored successfully on local side.
    @return True if a next FileInfo is available, False otherwise."""
    if self.inStreamReadingFlag:
      raise Exception('Illegal state')
    (responseData, inStreamReadingFlag) = self.streamMultiplexer.sendRequest(
        bytes(json.dumps(['nextDataElement', wasStoredFlag]), 'ascii'))
    if inStreamReadingFlag:
      raise Exception('Protocol error')
    return json.loads(str(responseData, 'ascii'))

  def getDataElementInfo(self):
    """Get information about the currently selected FileInfo.
    Extraction of information and stream may only be possible
    until proceeding to the next FileInfo using nextDataElement().
    @return a tuple with the source URL, metadata and the attribute
    dictionary visible to the client."""
    if self.inStreamReadingFlag:
      raise Exception('Illegal state')
    (responseData, inStreamReadingFlag) = self.streamMultiplexer.sendRequest(
        bytes(json.dumps(['getDataElementInfo']), 'ascii'))
    if inStreamReadingFlag:
      raise Exception('Protocol error')
    result = json.loads(str(responseData, 'ascii'))
    result[1] = BackupElementMetainfo.unserialize(
        bytes(result[1], 'ascii'))
    return result

  def getDataElementStream(self):
    """Get a stream to read from currently selected data element.
    While stream is open, no other protocol methods can be called.
    @throws Exception if no transaction is open or no current
    data element selected for transfer."""
    self.inStreamReadingFlag = True
    return JsonClientProtocolDataElementStream(self)

  def getFileInfos(self, count):
    """Get the next file infos from the remote side. This method
    is equivalent to calling nextDataElement() and getDataElementInfo()
    count times. This will also finish any currently open FileInfo
    indicating no sucessful storage to remote side."""
    raise Exception('Interface method called')

  def offerShutdown(self):
    """Offer remote side to shutdown the connection. The other
    side has to confirm the offer to allow real shutdown."""
    if self.inStreamReadingFlag:
      raise Exception('Illegal state')
    self.streamMultiplexer.offerShutdown()

  def waitForShutdown(self):
    """Wait for the remote side to offer a shutdown. As we cannot
    force remote side to offer shutdown using the given multiplex
    mode, just wait until we receive the offer."""
    while not self.streamMultiplexer.shutdownOfferReceivedFlag:
      responseData = self.streamMultiplexer.handleRequests(600)
      if responseData != None:
        raise Exception(
            'Did not expect to receive data while waiting for shutdown')
    self.streamMultiplexer.close()
    self.streamMultiplexer = None

  def forceShutdown(self):
    """Force an immediate shutdown without prior anouncement just
    by terminating all connections and releasing all resources."""
    if self.streamMultiplexer != None:
      self.streamMultiplexer.close()
      self.streamMultiplexer = None

  def internalReadDataStream(self, startStreamFlag=False):
    """Read a remote backup data element as stream."""
    if not self.inStreamReadingFlag:
      raise Exception('Illegal state')
    responseData = None
    inStreamReadingFlag = None
    if startStreamFlag:
      (responseData, inStreamReadingFlag) = self.streamMultiplexer.sendRequest(
          bytes(json.dumps(['getDataElementStream']), 'ascii'))
      if not inStreamReadingFlag:
        raise Exception('Protocol error')
    else:
      (responseData, inStreamReadingFlag) = self.streamMultiplexer.handleRequests(1000)
      if inStreamReadingFlag != (len(responseData) != 0):
        raise Exception('Protocol error')
    if len(responseData) == 0:
# So this was the final chunk, switch to normal non-stream mode again.
      self.inStreamReadingFlag = False
    return responseData

  def __internalStreamAbort(self):
    """Abort reading of the data stream currently open for reading."""
    if not self.inStreamReadingFlag:
      raise Exception('Illegal state')
# This is an exception to the normal client/server protocol: send
# the abort request even while the current request is still being
# processed.
    (responseData, inStreamReadingFlag) = self.streamMultiplexer.sendRequest(
        bytes(json.dumps(['abortDataElementStream']), 'ascii'))
# Now continue reading until all buffers have drained and final
# data chunk was removed.
    while len(self.internalReadDataStream()) != 0:
      pass
# Now read the response to the abort command itself.
    (responseData, inStreamReadingFlag) = self.streamMultiplexer.sendRequest(None)
    if len(responseData) != 0:
      raise Exception('Unexpected response received')


class WrappedFileStreamMultipartResponseIterator(MultipartResponseIterator):
  """This class wraps an OS stream to provide the data as response
  iterator."""

  def __init__(self, streamFd, chunkSize=1<<16):
    self.streamFd = streamFd
    self.chunkSize = chunkSize

  def getNextPart(self):
    """Get the next part from this iterator. After detecting
    that no more parts are available or calling release(), the
    caller must not attempt to invoke the method again.
    @return the part data or None when no more parts are available."""
    if self.streamFd < 0:
      raise Exception('Illegal state')
    readData = os.read(self.streamFd, self.chunkSize)
    if len(readData) == 0:
# This is the end of the stream, we can release it.
      self.release()
      return None
    return readData

  def release(self):
    """This method releases all resources associated with this
    iterator if the iterator end was not yet reached in getNextPart().
    All future calls to getNextPart() or release() will cause
    exceptions."""
    if self.streamFd < 0:
      raise Exception('Illegal state')
    os.close(self.streamFd)
    self.streamFd = -1


class JsonStreamServerProtocolRequestHandler():
  """This class handles incoming requests encoded in JSON and
  passes them on to a server protocol adapter."""

  def __init__(self, serverProtocolAdapter):
    self.serverProtocolAdapter = serverProtocolAdapter

  def handleRequest(self, requestData):
    """Handle an incoming request.
    @return the serialized data."""
    request = json.loads(str(requestData, 'ascii'))
    if not isinstance(request, list):
      raise Exception('Unexpected request data')
    requestMethod = request[0]
    responseData = None
    noResponseFlag = False
    if requestMethod == 'getPolicyInfo':
      responseData = self.serverProtocolAdapter.getPolicyInfo()
    elif requestMethod == 'startTransaction':
      self.serverProtocolAdapter.startTransaction(request[1])
      noResponseFlag = True
    elif requestMethod == 'nextDataElement':
      responseData = self.serverProtocolAdapter.nextDataElement(request[1])
    elif requestMethod == 'getDataElementInfo':
      elementInfo = self.serverProtocolAdapter.getDataElementInfo()
# Meta information needs separate serialization, do it.
      if elementInfo != None:
        responseData = (elementInfo[0], str(elementInfo[1].serialize(), 'ascii'), elementInfo[2])
    elif requestMethod == 'getDataElementStream':
      responseData = WrappedFileStreamMultipartResponseIterator(
          self.serverProtocolAdapter.getDataElementStream())
    else:
      raise Exception('Invalid request %s' % repr(requestMethod))
    if noResponseFlag:
      return b''
    if isinstance(responseData, MultipartResponseIterator):
      return responseData
    return bytes(json.dumps(responseData), 'ascii')


class SocketConnectorService():
  """This class listens on a socket and creates a TransferContext
  for each incoming connection."""

  def __init__(
      self, socketPath, receiverTransferPolicy, senderTransferPolicy,
      localStorage, transferAgent):
    """Create this service to listen on the given path.
    @param socketPath the path where to create the local UNIX
    socket. The service will not create the directory required
    to hold the socket but will unlink any preexisting socket
    file with that path. This operation is racy and might cause
    security issues when applied by privileged user on insecure
    directories."""
    self.socketPath = socketPath
    self.receiverTransferPolicy = receiverTransferPolicy
    self.senderTransferPolicy = senderTransferPolicy
    self.localStorage = localStorage
    self.transferAgent = transferAgent
# The local socket to accept incoming connections. The only place
# to close the socket is in the shutdown method to avoid concurrent
# close in main loop.
    self.socket = None
    self.isRunningFlag = False
    self.shutdownFlag = False

    self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
      self.socket.bind(self.socketPath)
    except socket.error as bindError:
      if bindError.errno != errno.EADDRINUSE:
        raise
# Try to unlink the old socket and retry creation.
      os.unlink(self.socketPath)
      self.socket.bind(self.socketPath)

    os.chmod(self.socketPath, 0x180)

  def run(self):
    """Run this connector service. The method will not return until
    shutdown is requested by another thread."""
# Keep a local copy of the server socket to avoid races with
# asynchronous shutdown signals.
    serverSocket = self.socket
    if self.shutdownFlag or (serverSocket is None):
      raise Exception('Already shutdown')

    self.isRunningFlag = True
    serverSocket.listen(4)
    while not self.shutdownFlag:
      clientSocket = None
      remoteAddress = None
      try:
        (clientSocket, remoteAddress) = serverSocket.accept()
      except OSError as acceptError:
        if (acceptError.errno != errno.EINVAL) or (not self.shutdownFlag):
          print(
              'Unexpected error %s accepting new connections' % acceptError,
              file=sys.stderr)
        continue
      transferContext = TransferContext(
          'socket', self.receiverTransferPolicy,
          self.senderTransferPolicy, self.localStorage)
      serverProtocolAdapter = DefaultTransferAgentServerProtocolAdapter(
          transferContext)
# Extract a duplicate of the socket file descriptor. This is needed
# as the clientSocket might be garbage collected any time, thus
# closing the file descriptors while still needed.
      clientSocketFd = os.dup(clientSocket.fileno())
      streamMultiplexer = StreamRequestResponseMultiplexer(
          clientSocketFd, clientSocketFd,
          JsonStreamServerProtocolRequestHandler(serverProtocolAdapter))
# Do not wait for garbage collection, release the object immediately.
      clientSocket.close()
      transferContext.connect(
          JsonStreamClientProtocolAdapter(streamMultiplexer),
          serverProtocolAdapter)
      self.transferAgent.addConnection(transferContext)
    self.isRunningFlag = False

  def shutdown(self, forceShutdownTime=-1):
    """Shutdown this connector service and all open connections
    established by it. This method is usually called by a signal
    handler as it will take down the whole service including all
    open connections. The method might be invoked more than once
    to force immediate shutdown after a previous attempt with
    timeout did not complete yet.
    @param forceShutdowTime when 0 this method will immediately
    end all service activity just undoing obvious intermediate
    state, e.g. deleting temporary files, but will not notify
    remote side for a clean shutdown or wait for current processes
    to complete. A value greater zero indicates the intent to
    terminate within that given amount of time."""
# Close the socket. This will also interrupt any other thread
# in run method if it was currently waiting for new connections.
    if not self.shutdownFlag:
      self.socket.shutdown(socket.SHUT_RDWR)
      os.unlink(self.socketPath)
      self.socketPath = None

# Indicate main loop termination on next possible occasion.
    self.shutdownFlag = True

# Shutdown all open connections.
    self.transferAgent.shutdown(forceShutdownTime)
