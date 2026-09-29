#!/bin/sh
# Migrate, then serve. The upgrade runs before the first request rather than from a separate
# manual step, because a container that starts against an un-migrated database fails in a way
# that looks like a code bug - 500s on tables that do not exist.
#
# Alembic is idempotent: on a database already at head this is a no-op, so restarts are safe.
set -e

echo "==> alembic upgrade head"
alembic upgrade head

echo "==> starting: $*"
exec "$@"
