#!/usr/bin/env bash
# Prompt for API keys without echoing them and store them in .env (mode 600).
#   bash scripts/set_key.sh                          # Google Maps key
#   bash scripts/set_key.sh GEMINI_API_KEY XAI_API_KEY OPENAI_API_KEY
# Press Enter on an empty prompt to skip a key.
set -euo pipefail
cd "$(dirname "$0")/.."
[ $# -eq 0 ] && set -- GOOGLE_MAPS_API_KEY
umask 077
touch .env
for name in "$@"; do
  read -rsp "Paste $name (input hidden, Enter to skip): " k
  echo
  if [ -z "$k" ]; then echo "  skipped $name"; continue; fi
  if [ ${#k} -lt 20 ]; then echo "  that doesn't look like a key; $name not saved"; continue; fi
  { grep -v "^$name=" .env || true; printf '%s=%s\n' "$name" "$k"; } > .env.tmp
  mv .env.tmp .env
  echo "  saved $name"
done
unset k
chmod 600 .env
echo "Done. You can close this tab."
