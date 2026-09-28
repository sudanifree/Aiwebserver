#!/bin/sh
set -eu

cd /var/www/html
mkdir -p rra log

if [ ! -f include/config.php ]; then
    cp include/config.php.dist include/config.php
    php <<'PHP'
<?php
$path = '/var/www/html/include/config.php';
$contents = file_get_contents($path);
$settings = [
    '$database_hostname = \'localhost\';' => '$database_hostname = ' . var_export(getenv('CACTI_DB_HOST'), true) . ';',
    '$database_default  = \'cacti\';' => '$database_default  = ' . var_export(getenv('CACTI_DB_NAME'), true) . ';',
    '$database_username = \'cactiuser\';' => '$database_username = ' . var_export(getenv('CACTI_DB_USER'), true) . ';',
    '$database_password = \'cactiuser\';' => '$database_password = ' . var_export(getenv('CACTI_DB_PASSWORD'), true) . ';',
    '$url_path = \'/cacti/\';' => '$url_path = \'/\';',
];
file_put_contents($path, str_replace(array_keys($settings), array_values($settings), $contents));
PHP
fi

chown www-data:www-data include/config.php rra log
chmod 0640 include/config.php
cron
exec apache2-foreground