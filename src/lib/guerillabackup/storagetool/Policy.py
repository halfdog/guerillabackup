class Policy():
  """This class defines a policy instance."""

  def __init__(self, policyConfig):
    """Instantiate this policy object from a JSON policy configuration
    definition."""
    if not isinstance(policyConfig, dict):
      raise Exception(
          'Policy configuration has to be a dictionary: %s' % (
              repr(policyConfig)))
    self.policyName = policyConfig['Name']
    if not isinstance(self.policyName, str):
      raise Exception('Policy name has to be a string')
    self.policyPriority = policyConfig.get('Priority', 0)
    if not isinstance(self.policyPriority, int):
      raise Exception('Policy priority has to be an integer')

  def getPolicyName(self):
    """Get the name of this policy."""
    return self.policyName

  def getPriority(self):
    """Get the priority of this policy. A higher number indicates
    that a policy has higher priority and shall override any
    policies with lower or equal priority."""
    return self.policyPriority

  def apply(self, sourceStatus):
    """Apply this policy to a backup source status."""
    raise Exception('Abstract method called')

  def delete(self, sourceStatus):
    """Delete the policy status data of this policy for all elements
    marked for deletion and update status data of those elements
    kept to allow validation even after deletion of some elements."""
    raise Exception('Abstract method called')
