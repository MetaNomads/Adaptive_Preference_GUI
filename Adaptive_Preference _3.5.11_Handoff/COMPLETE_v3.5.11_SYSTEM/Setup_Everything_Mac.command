#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=============================================="
echo " Adaptive Preference - Mac Setup"
echo "=============================================="
echo

# Check Node
if ! command -v node >/dev/null 2>&1; then
  echo "❌ Node.js not found."
  echo "Install Node.js (LTS) from nodejs.org, then re-run this file."
  exit 1
fi

# Check Python
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "❌ Python not found."
  echo "Install Python 3.10+ (recommended 3.11+), then re-run this file."
  exit 1
fi

echo "✓ Using Node: $(node -v)"
echo "✓ Using Python: $($PYTHON_BIN --version)"
echo

# JS deps
if [ ! -d "node_modules" ]; then
  echo "→ Installing JavaScript packages..."
  npm install
fi

# Python venv + deps
if [ ! -d "venv" ]; then
  echo "→ Creating Python virtual environment (venv)..."
  $PYTHON_BIN -m venv venv
fi

echo "→ Activating venv..."
source venv/bin/activate

echo "→ Installing Python requirements..."
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt

echo
echo "✅ Setup complete."
echo "You can now run Start_Adaptive_Preference_Mac.command"
echo
read -n 1 -s -r -p "Press any key to close..."
echo