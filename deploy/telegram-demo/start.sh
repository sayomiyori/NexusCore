#!/bin/sh
set -eu

# Validate before envsubst: an operator typo must not become nginx syntax.
TELEGRAM_DEMO_BOT_ID=${TELEGRAM_DEMO_BOT_ID:-}
if [ "${#TELEGRAM_DEMO_BOT_ID}" -ne 36 ] || ! printf '%s\n' "$TELEGRAM_DEMO_BOT_ID" | grep -Eq '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'; then
    echo 'TELEGRAM_DEMO_BOT_ID must be a lowercase canonical UUID' >&2
    exit 1
fi
exec /docker-entrypoint.sh "$@"
