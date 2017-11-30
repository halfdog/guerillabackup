Description:
============

This directory contains configuration for logfile backup unit
testing.


Test invocation:
================

projectBaseDir="... directory with GuerillaBackup source ..."
tmpDir="$(mktemp -d)"
mkdir -- "${tmpDir}/config" "${tmpDir}/data" "${tmpDir}/sink" "${tmpDir}/logs"
cp -a -- "${projectBaseDir}/test/LogfileBackupUnitTest/config" "${tmpDir}/config"
ln -s -- "${projectBaseDir}/src/lib/guerillabackup/LogfileBackupUnit.py" "${tmpDir}/config/units/LogfileBackupUnit"
cp -a -- "${projectBaseDir}/test/LogfileBackupUnitTest/LogfileBackupUnit.config" "${tmpDir}/config/units"
sed -i -r -e "s:\[TmpDir\]:${tmpDir}:g" -- "${tmpDir}/config/config" "${tmpDir}/config/units/LogfileBackupUnit.config"

echo 0 > "${tmpDir}/logs/test.log"
dd if=/dev/zero bs=1M count=32 > "${tmpDir}/logs/test.log.1"
dd if=/dev/zero bs=1M count=32 | gzip -c9 > "${tmpDir}/logs/test.log.2.gz"
cp -a -- "${tmpDir}/logs/test.log.2.gz" "${tmpDir}/logs/test.log.3.gz"
cp -a -- "${tmpDir}/logs/test.log.2.gz" "${tmpDir}/logs/test.log.4.gz"
cp -a -- "${tmpDir}/logs/test.log.2.gz" "${tmpDir}/logs/test.log.5.gz"
cp -a -- "${tmpDir}/logs/test.log.2.gz" "${tmpDir}/logs/test.log.6.gz"
cp -a -- "${tmpDir}/logs/test.log.2.gz" "${tmpDir}/logs/test.log.7.gz"

echo "Starting LogfileBackupUnit testing in ${tmpDir}"
"${projectBaseDir}/src/BackupGenerator" --ConfigDir "${tmpDir}/config"

sed -i -r -e "s:\[[0-9]+,:[123,:g" -- "${tmpDir}/state/generators/LogfileBackupUnit/state.current"
