#!/usr/bin/env bash
# Creates random passwords for Zabbix in ../secrets/ (ignored by git).
# Existing files are kept, so running it again never changes a password.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p secrets
chmod 700 secrets                  # only your host user can open the folder

for name in \
  zabbix_db_password \
  zabbix_admin_password \
  zbx_mysql_monitor_password \
  zbx_rabbitmq_monitor_password \
  tomcat_jmx_password
do
  file="secrets/$name.txt"
  if [ -s "$file" ]; then
    echo "keep     $file"
  else
    openssl rand -base64 32 | tr -d '/+=\n' | head -c 24 > "$file"
    echo "created  $file"
  fi
  chmod 644 "$file"                # readable by the non-root users in the containers
done
