#!/usr/bin/env bash
# Regenerates api/requirements.lock: exact pins for every third-party runtime
# dependency of gambrole-api + gambrole-core. Render's build and CI both
# install from it, so what CI tests is what Render deploys.
#
#   scripts/lock_api_deps.sh            # re-resolve, keeping existing pins
#   scripts/lock_api_deps.sh --upgrade  # bump everything to the latest allowed
#   scripts/lock_api_deps.sh --upgrade-package fastapi  # bump one package
#
# Needs uv (https://docs.astral.sh/uv/). The two local packages themselves are
# excluded — they're installed from their source dirs with --no-deps.
set -euo pipefail
cd "$(dirname "$0")/.."
printf './core\n./api\n' | uv pip compile - \
  --python-version 3.13 \
  --universal \
  --no-emit-package gambrole-core \
  --no-emit-package gambrole-api \
  --custom-compile-command "scripts/lock_api_deps.sh" \
  -o api/requirements.lock \
  "$@"
