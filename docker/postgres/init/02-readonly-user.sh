#!/bin/sh
set -eu

psql --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=agent_user="$DATAPILOT_DB_USER" \
  --set=agent_password="$DATAPILOT_DB_PASSWORD" <<'SQL'
CREATE ROLE :"agent_user" LOGIN PASSWORD :'agent_password';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE :"DBNAME" TO :"agent_user";
GRANT USAGE ON SCHEMA public TO :"agent_user";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"agent_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO :"agent_user";
ALTER ROLE :"agent_user" SET default_transaction_read_only = on;
ALTER ROLE :"agent_user" SET statement_timeout = '3s';
SQL
