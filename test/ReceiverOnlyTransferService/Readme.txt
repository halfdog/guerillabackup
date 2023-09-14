Description:
============

This directory contains a transfer service implementation with
a test receiver only transfer configuration. It just listens on
an input socket, which has to be connected externally.


Transfer invocation:
====================

projectBaseDir="... directory with GuerillaBackup source ..."
tmpDir="$(mktemp -d)"
mkdir -- "${tmpDir}/config" "${tmpDir}/data"
cp -a -- "${projectBaseDir}/test/ReceiverOnlyTransferService/config" "${tmpDir}/config"
sed -i -r -e "s:\[TmpDir\]:${tmpDir}:g" -- "${tmpDir}/config/config"
echo "Listening on socket ${tmpDir}/run/transfer.socket"
"${projectBaseDir}/src/gb-transfer-service" --Config "${tmpDir}/config/config"

Connect the gb-transfer-service to an instance with a sending policy,
e.g. see SenderOnlyTransferService testcase.

socat "UNIX-CONNECT:${tmpDir}/run/transfer.socket" "UNIX-CONNECT:...other socket"

Terminate the gb-transfer-service using [Ctrl]-C and check, that backups
were transferred as expected.

ls -al -- "${tmpDir}/data"
