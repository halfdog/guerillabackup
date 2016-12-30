"""This module contains a collection of interfaces and classes
for agent-based transfer and synchronization."""

import errno
import json
import os
import select
import socket
import struct
import sys
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
  def __init__(self, agentId, receiverTransferPolicy, senderTransferPolicy,
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
    self.clientProtocolAdapter = clientProtocolAdapter
    self.serverProtocolAdapter = serverProtocolAdapter

  def offerShutdown(self):
    if self.clientProtocolAdapter == None:
      raise Exception('Cannot offer shutdown while not connected')
    if self.shutdownOfferedFlag:
      raise Exception('Shutdown already offered')
    self.clientProtocolAdapter.offerShutdown()
    self.shutdownOfferedFlag = True

  def waitForShutdown(self):
    if self.shutdownAcceptedFlag:
      return
    self.clientProtocolAdapter.waitForShutdown()
    self.shutdownAcceptedFlag = True

  def isShutdownAccepted(self):
    return self.shutdownAcceptedFlag


class PolicyViolationException(Exception):
  def __init__(self, message, errorAttributeDict):
    """@param errorAttributeDict when not None, try to set those
    attributes in remote TransferAgent. This is useful to control
    behaviour on other sides to resolve the failure, e.g. remove
    the problematic element from being listed in the next run."""
    Exception.__init__(self, message)
    self.errorAttributeDict = errorAttributeDict


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
    dictionary visible to the client."""
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
    @return a tuple with the metadata and the attribute dictionary
    visible to the client."""
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
      (sourceUrl, metaInfo, attributeDict) = transferContext.clientProtocolAdapter.getDataElementInfo()
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
        if streamData == '':
          break
        sinkHandle.write(streamData)
      sinkHandle.close(metaInfo)


class TransferAgent():
  """The TransferAgent keeps track of all currently open transfer
  contexts and orchestrates transfer."""
  def addConnection(self, transferContext):
    """Add a connection to the local agent."""
    raise Exception('Interface method called')


class SimpleTransferAgent(TransferAgent):
  """This is a minimalistic implementation of a transfer agent.
  It is capable of single-threaded transfers only, thus only a
  single connection can be attached to this agent."""

  def __init__(self):
    """Create the local agent."""
    pass

  def addConnection(self, transferContext):
    """Add a connection to the local transfer agent. As this agent
    is only single threaded, the method will return only after
    this connection was closed already."""
    try:
      if not self.ensurePolicyCompliance(transferContext):
        print >>sys.stderr, 'Incompatible policies detected, shutting down'
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
        print >>sys.stderr, '%s' % communicationError[1]
      else:
        raise
    finally:
      transferContext.clientProtocolAdapter.forceShutdown()

  def ensurePolicyCompliance(self, transferContext):
    """Check that remote sending policy is compliant to local
    receiver policy or both policies are not set."""
    policyInfo = transferContext.clientProtocolAdapter.getRemotePolicyInfo()
    if transferContext.receiverTransferPolicy == None:
# We are not expecting to receive anything, so remote policy can
# never match local one.
      return policyInfo == None
    return transferContext.receiverTransferPolicy.isSenderPolicyCompatible(
        policyInfo)


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
    if self.transferContext.senderTransferPolicy == None:
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
    self.transactionIterator = self.transferContext.senderTransferPolicy.queryBackupDataElements(self.transferContext, queryData)

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
    if self.transactionIterator == None:
      return False
    dataElement = self.transactionIterator.getNextElement()
    if dataElement == None:
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
    if self.currentDataElement == None:
      return None
    return (self.currentDataElement.getSourceUrl(), self.currentDataElement.getMetaInfo(), None)

  def getDataElementStream(self):
    """Get a stream to read the currently selected data element.
    While stream is open, no other protocol methods can be called.
    @throws Exception if no transaction is open or no current
    data element selected for transfer."""
    if self.currentDataElement == None:
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
    """Get only the metadata part of this element"""
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
# FIXME: No real in-use test yet.
    pass


class MultipartResponseIterator():
  """This is the interface for all response iterators. Those should
  be used, where the response is too large for a single response
  data block or where means for interruption of an ongoing large
  response are needed."""
  def getNextPart(self):
    """Get the next part from this iterator.
    @return the part data or None when no more parts are available."""
    raise Exception('Interface method called')


class MultiplexerResponseReceiverStream():
  """This class implements a receiver side for stream response
  reading."""

  def __init__(self, streamMultiplexer, requestData):
    """Start reading a remote stream."""
    self.streamMultiplexer = streamMultiplexer
    (self.dataBuffer, inStreamReadingFlag) = streamMultiplexer.sendRequest(
        requestData)
    if not inStreamReadingFlag:
      raise Exception('Expected stream reading but got normal response')
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
# Read more data.
      responseData = None
      while True:
        (responseData, inStreamReadingFlag) = self.streamMultiplexer.internalIOHandler(None, 600)
        if inStreamReadingFlag:
          if len(responseData) != 0:
            break
        else:
          if len(responseData) != 0:
            raise Exception('Protocol error')
          break
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

# This is an exception to the normal client/server protocol: send
# the abort request even while the current request is still being
# processed.
    self.streamMultiplexer.abortStreamRequest()
# Now continue reading until all buffers have drained and final
# data chunk was removed.
    while len(self.read()) != 0:
      pass
# Now read the response to the abort command itself.
    (responseData, inStreamReadingFlag) = self.streamMultiplexer.sendRequest(
        None)
    if inStreamReadingFlag:
      raise Exception('Protocol error')
    if len(responseData) != 0:
      raise Exception('Unexpected response received')
    self.endOfStreamFlag = True


class StreamRequestResponseMultiplexer():
  """This class allows to send requests and reponses via a single
  bidirectional in any connection. The class is not thread-safe
  and hence does not support concurrent method calls. The transfer
  protocol consists of a few packet types:
  * 'A' for aborting a running streaming request.
  * 'S' for sending a request to the remote side server interface
  * 'P' for stream response parts before receiving a final 'R'
    packet. There has to be at least a single 'P package for a
    stream response, even when that packet has zero size. The
    final 'R' packet has always to be of zero size.
  * 'R' for the remote response packet containing the response
    data."""
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
    @return a tuple with the data and the response ID. The response
    ID will stay the same for the initial response packet and
    all no-response continuation packets."""
    if (requestData == None) or (len(requestData) == 0):
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
    pendingException = None
    try:
      os.close(self.inputFd)
    except Exception as closeException:
      print >>sys.stderr, 'Closing of input stream failed'
      pendingException = closeException
    if self.outputFd != self.inputFd:
      try:
        os.close(self.outputFd)
      except Exception as closeException:
        print >>sys.stderr, 'Closing of output stream failed'
        pendingException = closeException
    self.inputFd = -1
    self.outputFd = -1
    self.shutdownOfferSentFlag = True
    self.shutdownOfferReceivedFlag = True
    if pendingException != None:
      raise

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
    if requestData == None:
      if self.shutdownOfferReceivedFlag and not self.inStreamResponseFlag:
        raise Exception(
            'Request handling attempted after remote shutdown was offered')
    else:
      sendQueue.append([b'S'+struct.pack('<I', len(requestData)), 0])
      self.responsePendingFlag = True
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
# Sendqueue must have been drained and no more quests to await.
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
      if len(writeFds):
        sendItem = sendQueue[0]
        offset = sendItem[1]
        writeResult = os.write(self.outputFd, sendItem[0][offset:])+offset
        if writeResult == len(sendItem[0]):
          del sendQueue[0]
          if len(sendQueue) == 0:
            if self.responsePartIterator != None:
              nextPart = self.responsePartIterator.getNextPart()
              if nextPart == None:
                sendQueue.append([b'R\x00\x00\x00\x00', 0])
                self.responsePartIterator = None
              else:
                sendQueue.append([b'P'+struct.pack('<I', len(nextPart)), 0])
                sendQueue.append([nextPart, 0])
            else:
              writeSelectFds = []
        else:
          sendItem[1] = writeResult
        ioHandledFlag = True

      if len(readFds):
# There is response data for the current request or another remote
# request to be received. Make sure not to overread the response.
        if self.remoteDataLength < 0:
          readData = os.read(self.inputFd, 5-len(self.remoteData))
          if len(readData) == 0:
            if self.responsePendingFlag:
              raise OSError(
                  errno.ECONNRESET, 'End of data while awaiting response')
            if len(self.remoteData) != 0:
              raise Exception('End of data with partial input')
# From here on, cannot read from closed descriptor anyway.
            readSelectFds = []
            if len(writeSelectFds) == 0:
# So this is the end of the stream. If shutdown negotiated was
# not performed as specified by the protocol, then consider that
# an unexpected connection shutdown.
              if (not(self.wasShutdownOffered()) or
                  not self.wasShutdownRequested()):
                raise OSError(
                    errno.ECONNRESET,
                    'End of stream without shutdown negotiation')
              break
            continue

# So this was a normal read. Process the received data.
          self.remoteData += readData
          if len(self.remoteData) == 5:
            self.remoteDataLength = struct.unpack('<I', self.remoteData[1:5])[0]
            if (self.remoteDataLength < 0) or (self.remoteDataLength > (1<<20)):
              raise Exception('Invalid input data chunk length 0x%x' % self.remoteDataLength)
          self.remoteDataLength += 5
          if self.remoteDataLength != 5:
            continue
        if self.remoteDataLength != 5:
          readData = os.read(
              self.inputFd, self.remoteDataLength-len(self.remoteData))
          if len(readData) == 0:
            if self.responsePendingFlag:
              raise Exception('End of data while awaiting response')
            raise Exception('End of data with partial input')
          self.remoteData += readData
        if len(self.remoteData) != self.remoteDataLength:
          continue

# Check the code.
        if not(self.remoteData[0] in ['P', 'R', 'S']):
          raise Exception('Invalid packet type 0x%x' % ord(self.remoteData[0]))

        if self.remoteData[0] != 'S':
          if not self.responsePendingFlag:
            raise Exception(
                'Received %s packet while not awaiting response' % self.remoteData[0])
          if self.remoteData[0] == 'P':
# So this is the first or an additional fragment for a previous response.
            self.inStreamResponseFlag = True
          else:
            self.responsePendingFlag = False
            self.inStreamResponseFlag = False
          responseData = (self.remoteData[5:], self.inStreamResponseFlag)
          self.remoteData = b''
          self.remoteDataLength = -1
          if len(sendQueue) == 0:
            break
          continue

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
            readSelectFds = []
        else:
          handlerResponse = self.requestHandler.handleRequest(
              self.remoteData[5:])
          if isinstance(handlerResponse, MultipartResponseIterator):
            self.responsePartIterator = handlerResponse
            handlerResponse = handlerResponse.getNextPart()
            sendQueue.append([b'P'+struct.pack('<I', len(handlerResponse)), 0])
          else:
            sendQueue.append([b'R'+struct.pack('<I', len(handlerResponse)), 0])
          sendQueue.append([handlerResponse, 0])
        writeSelectFds = [self.outputFd]
        self.remoteData = b''
        self.remoteDataLength = -1
        ioHandledFlag = True
    return responseData


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
    (responseData, responseId) = self.streamMultiplexer.sendRequest(
        json.dumps(['getPolicyInfo']))
    return json.loads(responseData)

  def startTransaction(self, queryData):
    """Start or restart a query transaction to retrive files from
    beginning on, even when skipped in previous round. The query
    pointer is positioned before the first FileInfo to retrieve.
    @param query data to send as query to remote side.
    @throws exception if transation start is not possible or query
    data was not understood by remote side."""
    if self.inStreamReadingFlag:
      raise Exception('Illegal state')
    (responseData, responseId) = self.streamMultiplexer.sendRequest(
        json.dumps(['startTransaction', queryData]))
    if len(responseData) != 0:
      raise Exception('Unexpected response received')

  def nextDataElement(self, wasStoredFlag=False):
    """Move to the next FileInfo.
    @param wasStoredFlag if true, indicate that the previous file
    was stored successfully on local side.
    @return True if a next FileInfo is available, False otherwise."""
    if self.inStreamReadingFlag:
      raise Exception('Illegal state')
    (responseData, responseId) = self.streamMultiplexer.sendRequest(
        json.dumps(['nextDataElement', wasStoredFlag]))
    return json.loads(responseData)

  def getDataElementInfo(self):
    """Get information about the currently selected FileInfo.
    Extraction of information and stream may only be possible
    until proceeding to the next FileInfo using nextDataElement().
    @return a tuple with the source URL, metadata and the attribute
    dictionary visible to the client."""
    if self.inStreamReadingFlag:
      raise Exception('Illegal state')
    (responseData, responseId) = self.streamMultiplexer.sendRequest(
        json.dumps(['getDataElementInfo']))
    result = json.loads(responseData)
    result[1] = BackupElementMetainfo.unserialize(result[1])
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
    responseId = None
    if startStreamFlag:
      (responseData, responseId) = self.streamMultiplexer.sendRequest(
          json.dumps(['getDataElementStream']))
    else:
      (responseData, responseId) = self.streamMultiplexer.handleRequests(1000)
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
    (responseData, responseId) = self.streamMultiplexer.sendRequest(
        json.dumps(['abortDataElementStream']))
# Now continue reading until all buffers have drained and final
# data chunk was removed.
    while len(self.internalReadDataStream()) != 0:
      pass
# Now read the response to the abort command itself.
    (responseData, responseId) = self.streamMultiplexer.sendRequest(None)
    if len(responseData) != 0:
      raise Exception('Unexpected response received')


class WrappedFileStreamMultipartResponseIterator(MultipartResponseIterator):
  """This class wraps an OS stream to provide the data as response
  iterator."""

  def __init__(self, streamFd, chunkSize=1<<16):
    self.streamFd = streamFd
    self.chunkSize = chunkSize

  def getNextPart(self):
    """Get the next part from this iterator.
    @return the part data or None when no more parts are available."""
    readData = os.read(self.streamFd, self.chunkSize)
    if len(readData) == 0:
      return None
    return readData


class JsonStreamServerProtocolRequestHandler():
  """This class handles incoming requests encoded in JSON and
  passes them on to a server protocol adapter."""

  def __init__(self, serverProtocolAdapter):
    self.serverProtocolAdapter = serverProtocolAdapter

  def handleRequest(self, requestData):
    """Handle an incoming request.
    @return the serialized data."""
    request = json.loads(requestData)
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
      responseData = (elementInfo[0], elementInfo[1].serialize(), elementInfo[2])
    elif requestMethod == 'getDataElementStream':
      responseData = WrappedFileStreamMultipartResponseIterator(
          self.serverProtocolAdapter.getDataElementStream())
    else:
      raise Exception('Invalid request %s' % repr(requestMethod))
    if noResponseFlag:
      return b''
    if isinstance(responseData, MultipartResponseIterator):
      return responseData
    return json.dumps(responseData)


class SocketConnectorService():
  """This class listens on a socket and creates a TransferContext
  for each incoming connection."""

  def __init__(self, socketPath, receiverTransferPolicy,
      senderTransferPolicy, localStorage, transferAgent):
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
    self.socket = None
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
    self.isRunningFlag = False

  def run(self):
    """Run this connector service. The method will not return until
    shutdown is requested by another thread."""
    if self.socket == None:
      raise Exception('Already shutdown')
    serverSocket = self.socket
    self.isRunningFlag = True
    serverSocket.listen(4)
    while self.isRunningFlag:
      (clientSocket, remoteAddress) = serverSocket.accept()
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

  def shutdown(self):
    """Shutdown this connector service and all open connections
    established by it."""
    self.isRunningFlag = False
# Close the socket. This will also interrupt any other thread
# in run method.
    self.socket.close()
    self.socket = None
    os.unlink(self.socketPath)
# Shutdown all open connections.
    raise Exception('No connection shutdown yet')
#   self.socketPath = None
