#!/bin/bash
set -e


psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE "${POSTGRES_DB}_chn";
    GRANT ALL PRIVILEGES ON DATABASE "${POSTGRES_DB}_chn" TO "$POSTGRES_USER";
    CREATE DATABASE "${POSTGRES_DB}_us";
    GRANT ALL PRIVILEGES ON DATABASE "${POSTGRES_DB}_us" TO "$POSTGRES_USER";
EOSQL


postgresqltuner.pl --host=/var/run/postgresql --user "$POSTGRES_USER" 