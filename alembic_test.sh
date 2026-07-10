#!/bin/bash
set -e
apt-get update -qq && apt-get install -y -qq libpq-dev 2>&1 | tail -1
pip install -q -r requirements.txt 2>&1 | tail -1
echo '=== testing DB connection ==='
python -c "
import psycopg2
conn = psycopg2.connect('postgresql://postgres:postgres@host.docker.internal:5433/regintel_migration_test')
cur = conn.cursor()
cur.execute('SELECT version()')
print('Connected:', cur.fetchone()[0])
cur.close()
conn.close()
"
echo '=== Running alembic upgrade head ==='
alembic upgrade head 2>&1
echo '==EXIT='$?
