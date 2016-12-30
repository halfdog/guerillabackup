This directory contains all the loaded units plus configuration
parameter overrides, if available. When not available, the main
backup generator configuration, usually "/etc/guerillabackup/config",
is passed to each unit unmodified.

A valid unit can be a symlink to a guerillabackup core unit, e.g.
/usr/lib/guerillabackup/lib/guerillabackup/LogfileBackupUnit.py
but also a local unit definition written into a plain file.

To be loaded, the unit definition file name has to contain only
numbers and letters. An associated configuration file has the
same name with suffix ".config" appended.

This "Readme.txt" and all files named ".template" are ignored.
