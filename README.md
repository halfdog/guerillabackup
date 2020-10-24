# GuerillaBackup:

GuerillaBackup is a minimalistic backup toolbox for asynchronous,
local-coordinated, distributed, resilient and secure backup generation,
data distribution, verification, storage and deletion suited for
rugged environments. GuerillaBackup could be the right solution
for you if you want

* distributed backup data generation under control of the source
  system owner, assuming that he knows best what data is worth
  being written to backup and which policies (retention time,
  copy count, encryption, non-repudiation) should be applied
* operation with limited bandwith, instable network connectivity,
  limited storage space
* data confidentiality, integrity, availability guarantees even
  with a limited number of compromised or malicious backup processing
  nodes
* limited trust between backup data source and sink system(s)

When you need the following features, you might look for a standard
free or commercial backup solution:

* central control of backup and retention policies
* central unlimited access to all data
* operate under stable conditions with solid network, sufficient
  storage, trust between both backup data source and sink

# Getting started:

For those just wanting to get started quickly, following trail
might be the best:

* Build (see "Building" below) the software or install the binary
  package from file ("dpkg -i guerillabackup_[version]_all.deb")
  or repository ("apt-get install guerillabackup".
* Follow the steps from "doc/Installation.txt", section "General
  GuerillaBackup Configuration".
* If not everything is fine yet, see "doc/FAQs.txt" to see if
  your problem is already known.
* If still not working, please file a bug/feature request at github,
  see "Resources" section below.

# Building:

* Build a native Debian test package using the default template:
  see data/debian.template/Readme.txt

# Resources:

* Bugs, feature requests: https://github.com/halfdog/guerillabackup/issues

# Documentation:

* doc/Design.txt: GuerillaBackup design documentation
* doc/Implementation.txt: GuerillaBackup implementation documentation
* doc/Installation.txt: GuerillaBackup end user installation
  documentation
* Manual pages: doc/BackupGenerator.1.xml and doc/TransferService.1.xml
  here on github, usually "man (BackupGenerator|TransferService)"
  when installed from package repository
* doc/FAQs.txt: GuerillaBackup frequently asked questions
