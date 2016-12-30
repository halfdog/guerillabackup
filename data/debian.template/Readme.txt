This directory contains the Debian packaging files to build a
native package. They are kept in the data directory: quilt type
Debian package building cannot use any files included in the
DEBIAN directory of an upstream orig.tar.gz.

To build a native package using the template files, use following
commands:

projectBaseDir="... directory with GuerillaBackup source ..."
tmpDir="$(mktemp -d)"
mkdir -- "${tmpDir}/guerillabackup"
cp -aT -- "${projectBaseDir}" "${tmpDir}/guerillabackup"
mv -i -- "${tmpDir}/guerillabackup/data/debian.template" "${tmpDir}/guerillabackup/debian" < /dev/null
cd "${tmpDir}/guerillabackup"
dpkg-buildpackage -us -uc

