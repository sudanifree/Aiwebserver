#!/bin/sh
set -eu

cd /var/www/html
mkdir -p rra log

if [ ! -f include/config.php ]; then
    cp include/config.php.dist include/config.php
fi

php <<'PHP'
<?php
$path = '/var/www/html/include/config.php';
$contents = file_get_contents($path);
$settings = [
    '/\$database_hostname\s*=\s*[^;]*;/' => '$database_hostname',
    '/\$database_default\s*=\s*[^;]*;/' => '$database_default',
    '/\$database_username\s*=\s*[^;]*;/' => '$database_username',
    '/\$database_password\s*=\s*[^;]*;/' => '$database_password',
    '/\$database_port\s*=\s*[^;]*;/' => '$database_port',
    '/\$url_path\s*=\s*[^;]*;/' => '$url_path',
];
$values = [
    '$database_hostname' => getenv('CACTI_DB_HOST'),
    '$database_default' => getenv('CACTI_DB_NAME'),
    '$database_username' => getenv('CACTI_DB_USER'),
    '$database_password' => getenv('CACTI_DB_PASSWORD'),
    '$database_port' => '3306',
    '$url_path' => '/',
];
foreach ($settings as $pattern => $variable) {
    $replacement = $variable . ' = ' . var_export($values[$variable], true) . ';';
    $contents = preg_replace_callback($pattern, static fn() => $replacement, $contents, 1);
}
file_put_contents($path, $contents);
PHP

if [ ! -d /var/lib/mysql/mysql ]; then
    mariadb-install-db --user=mysql --datadir=/var/lib/mysql --auth-root-authentication-method=normal
fi

chown -R mysql:mysql /var/lib/mysql
mariadbd --user=mysql --datadir=/var/lib/mysql --bind-address=127.0.0.1 \
    --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci \
    --max-allowed-packet=500M --innodb-file-per-table=1 \
    --innodb-doublewrite=OFF --innodb-use-atomic-writes=ON \
    --sql-mode=NO_ENGINE_SUBSTITUTION &
database_pid=$!

ready=0
for attempt in $(seq 1 60); do
    if mariadb-admin --user=root ping --silent >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 1
done
if [ "$ready" -ne 1 ]; then
    echo "MariaDB did not become ready" >&2
    exit 1
fi

case "$CACTI_DB_PASSWORD" in
    ''|*[!a-fA-F0-9]*)
        echo "CACTI_DB_PASSWORD must contain only hexadecimal characters" >&2
        exit 1
        ;;
esac

mariadb --user=root <<SQL
CREATE DATABASE IF NOT EXISTS cacti CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'cactiuser'@'localhost' IDENTIFIED BY '${CACTI_DB_PASSWORD}';
ALTER USER 'cactiuser'@'localhost' IDENTIFIED BY '${CACTI_DB_PASSWORD}';
GRANT ALL PRIVILEGES ON cacti.* TO 'cactiuser'@'localhost';
CREATE USER IF NOT EXISTS 'cactiuser'@'127.0.0.1' IDENTIFIED BY '${CACTI_DB_PASSWORD}';
ALTER USER 'cactiuser'@'127.0.0.1' IDENTIFIED BY '${CACTI_DB_PASSWORD}';
GRANT ALL PRIVILEGES ON cacti.* TO 'cactiuser'@'127.0.0.1';
GRANT SELECT ON mysql.time_zone_name TO 'cactiuser'@'localhost';
GRANT SELECT ON mysql.time_zone_name TO 'cactiuser'@'127.0.0.1';
SQL

timezone_count=$(mariadb --user=root --batch --skip-column-names \
    --execute="SELECT COUNT(*) FROM mysql.time_zone_name")
if [ "$timezone_count" -eq 0 ]; then
    mariadb-tzinfo-to-sql /usr/share/zoneinfo | mariadb --user=root mysql
fi

table_count=$(mariadb --user=root --batch --skip-column-names \
    --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='cacti'")
if [ "$table_count" -eq 0 ]; then
    mariadb --user=root cacti < /var/www/html/cacti.sql
fi

printf '%s\n' \
    'agentAddress udp:127.0.0.1:161' \
    'agentuser Debian-snmp Debian-snmp' \
    'rocommunity public 127.0.0.1 .1' \
    'sysLocation Local Cacti container' \
    'sysContact local' \
    > /etc/snmp/snmpd.conf

chown www-data:www-data include/config.php rra log
chmod 0640 include/config.php
cron
snmpd -f -Lo &
snmp_pid=$!
apache2-foreground &
apache_pid=$!
trap 'kill "$apache_pid" "$database_pid" "$snmp_pid" 2>/dev/null || true' TERM INT
wait "$apache_pid"