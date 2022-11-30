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


def parseTimeDef(timeStr):
  """Parse a time definition string returning the seconds it
  encodes.
  @param timeStr a human readable string defining a time interval.
  It may contain one or more pairs of numeric values and unit
  appended to each other without spaces, e.g. "6d20H". Valid
  units are "m" (month with 30 days), "w" (week, 7 days), "d"
  (day, 24 hours), "H" (hour with 60 minutes), "M" (minute with
  60 seconds), "S" (second).
  @return the number of seconds encoded in the interval specification."""
  if not timeStr:
    raise Exception('Empty time string not allowed')

  timeDef = {}
  numStart = 0
  while numStart < len(timeStr):
    numEnd = numStart
    while (numEnd < len(timeStr)) and (timeStr[numEnd].isnumeric()):
      numEnd += 1
    if numEnd == numStart:
      raise Exception()
    number = int(timeStr[numStart:numEnd])
    typeKey = 's'
    if numEnd != len(timeStr):
      typeKey = timeStr[numEnd]
      numEnd += 1
    numStart = numEnd
    if typeKey in timeDef:
      raise Exception()
    timeDef[typeKey] = number
  timeVal = 0
  for typeKey, number in timeDef.items():
    factor = {
        'm': 30 * 24 * 60 * 60,
        'w': 7 * 24 * 60 * 60,
        'd': 24 * 60 * 60,
        'H': 60 * 60,
        'M': 60,
        's': 1
    }.get(typeKey, None)
    if factor is None:
      raise Exception('Unknown time specification element "%s"' % typeKey)
    timeVal += number * factor
  return timeVal
