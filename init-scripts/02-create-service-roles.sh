#!/bin/sh
set -eu

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${AUTH_DB_PASSWORD:?AUTH_DB_PASSWORD is required}"
: "${WEBHOOK_DB_PASSWORD:?WEBHOOK_DB_PASSWORD is required}"
: "${AGENT_DB_PASSWORD:?AGENT_DB_PASSWORD is required}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v auth_pw="$AUTH_DB_PASSWORD" \
  -v webhook_pw="$WEBHOOK_DB_PASSWORD" \
  -v agent_pw="$AGENT_DB_PASSWORD" <<'EOSQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auth_service') THEN
    CREATE ROLE auth_service LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'webhook_service') THEN
    CREATE ROLE webhook_service LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_service') THEN
    CREATE ROLE agent_service LOGIN;
  END IF;
END
$$;

ALTER ROLE auth_service PASSWORD :'auth_pw';
ALTER ROLE webhook_service PASSWORD :'webhook_pw';
ALTER ROLE agent_service PASSWORD :'agent_pw';

ALTER DATABASE authfortress OWNER TO auth_service;
ALTER DATABASE webhook_manager OWNER TO webhook_service;
ALTER DATABASE agenthub OWNER TO agent_service;

REVOKE CONNECT ON DATABASE authfortress FROM PUBLIC;
REVOKE CONNECT ON DATABASE webhook_manager FROM PUBLIC;
REVOKE CONNECT ON DATABASE agenthub FROM PUBLIC;

GRANT CONNECT ON DATABASE authfortress TO auth_service;
GRANT CONNECT ON DATABASE webhook_manager TO webhook_service;
GRANT CONNECT ON DATABASE agenthub TO agent_service;
EOSQL
