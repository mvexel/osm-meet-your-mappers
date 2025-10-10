#!/usr/bin/env bash

set -euo pipefail

if [[ -z "${DEPLOY_DIR:-}" ]]; then
  echo "DEPLOY_DIR is required" >&2
  exit 1
fi

cd "${DEPLOY_DIR}"

if [[ -f scripts/deploy.sh ]]; then
  if ! git ls-files --error-unmatch scripts/deploy.sh >/dev/null 2>&1; then
    rm -f scripts/deploy.sh
  fi
fi

git fetch --prune
git checkout "${DEPLOY_BRANCH:-main}"
git pull --ff-only origin "${DEPLOY_BRANCH:-main}"

docker compose --profile production pull
docker compose --profile production up -d
