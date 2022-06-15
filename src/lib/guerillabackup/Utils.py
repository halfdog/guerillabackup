"""This module contains shared utility functions used e.g. by
generator, transfer and validation services."""

import json

def jsonLoadWithComments(fileName):
  """Load JSON data containing comments from a given file name."""
  jsonFile = open(fileName, 'rb')
  jsonData = jsonFile.read()
  jsonFile.close()
  jsonData = b'\n'.join([
      b'' if x.startswith(b'#') else x for x in jsonData.split(b'\n')])
  return json.loads(str(jsonData, 'utf-8'))
