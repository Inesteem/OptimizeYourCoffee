#!/bin/bash
# Swap between production and test databases.
#
# Usage:
#   ./scripts/swap_db.sh test    # Save current DB as production, load test DB
#   ./scripts/swap_db.sh prod    # Save current DB as test, load production DB
#   ./scripts/swap_db.sh status  # Show which DB is active
#
# The script stores databases in coffee-app/db-store/:
#   coffee-prod.db  — real production data
#   coffee-test.db  — test data for development

set -euo pipefail

DB="coffee-app/coffee.db"
STORE="coffee-app/db-store"
PROD="$STORE/coffee-prod.db"
TEST="$STORE/coffee-test.db"

mkdir -p "$STORE"

case "${1:-status}" in
    test)
        if [ -f "$DB" ] && [ -s "$DB" ]; then
            cp "$DB" "$PROD"
            echo "Saved production DB → $PROD"
        fi
        if [ -f "$TEST" ]; then
            cp "$TEST" "$DB"
            # Remove WAL/SHM so SQLite starts fresh
            rm -f "$DB-wal" "$DB-shm"
            echo "Loaded test DB → $DB"
        else
            echo "Error: No test DB found at $TEST"
            exit 1
        fi
        ;;
    prod)
        if [ -f "$DB" ] && [ -s "$DB" ]; then
            cp "$DB" "$TEST"
            echo "Saved test DB → $TEST"
        fi
        if [ -f "$PROD" ]; then
            cp "$PROD" "$DB"
            rm -f "$DB-wal" "$DB-shm"
            echo "Loaded production DB → $DB"
        else
            echo "Error: No production DB found at $PROD"
            exit 1
        fi
        ;;
    status)
        echo "DB path: $DB"
        if [ -f "$DB" ]; then
            count=$(sqlite3 "$DB" "SELECT COUNT(*) FROM coffees;" 2>/dev/null || echo "?")
            echo "  Active DB: $count coffees"
        else
            echo "  Active DB: not found"
        fi
        if [ -f "$PROD" ]; then
            count=$(sqlite3 "$PROD" "SELECT COUNT(*) FROM coffees;" 2>/dev/null || echo "?")
            echo "  Production DB: $count coffees"
        else
            echo "  Production DB: not stored yet"
        fi
        if [ -f "$TEST" ]; then
            count=$(sqlite3 "$TEST" "SELECT COUNT(*) FROM coffees;" 2>/dev/null || echo "?")
            echo "  Test DB: $count coffees"
        else
            echo "  Test DB: not stored yet"
        fi
        ;;
    *)
        echo "Usage: $0 {test|prod|status}"
        exit 1
        ;;
esac
