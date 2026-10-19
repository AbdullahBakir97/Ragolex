#!/bin/sh
# Run published images of Mini RAG on this server with docker compose, and go
# back to the images before when the new ones do not come up healthy.
#
#   tools/deploy.sh <tag>      run the images tagged <tag>, e.g. sha-1a2b3c4 or 1.4.0
#   tools/deploy.sh rollback   run the images deployed before the current ones
#   tools/deploy.sh status     the tags deployed now and before
#
# Run it in the folder with compose.yaml and .env. The API applies database
# migrations as it starts, so a release's migrations must leave the schema
# usable by the release before it, for a rollback to work.
#
# Settings, from the environment:
#   MINI_RAG_IMAGES  where the images are (default ghcr.io/abdullahbakir97):
#                    <MINI_RAG_IMAGES>/mini-rag and <MINI_RAG_IMAGES>/mini-rag-web
#   DEPLOY_TIMEOUT   seconds the services have to become healthy (default 180)
#   COMPOSE          the compose command (default "docker compose")
#
# The tags deployed are kept in .deploy/current and .deploy/previous.
set -eu

images=${MINI_RAG_IMAGES:-ghcr.io/abdullahbakir97}
timeout=${DEPLOY_TIMEOUT:-180}
compose=${COMPOSE:-docker compose}
state=.deploy

say() { echo "deploy: $*"; }
fail() { echo "deploy: $*" >&2; exit 1; }

# Tags are what registries allow: letters, digits, dots, dashes and underscores.
valid_tag() {
    case $1 in '' | .* | -* | *[!A-Za-z0-9._-]*) return 1 ;; esac
    [ ${#1} -le 128 ]
}

# Pull the images of a tag and start them, waiting until they are healthy.
run() (
    export MINI_RAG_IMAGE="$images/mini-rag:$1" MINI_RAG_WEB_IMAGE="$images/mini-rag-web:$1"
    # shellcheck disable=SC2086 # $compose is a command and its arguments.
    $compose pull --quiet app web &&
        $compose up --detach --no-build --wait --wait-timeout "$timeout" app web
)

# What went wrong, for the job's log.
diagnose() {
    # shellcheck disable=SC2086
    $compose ps || true
    # shellcheck disable=SC2086
    $compose logs --no-color --tail 50 app web || true
}

read_tag() { cat "$state/$1" 2>/dev/null || true; }

deploy() {
    tag=$1
    valid_tag "$tag" || fail "'$tag' is not an image tag"
    [ -f compose.yaml ] || fail "there is no compose.yaml here: run me in the deployment's folder"
    [ -f .env ] || fail "there is no .env here: copy .env.example and fill it in first"
    mkdir -p "$state"
    current=$(read_tag current)
    say "deploying $tag${current:+ (now $current)}"
    if run "$tag"; then
        if [ "$current" != "$tag" ]; then
            [ -z "$current" ] || echo "$current" > "$state/previous"
            echo "$tag" > "$state/current"
        fi
        say "$tag is up and healthy"
        return 0
    fi
    diagnose
    if [ -n "$current" ] && [ "$current" != "$tag" ]; then
        say "$tag did not come up healthy: rolling back to $current"
        run "$current" || fail "the rollback to $current failed too: see docker compose ps and logs"
        fail "$tag did not come up healthy; $current runs again"
    fi
    fail "$tag did not come up healthy, and there is nothing to roll back to"
}

rollback() {
    previous=$(read_tag previous)
    current=$(read_tag current)
    [ -n "$previous" ] || fail "there is no earlier deployment to roll back to"
    say "rolling back from ${current:-nothing} to $previous"
    if ! run "$previous"; then
        diagnose
        fail "$previous did not come up healthy"
    fi
    echo "$previous" > "$state/current"
    [ -z "$current" ] || echo "$current" > "$state/previous"
    say "$previous is up and healthy"
}

case ${1:-} in
    rollback) rollback ;;
    status)
        echo "current:  $(read_tag current)"
        echo "previous: $(read_tag previous)"
        ;;
    '' | -h | --help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; [ -n "${1:-}" ] ;;
    *) deploy "$1" ;;
esac
