Description:
============

This directory contains a transfer service implementation with
a test backup generator adding one simple tar backup every minute
and a transfer service configuration to send those.


Generator invocation:
=====================

projectBaseDir="... directory with GuerillaBackup source ..."
tmpDir="$(mktemp -d)"
mkdir -- "${tmpDir}/config" "${tmpDir}/data" "${tmpDir}/log"
echo "Testlogdata" > "${tmpDir}/log/test.log.0"
cp -a -- "${projectBaseDir}/test/SenderOnlyTransferService/config" "${projectBaseDir}/test/SenderOnlyTransferService/units" "${tmpDir}/config"
sed -i -r -e "s:\[TmpDir\]:${tmpDir}:g" -- "${tmpDir}/config/config" "${tmpDir}/config/units/LogfileBackupUnit.config" "${tmpDir}/config/units/TarBackupUnit.config"
ln -s -- "${projectBaseDir}/src/lib/guerillabackup/LogfileBackupUnit.py" "${tmpDir}/config/units/LogfileBackupUnit"
ln -s -- "${projectBaseDir}/src/lib/guerillabackup/TarBackupUnit.py" "${tmpDir}/config/units/TarBackupUnit"
"${projectBaseDir}/src/gb-backup-generator" --ConfigDir "${tmpDir}/config"

Terminate the generator using [Ctrl]-C and check, that backups
were created.

ls -alR -- "${tmpDir}/data"

To test data corruption handling, append a byte to one of the
data files.

echo "corrupted!" >> "${tmpDir}/data/.....data"


gb-transfer-service invocation:
============================

Start the service:

echo "Listening on socket ${tmpDir}/run/transfer.socket"
"${projectBaseDir}/src/gb-transfer-service" --Config "${tmpDir}/config/config"

Send test requests using the fake client: IO-handling is simplified,
so just press return on empty lines until expected response was
received.

"${projectBaseDir}/test/SyncProtoTestClient" "${tmpDir}/run/transfer.socket"

send Rnull
send R
send S["getPolicyInfo"]
send S["startTransaction", null]
send S["nextDataElement", false]
send S["getDataElementInfo"]
send S["getDataElementStream"]
send S["nextDataElement", true]
...
send S

Normal transfer client test:

See ReceiverOnlyTransferService
