#!/bin/sh
# Back up Ragolex, or restore a backup: the database and the uploaded files together.
#
#   tools/backup.sh create [directory]             writes ragolex-<UTC time>.tar.gz there (default .)
#   tools/backup.sh restore <archive> [--force]    restores one into an empty database and files folder
#
# Settings come from the environment, as for the API:
#   DATABASE_URL  the database (postgresql:// or postgresql+asyncpg://)
#   FILES_DIR     the uploaded files (default assets/files)
#
# It needs pg_dump, pg_restore and psql of the server's major version: a newer
# pg_restore sends settings an older server rejects (transaction_timeout before 17).
# With docker compose, the `backup` service has them: see docs/operations.md.
#
# An archive holds:
#   database.dump   pg_dump's custom format: tables, the vector extension, embeddings
#   files.tar       FILES_DIR as it was
#   manifest.txt    when it was made, the schema revision and how many files
#   SHA256SUMS      checked before anything is restored
set -eu

die() { echo "backup.sh: $*" >&2; exit 1; }

url=$(printf '%s' "${DATABASE_URL:?set DATABASE_URL}" | sed 's#^postgresql+[a-z0-9]*://#postgresql://#')
files_dir=${FILES_DIR:-assets/files}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

create() {
    target=${1:-.}
    mkdir -p "$target"
    archive="$target/ragolex-$(date -u +%Y%m%d-%H%M%S).tar.gz"
    [ -e "$archive" ] && die "$archive exists already"

    pg_dump --dbname="$url" --format=custom --no-owner --no-privileges --file="$work/database.dump"
    mkdir -p "$files_dir"
    tar -C "$files_dir" -cf "$work/files.tar" .
    revision=$(psql "$url" -tAc "SELECT version_num FROM alembic_version" 2>/dev/null || echo unknown)
    {
        echo "created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "schema_revision=$revision"
        echo "files=$(find "$files_dir" -type f | wc -l | tr -d ' ')"
    } > "$work/manifest.txt"
    (cd "$work" && sha256sum database.dump files.tar manifest.txt > SHA256SUMS)
    tar -C "$work" -czf "$archive" database.dump files.tar manifest.txt SHA256SUMS
    echo "Backed up to $archive ($(du -h "$archive" | cut -f1)):"
    sed 's/^/  /' "$work/manifest.txt"
}

restore() {
    archive=${1:-}
    force=${2:-}
    [ -n "$archive" ] || die "which archive? tools/backup.sh restore <archive> [--force]"
    [ -f "$archive" ] || die "$archive is not a file"
    [ -z "$force" ] || [ "$force" = "--force" ] || die "unknown option $force"

    tar -C "$work" -xzf "$archive"
    (cd "$work" && sha256sum --check --quiet SHA256SUMS) || die "$archive is damaged: its checksums do not match"

    # Restoring over data would mix two states; it takes --force to replace them.
    tables=$(psql "$url" -tAc "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
    if [ "$tables" != "0" ] && [ -z "$force" ]; then
        die "the database has tables already; restore into an empty one, or add --force to replace them"
    fi
    if [ -d "$files_dir" ] && [ -n "$(ls -A "$files_dir")" ] && [ -z "$force" ]; then
        die "$files_dir is not empty; restore into an empty folder, or add --force to replace it"
    fi

    pg_restore --dbname="$url" --clean --if-exists --no-owner --no-privileges --exit-on-error \
        "$work/database.dump"
    mkdir -p "$files_dir"
    if [ -n "$force" ]; then
        find "$files_dir" -mindepth 1 -delete
    fi
    tar -C "$files_dir" -xf "$work/files.tar"
    echo "Restored $archive:"
    sed 's/^/  /' "$work/manifest.txt"
}

case "${1:-}" in
    create) shift; create "$@" ;;
    restore) shift; restore "$@" ;;
    *) die "usage: tools/backup.sh create [directory] | restore <archive> [--force]" ;;
esac
