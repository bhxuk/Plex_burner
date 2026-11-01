#!/bin/sh
# Container entrypoint. The repo is mounted at /app (see docker-compose.yml), so code
# updated by the in-app updater is picked up on restart. If requirements.txt changed
# since the image was built, install the new packages before starting.
set -e
cd /app
git config --global --add safe.directory /app 2>/dev/null || true

MARK=/usr/local/.plex-burner-req
HASH="$(sha256sum requirements.txt | cut -d' ' -f1)"
if [ "$(cat "$MARK" 2>/dev/null)" != "$HASH" ]; then
  echo "[entrypoint] requirements changed, installing packages"
  pip install -q --root-user-action=ignore -r requirements.txt && echo "$HASH" > "$MARK"
fi

exec python -m app.main
