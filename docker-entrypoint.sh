#!/bin/sh
set -eu

# Home Assistant supplies /data at runtime. Make the mount writable, then run
# the application without root privileges.
if [ "$(id -u)" -eq 0 ]; then
    chown app:app /data
    exec setpriv --reuid=app --regid=app --init-groups "$@"
fi

exec "$@"
