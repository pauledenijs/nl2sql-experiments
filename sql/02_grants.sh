#!/usr/bin/env bash
set -Eeuo pipefail

# 1. Fail fast on missing vars
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${NL2SQL_RO_PASSWORD:?NL2SQL_RO_PASSWORD is required}"

# 2. Run psql as the superuser against the target database

psql \
	-v ON_ERROR_STOP=1 \
	--username "${POSTGRES_USER}" \
	--dbname "${POSTGRES_DB}" \
	<<'SQL'

-- 3. Pull shell env vars into the psql-side variables.
-- The quoted 'SQL' delimiter means shell does NOT expand anything inside.
\getenv ro_password NL2SQL_RO_PASSWORD
\getenv pg_user POSTGRES_USER
\getenv pg_db POSTGRES_DB
	
	
-- 4. Create the read-only role
CREATE ROLE nl2sql_ro
	LOGIN
	NOCREATEROLE NOSUPERUSER NOREPLICATION NOBYPASSRLS
	PASSWORD :'ro_password';

GRANT CONNECT ON DATABASE :"pg_db" TO nl2sql_ro;
GRANT USAGE ON SCHEMA public TO nl2sql_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nl2sql_ro;

ALTER DEFAULT PRIVILEGES
FOR ROLE :"pg_user"
IN SCHEMA public
GRANT SELECT ON TABLES TO nl2sql_ro;

ALTER ROLE nl2sql_ro SET statement_timeout = '5s';
ALTER ROLE nl2sql_ro SET default_transaction_read_only = on;

SQL


