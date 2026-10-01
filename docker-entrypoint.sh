#!/bin/sh
set -eu

# Railway volumes are mounted after the image is built and arrive root-owned.
# Prepare only Mini AI's fixed data mount, then run the service unprivileged.
mkdir -p /data
chown mini:mini /data
chmod 0700 /data

exec gosu mini "$@"
