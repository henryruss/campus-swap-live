#!/bin/bash
# Pull a fresh dump from Render and restore it to the local campusswap DB.
# Usage: ./sync_prod_db.sh
#
# Requires RENDER_DATABASE_URL in .env (or already exported in your shell).
# Get it from: Render dashboard → your Postgres service → Connect → External Database URL

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
SNAPSHOT="$SCRIPT_DIR/prod_snapshot.sql"
LOCAL_DB="campusswap"

# Load .env if present
if [ -f "$ENV_FILE" ]; then
  RENDER_DATABASE_URL=$(grep -v '^#' "$ENV_FILE" | grep 'RENDER_DATABASE_URL' | sed 's/.*=[ ]*//')
fi

if [ -z "$RENDER_DATABASE_URL" ]; then
  echo "Error: RENDER_DATABASE_URL is not set."
  echo "Add it to your .env file:"
  echo "  RENDER_DATABASE_URL=postgresql://user:password@host/dbname"
  echo "(Find it in Render → your Postgres → Connect → External Database URL)"
  exit 1
fi

PG_DUMP=/opt/homebrew/opt/postgresql@18/bin/pg_dump
if [ ! -f "$PG_DUMP" ]; then
  echo "Error: postgresql@18 not found at $PG_DUMP"
  echo "Run: brew install postgresql@18"
  exit 1
fi

echo "→ Dumping prod DB from Render..."
"$PG_DUMP" "$RENDER_DATABASE_URL" --no-owner --no-acl -f "$SNAPSHOT"
echo "  Saved to prod_snapshot.sql ($(wc -l < "$SNAPSHOT") lines)"

echo "→ Dropping and recreating local DB: $LOCAL_DB"
dropdb --if-exists "$LOCAL_DB"
createdb "$LOCAL_DB"

echo "→ Restoring..."
psql "$LOCAL_DB" < "$SNAPSHOT"

echo ""
echo "Done. Local '$LOCAL_DB' is now a copy of prod."
