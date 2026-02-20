#!/bin/bash
set -e

cd "$(dirname "$0")"

# If not set up yet, run setup first
if [ ! -d "venv" ] || [ ! -d "node_modules" ]; then
  echo "→ Setup missing. Running Setup_Everything_Mac.command..."
  bash "./Setup_Everything_Mac.command"
fi

echo "→ Starting Adaptive Preference..."
npm start