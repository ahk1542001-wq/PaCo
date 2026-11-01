#!/usr/bin/env bash
# PageOps Agent launcher.
# This VM's NO_PROXY value (IPv6 entries) crashes httpx URL parsing,
# so both variables are unset before the bot starts.
set -euo pipefail
cd "$(dirname "$0")"

unset NO_PROXY no_proxy

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec .venv/bin/python -m pageops.bot
