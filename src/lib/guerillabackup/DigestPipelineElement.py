"""This module contains only the classes for pipelined digest
calculation."""

import fcntl
import guerillabackup
import hashlib
import os

class DigestPipelineElement(
    guerillabackup.TransformationPipelineElementInterface):
  """This class create pipeline instances for digest generation.
  The instances will forward incoming data unmodified to allow
  digest generation on the fly."""
  def __init__(self, digestClass=hashlib.sha512):
    self.digestClass = digestClass

  def getExecutionInstance(self, upstreamProcessOutput):
    """Get an execution instance for this transformation element.
    @param upstreamProcessOutput this is the output of the upstream
    process, that will be wired as input of the newly created
    process instance."""
    return DigestPipelineExecutionInstance(
        self.digestClass, upstreamProcessOutput)


class DigestPipelineExecutionInstance(
    guerillabackup.TransformationProcessInterface):
  """This is the digest execution instance class created when
  instantiating the pipeline."""
  def __init__(self, digestClass, upstreamProcessOutput):
    self.digest = digestClass()
    self.digestData = None
# Keep the upstream process output until end of stream is reached.
    self.upstreamProcessOutput = upstreamProcessOutput
    self.processOutput = None
# Output stream for direct writing.
    self.processOutputStream = None
    self.processOutputBuffer = ''


  def getProcessOutput(self):
    """Get the output connector of this transformation process."""
    if self.processOutputStream == None:
      raise Exception('No access to process output in stream mode')
    if self.processOutput == None:
      self.processOutput = DigestOutputInterface(self)
    return self.processOutput


  def setProcessOutputStream(self, processOutputStream):
    """Some processes may also support setting of an output stream
    file descriptor. This is especially useful if the process
    is the last one in a pipeline and hence could write directly
    to a file or network descriptor.
    @throw Exception if this process does not support setting
    of output stream descriptors."""

    if self.processOutput != None:
      raise Exception('No setting of output stream after call to getProcessOutput')
# This module has no asynchronous operation mode, so writing to
# a given output stream in doProcess has to be non-blocking to
# avoid deadlock.
    flags = fcntl.fcntl(processOutputStream, fcntl.F_GETFL)
    fcntl.fcntl(processOutputStream, fcntl.F_SETFL, flags|os.O_NONBLOCK)
    self.processOutputStream = processOutputStream

  def isAsynchronous(self):
    """A asynchronous process just needs to be started and will
    perform data processing on streams without any further interaction
    while running."""
    return False

  def start(self):
    """Start this execution process."""
    if (self.processOutput == None) and (self.processOutputStream == None):
      raise Exception('Not connected')

    if self.digest == None:
      raise Exception('Cannot restart again')
# Nothing to do with that type of process.

  def stop(self):
    """Stop this execution process when still running.
    @return None when the the instance was already stopped, information
    about stopping, e.g. the stop error message when the process
    was really stopped."""
    if self.digest == None:
      return None
    self.digestData = self.digest.digest()
    self.digest = None

  def isRunning(self):
    """See if this process instance is still running."""
    return self.digest != None

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
    if self.digest == None:
      return -1
    movedDataLength = 0
    if ((self.upstreamProcessOutput != None) and
        (len(self.processOutputBuffer) == 0)):
      self.processOutputBuffer = self.upstreamProcessOutput.readData(1<<16)
      if self.processOutputBuffer == None:
        self.upstreamProcessOutput = None
        self.digestData = self.digest.digest()
        self.digest = None
        return -1
      movedDataLength = len(self.processOutputBuffer)
    if self.processOutputStream != None:
      writeLength = os.write(self.processOutputStream, self.processOutputBuffer)
      movedDataLength += writeLength
      self.digest.update(self.processOutputBuffer[:writeLength])
      if writeLength == len(self.processOutputBuffer):
        self.processOutputBuffer = ''
      else:
        self.processOutputBuffer = self.processOutputBuffer[writeLength:]
    return movedDataLength

  def getBlockingStreams(self, readStreamList, writeStreamList):
    """Collect the file descriptors that are currently blocking
    this synchronous compoment."""
    if ((self.upstreamProcessOutput != None) and
        (len(self.processOutputBuffer) == 0) and
        (self.upstreamProcessOutput.getOutputStreamDescriptor() != None)):
      readStreamList.append(
          self.upstreamProcessOutput.getOutputStreamDescriptor())
    if ((self.processOutputStream != None) and
        (self.processOutputBuffer != None) and
        (len(self.processOutputBuffer) != 0)):
      writeStreamList.append(self.processOutputStream)

  def getDigestData(self):
    """Get the data from this digest after processing was completed."""
    if self.digest != None:
      raise Exception('Digest processing not yet completed')
    return self.digestData


class DigestOutputInterface(
    guerillabackup.TransformationProcessOutputInterface):
  """Digest pipeline element output class."""
  def __init__(self, executionInstance):
    self.executionInstance = executionInstance

  def getOutputStreamDescriptor(self):
    """Get the file descriptor to read output from this output
    interface. This is not available for that type of digest element."""
    return None

  def readData(self, length):
    """Read data from this output.
    @return the at most length bytes of data, zero-length data
    if nothing available at the moment and None when end of input
    was reached."""
    if self.executionInstance.processOutputBuffer == None:
      return None
    returnData = self.executionInstance.processOutputBuffer
    if length < len(self.executionInstance.processOutputBuffer):
      returnData = self.executionInstance.processOutputBuffer[:length]
      self.executionInstance.processOutputBuffer = self.executionInstance.processOutputBuffer[length:]
    else:
      self.executionInstance.processOutputBuffer = ''
    return returnData
