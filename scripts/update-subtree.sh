#!/bin/sh
set -eu
if [ "$#" -gt 2 ]; then
    echo 'Usage: update-subtree.sh [SHARED_REPOSITORY_PATH_OR_URL [REF]]' >&2
    exit 2
fi
RW_UPDATE_SOURCE=${1:-https://github.com/RimWorld-mods-patches/rimworld-dev-skills.git}
RW_UPDATE_REF=${2:-main}
RW_UPDATE_ROOT=$(git rev-parse --show-toplevel)
cd "$RW_UPDATE_ROOT"
if [ -n "$(git status --porcelain)" ]; then
    echo 'Commit or preserve local changes before updating the shared subtree.' >&2
    exit 1
fi
git subtree pull --prefix=.shared/rimworld-dev-skills "$RW_UPDATE_SOURCE" "$RW_UPDATE_REF" --squash
