"""This module contains classes for creation of asynchronous
OS process based pipeline elements."""

import fcntl
import os
import subprocess

import guerillabackup
from guerillabackup.TransformationProcessOutputStream import NullProcessOutputStream
from guerillabackup.TransformationProcessOutputStream import TransformationProcessOutputStream

class OSProcessPipelineElement(
    guerillabackup.TransformationPipelineElementInterface):
  """This is the interface to define data transformation pipeline
  elements, e.g. for compression, encryption, signing. To really
  start execution of a transformation pipeline, transformation
  process instances have to be created for each pipe element."""

  def __init__(self, executable, execArgs, allowedExitStatusList=None):
    """Create the OSProcessPipelineElement element.
    @param allowedExitStatusList when not defined, only command
    exit code of 0 is accepted to indicated normal termination."""
    self.executable = executable
    self.execArgs = execArgs
    if not guerillabackup.isValueListOfType(self.execArgs, str):
      raise Exception('execArgs have to be list of strings')
    if allowedExitStatusList is None:
      allowedExitStatusList = [0]
    self.allowedExitStatusList = allowedExitStatusList

  def getExecutionInstance(self, upstreamProcessOutput):
    """Get an execution instance for this transformation element.
    @param upstreamProcessOutput this is the output of the upstream
    process, that will be wired as input of the newly created
    process instance."""
    return OSProcessPipelineExecutionInstance(
        self.executable, self.execArgs, upstreamProcessOutput,
        self.allowedExitStatusList)


class OSProcessPipelineExecutionInstance(
    guerillabackup.TransformationProcessInterface):
  """This class defines the execution instance of an OSProcessPipeline
  element."""

  STATE_NOT_STARTED = 0
  STATE_RUNNING = 1
# This state reached when the process has already terminated but
# input/output shutdown is still pending.
  STATE_SHUTDOWN = 2
  STATE_ENDED = 3

  def __init__(self, executable, execArgs, upstreamProcessOutput, allowedExitStatusList):
    self.executable = executable
    self.execArgs = execArgs
    self.upstreamProcessOutput = upstreamProcessOutput
    if self.upstreamProcessOutput is None:
# Avoid reading from real stdin, use replacement output.
      self.upstreamProcessOutput = NullProcessOutputStream()
    self.upstreamProcessOutputBuffer = b''
    self.inputPipe = None
    self.allowedExitStatusList = allowedExitStatusList

# Simple state tracking to be more consistent on multiple invocations
# of the same method. States are "not starte", "running", "ended"
    self.processState = OSProcessPipelineExecutionInstance.STATE_NOT_STARTED
    self.process = None
# Process output instance of this process only when no output
# file descriptor is set.
    self.processOutput = None
# This exception holds any processing error until doProcess()
# or stop() is called.
    self.processingException = None

  def createProcess(self, outputFd):
    """Create the process.
    @param outputFd if not None, use this as output stream descriptor."""

# Create the process file descriptor pairs manually. Otherwise
# it is not possible to wait() for the process first and continue
# to read from the other side of the pipe after garbage collection
# of the process object.
    self.inputPipe = None
    outputPipeFds = None
    if outputFd is None:
      outputPipeFds = os.pipe2(os.O_CLOEXEC)
      outputFd = outputPipeFds[1]
    if self.upstreamProcessOutput.getOutputStreamDescriptor() is None:
      self.process = subprocess.Popen(
          self.execArgs, executable=self.executable, stdin=subprocess.PIPE,
          stdout=outputFd)
      self.inputPipe = self.process.stdin
      flags = fcntl.fcntl(self.inputPipe.fileno(), fcntl.F_GETFL)
      fcntl.fcntl(self.inputPipe.fileno(), fcntl.F_SETFL, flags|os.O_NONBLOCK)
    else:
      self.process = subprocess.Popen(
          self.execArgs, executable=self.executable,
          stdin=self.upstreamProcessOutput.getOutputStreamDescriptor(),
          stdout=outputFd)

    self.processOutput = None
    if outputPipeFds is not None:
# Close the write side now.
      os.close(outputPipeFds[1])
      self.processOutput = TransformationProcessOutputStream(
          outputPipeFds[0])

  def getProcessOutput(self):
    """Get the output connector of this transformation process."""
    if self.processState != OSProcessPipelineExecutionInstance.STATE_NOT_STARTED:
      raise Exception('Output manipulation only when not started yet')
    if self.process is None:
      self.createProcess(None)
    if self.processOutput is None:
      raise Exception('No access to process output in stream mode')
    return self.processOutput

  def setProcessOutputStream(self, processOutputStream):
    """Some processes may also support setting of an output stream
    file descriptor. This is especially useful if the process
    is the last one in a pipeline and hence could write directly
    to a file or network descriptor.
    @throw Exception if this process does not support setting
    of output stream descriptors."""
    if self.processState != OSProcessPipelineExecutionInstance.STATE_NOT_STARTED:
      raise Exception('Output manipulation only when not started yet')
    if self.process is not None:
      raise Exception('No setting of output stream after previous ' \
          'setting or call to getProcessOutput')
    self.createProcess(processOutputStream)

  def checkConnected(self):
    """Check if this process instance is already connected to
    an output, e.g. via getProcessOutput or setProcessOutputStream."""
    if (self.processState == OSProcessPipelineExecutionInstance.STATE_NOT_STARTED) and \
        (self.process is None):
      raise Exception('Operation mode not known while not fully connected')
# Process instance only created when connected, so everything OK.

  def isAsynchronous(self):
    """A asynchronous process just needs to be started and will
    perform data processing on streams without any further interaction
    while running."""
    self.checkConnected()
    return self.inputPipe is None

  def start(self):
    """Start this execution process."""
    if self.processState != OSProcessPipelineExecutionInstance.STATE_NOT_STARTED:
      raise Exception('Already started')
    self.checkConnected()
# The process itself was already started when being connected.
# Just update the state here.
    self.processState = OSProcessPipelineExecutionInstance.STATE_RUNNING

  def stop(self):
    """Stop this execution process when still running.
    @return None when the the instance was already stopped, information
    about stopping, e.g. the stop error message when the process
    was really stopped."""
    if self.processState == OSProcessPipelineExecutionInstance.STATE_NOT_STARTED:
      raise Exception('Not started')
# We are already stopped, do othing here.
    if self.processState == OSProcessPipelineExecutionInstance.STATE_ENDED:
      return None

# Clear any pending processing exceptions. This is the last chance
# for reporting anyway.
    stopException = self.processingException
    self.processingException = None

    if self.processState == OSProcessPipelineExecutionInstance.STATE_RUNNING:
# The process was not stopped yet, do it. There is a small chance
# that we send a signal to a dead process before waiting on it
# and hence we would have a normal termination here. Ignore that
# case, a stop() indicates need for abnormal termination with
# risk of data loss.
      self.process.kill()
      self.process.wait()
      self.process = None
      self.processState = OSProcessPipelineExecutionInstance.STATE_SHUTDOWN

# Now we are in STATE_SHUTDOWN.
    self.finishProcess()
# If there was no previous exception, copy any exception from
# finishing the process.
    if stopException is None:
      stopException = self.processingException
      self.processingException = None
    return stopException

  def isRunning(self):
    """See if this process instance is still running.
    @return False if instance was not yet started or already stopped.
    If there are any unreported pending errors from execution,
    this method will return True until doProcess() or stop() is
    called at least once."""
    if self.processState in [
        OSProcessPipelineExecutionInstance.STATE_NOT_STARTED,
        OSProcessPipelineExecutionInstance.STATE_ENDED]:
      return False
    if self.processingException is not None:
# There is a pending exception, which is cleared only in doProcess()
# or stop(), so pretend that the process is still running.
      return True

    if self.processState == OSProcessPipelineExecutionInstance.STATE_RUNNING:
      (pid, status) = os.waitpid(self.process.pid, os.WNOHANG)
      if pid == 0:
        return True
      self.process = None
      self.processState = OSProcessPipelineExecutionInstance.STATE_SHUTDOWN
      if (status&0xff) != 0:
        self.processingException = Exception('Process end by signal %d, ' \
            'status 0x%x' % (status&0xff, status))
      elif (status>>8) not in self.allowedExitStatusList:
        self.processingException = Exception('Process end with unexpected ' \
            'exit status %d' % (status>>8))

# We are in shutdown here. See if we can finish that phase immediately.
    if self.processingException is None:
      try:
        self.upstreamProcessOutput.close()
        self.processState = OSProcessPipelineExecutionInstance.STATE_ENDED
      except Exception as closeException:
        self.processingException = closeException

# Pretend that we are still running so that pending exception
# is reported with next doProcess() call.
    return self.processState != OSProcessPipelineExecutionInstance.STATE_ENDED

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
    if self.processState == OSProcessPipelineExecutionInstance.STATE_NOT_STARTED:
      raise Exception('Not started')
    if self.processState == OSProcessPipelineExecutionInstance.STATE_ENDED:
# This must be a logic error attempting to process data when
# already stopped.
      raise Exception('Process %s already stopped' % self.executable)
    if self.processingException is not None:
      processingException = self.processingException
      self.processingException = None
# We are dead here anyway, close inputs and outputs ignoring any
# data possibly lost.
      self.finishProcess()
      self.processState = OSProcessPipelineExecutionInstance.STATE_ENDED
      raise processingException

    if self.inputPipe is not None:
      if len(self.upstreamProcessOutputBuffer) == 0:
        self.upstreamProcessOutputBuffer = self.upstreamProcessOutput.readData(1<<16)
        if self.upstreamProcessOutputBuffer is None:
          self.inputPipe.close()
          self.inputPipe = None
      if ((self.upstreamProcessOutputBuffer is not None) and
          (len(self.upstreamProcessOutputBuffer) != 0)):
        writeLength = self.inputPipe.write(self.upstreamProcessOutputBuffer)
        if writeLength == len(self.upstreamProcessOutputBuffer):
          self.upstreamProcessOutputBuffer = b''
        else:
          self.upstreamProcessOutputBuffer = self.upstreamProcessOutputBuffer[writeLength:]
        return writeLength
    if self.isRunning():
# Pretend that we are still waiting for more input, thus polling
# may continue when at least another component moved data.
      return 0
# All pipes are empty and no more processing is possible.
    return -1

  def getBlockingStreams(self, readStreamList, writeStreamList):
    """Collect the file descriptors that are currently blocking
    this synchronous compoment."""
# The upstream input can be ignored when really a file descriptor,
# it is wired to this process for asynchronous use anyway. When
# not a file descriptor, writing to the input pipe may block.
    if self.inputPipe is not None:
      writeStreamList.append(self.inputPipe.fileno())


  def finishProcess(self):
    """This method cleans up the current process after operating
    system process termination but maybe before handling of pending
    exceptions. The method will set the processingException when
    finishProcess caused any errors. An error is also when this
    method is called while upstream did not close the upstream
    output stream yet."""
    readData = self.upstreamProcessOutput.readData(64)
    if readData is not None:
      if len(readData) == 0:
        self.processingException = Exception('Upstream did not finish yet, data might be lost')
      else:
        self.processingException = Exception('Not all upstream data processed')
# Upstream is delivering data that was not processed. Close the
# output so that upstream will also notice when attempting to
# write to will receive an exception.
      self.upstreamProcessOutput.close()
    self.upstreamProcessOutput = None

    if self.upstreamProcessOutputBuffer is not None:
      self.processingException = Exception(
          'Output buffers to process not drained yet, %d bytes lost' %
              len(self.upstreamProcessOutputBuffer))
      self.upstreamProcessOutputBuffer = None

    self.process = None
