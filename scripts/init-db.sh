#!/bin/bash
set -e

MYSQL_HOST=${MYSQL_HOST:-db}
MYSQL_PORT=${MYSQL_PORT:-3306}
MYSQL_USER=${MYSQL_USER:-root}

DUMP_DIR=/tmp/db-dump

mysql_cmd() {
    mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" "$@"
}

echo "=== VMaNGOS Database Initialization ==="
echo ""

if mysql_cmd -e "USE mangos; SELECT 1 FROM creature_template LIMIT 1;" 2>/dev/null; then
    echo "Database already initialized. To re-import, drop databases first:"
    echo "  docker compose exec db mysql -uroot -pmangos -e 'DROP DATABASE mangos; DROP DATABASE realmd; DROP DATABASE characters; DROP DATABASE logs;'"
    exit 0
fi

echo "Downloading latest database dump from GitHub release..."
mkdir -p "$DUMP_DIR"
cd "$DUMP_DIR"

ASSET_URL=$(curl -sL "https://api.github.com/repos/vmangos/core/releases/tags/db_latest" | \
    python3 -c "
import json, sys
data = json.load(sys.stdin)
for asset in data.get('assets', []):
    name = asset['name']
    if name.endswith('.zip') and 'sqlite' not in name.lower():
        print(asset['browser_download_url'])
        break
")

if [ -z "$ASSET_URL" ]; then
    echo "ERROR: Could not find database dump in db_latest release."
    echo "Check: https://github.com/vmangos/core/releases/tag/db_latest"
    exit 1
fi

echo "Downloading: $ASSET_URL"
curl -L -o db-dump.zip "$ASSET_URL"
unzip -o db-dump.zip

DUMP_SUBDIR=$(find . -type d -name "db_dump" | head -1)
if [ -z "$DUMP_SUBDIR" ]; then
    echo "ERROR: db_dump directory not found in archive"
    exit 1
fi

echo ""
echo "Creating databases and user..."
mysql_cmd <<'SQL'
CREATE DATABASE IF NOT EXISTS realmd     DEFAULT CHARSET utf8 COLLATE utf8_general_ci;
CREATE DATABASE IF NOT EXISTS characters DEFAULT CHARSET utf8 COLLATE utf8_general_ci;
CREATE DATABASE IF NOT EXISTS mangos     DEFAULT CHARSET utf8 COLLATE utf8_general_ci;
CREATE DATABASE IF NOT EXISTS logs       DEFAULT CHARSET utf8 COLLATE utf8_general_ci;

CREATE USER IF NOT EXISTS 'mangos'@'%' IDENTIFIED BY 'mangos';
GRANT ALL PRIVILEGES ON realmd.*     TO 'mangos'@'%';
GRANT ALL PRIVILEGES ON characters.* TO 'mangos'@'%';
GRANT ALL PRIVILEGES ON mangos.*     TO 'mangos'@'%';
GRANT ALL PRIVILEGES ON logs.*       TO 'mangos'@'%';
FLUSH PRIVILEGES;
SQL

echo "Importing realmd database..."
mysql_cmd realmd < "$DUMP_SUBDIR/logon.sql"

echo "Configuring default realm..."
mysql_cmd realmd <<'REALM'
INSERT INTO realmlist (name, address, localAddress, localSubnetMask, port, icon, realmflags, timezone, allowedSecurityLevel, population, realmbuilds)
VALUES ('VMaNGOS', '127.0.0.1', '127.0.0.1', '255.255.255.0', 8085, 0, 0, 0, 0, 0, '5875')
ON DUPLICATE KEY UPDATE address=VALUES(address), localAddress=VALUES(localAddress), port=VALUES(port), realmflags=0;
REALM

echo "Importing logs database..."
mysql_cmd logs < "$DUMP_SUBDIR/logs.sql"

echo "Importing characters database..."
mysql_cmd characters < "$DUMP_SUBDIR/characters.sql"

echo "Importing world (mangos) database... (this takes a while)"
mysql_cmd mangos < "$DUMP_SUBDIR/mangos.sql"

echo ""
echo "=== Database initialization complete ==="
echo ""
echo "  realmd      auth/login data"
echo "  characters  player data"
echo "  mangos      world data"
echo "  logs        server logs"
echo ""
echo "MySQL user 'mangos' (password: mangos) has full access."

rm -rf "$DUMP_DIR"
