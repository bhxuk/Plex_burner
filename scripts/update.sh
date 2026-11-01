#!/bin/sh
# Pulls the latest commit and rebuilds the Plex Burner container.
# Run by the dashboard's Update button (inside the plex-burner image) or by hand on the server.
set -e
git config --global --add safe.directory "$(pwd)"
git pull --ff-only
APP_COMMIT="$(git rev-parse HEAD)"
export APP_COMMIT
docker compose up -d --build
echo "Plex Burner is now at $(git rev-parse --short HEAD)"
