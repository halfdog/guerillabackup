"""This module provides streams for linking of pipeline elements."""

import guerillabackup
import os
import select

class TransformationProcessOutputStream(
    guerillabackup.TransformationProcessOutputInterface):
  """This class implements a filedescriptor stream based transformation
  output. It can be used for both plain reading but also to pass
  the file descriptor to downstream processes directly."""
  def __init__(self, streamFd):
    if not isinstance(streamFd, int):
      raise Exception('Not a valid stream file descriptor')
    self.streamFd = streamFd

  def getOutputStreamDescriptor(self):
    return self.streamFd

  def readData(self, length):
    """Read data from this stream without blocking.
    @return the at most length bytes of data, zero-length data
    if nothing available at the moment and None when end of input
    was reached."""
# Perform a select before reading so that we do not need to switch
# the stream into non-blocking mode.
    readFds, writeFds, exFds = select.select([self.streamFd], [], [], 0)
# Nothing available yet, do not attempt to read.
    if len(readFds) == 0:
      return b''
    data = os.read(self.streamFd, length)
# Reading will return zero-length data when end of stream was reached.
# Return none in that case.
    if len(data) == 0:
      return None
    return data


class NullProcessOutputStream(
    guerillabackup.TransformationProcessOutputInterface):
  """This class implements a transformation output delivering
  no output at all. It is useful to seal stdin of a toplevel OS
  process pipeline element to avoid reading from real stdin."""
  def getOutputStreamDescriptor(self):
    return None

  def readData(self, length):
    """Read data from this stream without blocking.
    @return the at most length bytes of data, zero-length data
    if nothing available at the moment and None when end of input
    was reached."""
    return None
