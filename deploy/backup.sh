#!/usr/bin/env bash
set -euo pipefail
umask 077
configuration="${MYSQL_BACKUP_CNF:-/etc/gupiao/mysql-backup.cnf}"
directory="${BACKUP_DIRECTORY:-/var/backups/gupiao}"
database="${BACKUP_DATABASE:-gupiao}"
if [[ ! -r "$configuration" || ! "$database" =~ ^[A-Za-z0-9_]+$ ]]; then
    printf '%s\n' 'Backup configuration missing or database name invalid' >&2
    exit 1
fi
mkdir -p -- "$directory"
temporary="$(mktemp "$directory/.backup-XXXXXXXX.sql.gz")"
trap 'rm -f -- "$temporary"' EXIT
mysqldump --defaults-extra-file="$configuration" --single-transaction --quick --set-gtid-purged=OFF --no-tablespaces "$database" | gzip > "$temporary"
filename="$directory/$database-$(date -u +%Y%m%dT%H%M%SZ)-$$.sql.gz"
mv -- "$temporary" "$filename"
trap - EXIT
printf '%s\n' "$filename"
