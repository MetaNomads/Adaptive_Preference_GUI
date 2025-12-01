#!/usr/bin/env bash
set -e  # Exit on ANY error

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Adaptive Preference - Installer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

##############################################
# 1. Detect Python
##############################################
echo "→ Detecting Python..."

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "❌ ERROR: No python found on PATH."
    exit 1
fi

echo "✓ Using Python: $(which $PYTHON_BIN)"
echo "✓ Python version: $($PYTHON_BIN --version)"

##############################################
# 2. Create venv
##############################################
echo "→ Creating virtual environment (.venv)..."

rm -rf .venv 2>/dev/null || true
$PYTHON_BIN -m venv .venv

if [ ! -d ".venv" ]; then
    echo "❌ ERROR: Failed to create .venv"
    exit 1
fi

echo "✓ .venv created"

##############################################
# 3. Activate venv
##############################################
echo "→ Activating virtual environment..."
source .venv/bin/activate

echo "✓ Activated venv: $VIRTUAL_ENV"

##############################################
# 4. Upgrade pip & wheel
##############################################
echo "→ Upgrading pip/setuptools/wheel..."
pip install --upgrade pip wheel setuptools

##############################################
# 5. Install dependencies
##############################################
if [ -f "requirements.txt" ]; then
    echo "→ Installing requirements..."
    pip install -r requirements.txt
else
    echo "❌ ERROR: requirements.txt not found."
    exit 1
fi

##############################################
# 6. Verify critical dependencies
##############################################
echo "→ Verifying Flask & SQLAlchemy..."

python - << 'EOF'
import flask, sqlalchemy
print("✓ Flask version:", flask.__version__)
print("✓ SQLAlchemy version:", sqlalchemy.__version__)
EOF

##############################################
# 7. Run governance tools (only if deps OK)
##############################################
echo "→ Running governance checks..."
python scripts/hollow_repo_guard.py
python scripts/program_integrity_guard.py
python scripts/syntax_guard.py
python scripts/critical_import_guard.py
python scripts/canon_guard.py

##############################################
# Done
##############################################
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Installation Completed Successfully!"
echo ""
echo "To activate the environment later:"
echo "    source .venv/bin/activate"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
