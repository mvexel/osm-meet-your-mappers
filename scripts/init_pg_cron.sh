#!/bin/bash

# Ensure we're running as postgres user
if [ "$(id -u)" = "0" ]; then
   exec gosu postgres "$0" "$@"
fi

# Write a custom PostgreSQL configuration file
cat > /var/lib/postgresql/data/postgresql.conf << EOF
shared_preload_libraries = 'pg_cron'
cron.database_name = '$POSTGRES_DB'
cron.log_run = on
cron.log_statement = on
cron.use_background_workers = on
EOF

# Start PostgreSQL with the new config
exec postgres -c "config_file=/var/lib/postgresql/data/postgresql.conf"
