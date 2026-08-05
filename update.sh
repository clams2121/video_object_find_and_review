#!/bin/bash
# Pulls the latest code and reinstalls dependencies. Run from anywhere -
# always operates on this script's own directory. Does not restart the
# server; if it's running, stop it (Shutdown button or Ctrl-C) and start it
# again afterward.
set -e
cd "$(dirname "$0")"

echo "Pulling latest code..."
git pull

echo "Installing dependencies..."
source .venv/bin/activate
pip install -r requirements.txt

echo "Update complete. Restart the app to apply changes: python -m app.main"
