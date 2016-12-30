import guerillabackup
from guerillabackup.OSProcessPipelineElement import OSProcessPipelineExecutionInstance

class GpgEncryptionPipelineElement(
    guerillabackup.TransformationPipelineElementInterface):
# Those are the default arguments beside key name.
  gpgDefaultCallArguments = ['/usr/bin/gpg', '--batch', '--lock-never',
      '--no-options', '--homedir', '/etc/guerillabackup/keys',
      '--trust-model', 'always', '--throw-keyids', '--no-emit-version',
      '--encrypt']

  """This class create pipeline instances for PGP encryption of
  data stream using gpg.
  @param When defined, pass those arguments to gpg when encrypting.
  Otherwise gpgDefaultCallArguments are used."""
  def __init__(self, keyName, callArguments=gpgDefaultCallArguments):
    self.keyName = keyName
    self.callArguments = callArguments

  def getExecutionInstance(self, upstreamProcessOutput):
    """Get an execution instance for this transformation element.
    @param upstreamProcessOutput this is the output of the upstream
    process, that will be wired as input of the newly created
    process instance."""
    return(OSProcessPipelineExecutionInstance(self.callArguments[0],
        self.callArguments+['--hidden-recipient', self.keyName],
        upstreamProcessOutput))

  def replaceKey(self, newKeyName):
    """Return an encryption element with same gpg invocation arguments
    but key name replaced."""
    return GpgEncryptionPipelineElement(newKeyName, self.callArguments)
