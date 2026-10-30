#!/bin/sh
# One-shot, reviewed provisioning for an existing PostgreSQL volume.
# Fresh volumes are handled by init-scripts/02-create-service-roles.sh.
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

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname agenthub \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

for spec in "authfortress:auth_service" "webhook_manager:webhook_service" "agenthub:agent_service"; do
  database=${spec%%:*}
  role=${spec##*:}
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$database" <<EOSQL
ALTER SCHEMA public OWNER TO $role;
DO \$\$
DECLARE r record;
BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO %I', r.tablename, '$role');
  END LOOP;
  FOR r IN SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER SEQUENCE public.%I OWNER TO %I', r.sequencename, '$role');
  END LOOP;
  FOR r IN SELECT t.typname FROM pg_type t
           JOIN pg_namespace n ON n.oid = t.typnamespace
           WHERE n.nspname = 'public' AND t.typtype = 'e' LOOP
    EXECUTE format('ALTER TYPE public.%I OWNER TO %I', r.typname, '$role');
  END LOOP;
  FOR r IN SELECT viewname FROM pg_views WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER VIEW public.%I OWNER TO %I', r.viewname, '$role');
  END LOOP;
  FOR r IN SELECT matviewname FROM pg_matviews WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER MATERIALIZED VIEW public.%I OWNER TO %I', r.matviewname, '$role');
  END LOOP;
  FOR r IN SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args
           FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname = 'public'
             AND p.prokind IN ('f', 'w')
             AND NOT EXISTS (
               SELECT 1 FROM pg_depend d
               WHERE d.objid = p.oid
                 AND d.classid = 'pg_proc'::regclass
                 AND d.deptype = 'e'
             ) LOOP
    EXECUTE format('ALTER FUNCTION public.%I(%s) OWNER TO %I', r.proname, r.args, '$role');
  END LOOP;
END
\$\$;
EOSQL
done
