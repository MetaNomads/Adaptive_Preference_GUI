#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="${PROJECT_NAME:-AdaptivePreferenceGUI_v3.5.11}"
LOG_DIR="${LOG_DIR:-logs}"
REQUIRE_DOCKER="${REQUIRE_DOCKER:-0}"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/install_$(date +%s).log"

# Dual logging: console + file
exec > >(tee -i "$LOG_FILE") 2>&1

echo "==> [$PROJECT_NAME] Starting install at $(date)"

# 1. Find Python
PYTHON_CMD=$(command -v python3 || command -v python || true)
if [ -z "${PYTHON_CMD}" ]; then
  echo "❌ Critical: No python or python3 found on PATH."
  exit 1
fi
echo "Using Python: ${PYTHON_CMD}"

# 2. Ensure venv
if [ -z "${VIRTUAL_ENV:-}" ]; then
  echo "⚠️  No virtualenv detected. Creating .venv at repo root..."
  "${PYTHON_CMD}" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  echo "✅ Activated .venv"
else
  echo "✅ Running inside existing virtualenv: $VIRTUAL_ENV"
fi

# 3. Optional Docker check
if [ "${REQUIRE_DOCKER}" -eq 1 ]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "❌ Fatal: Docker is required but not found. Set REQUIRE_DOCKER=0 to skip."
    exit 1
  fi
  echo "✅ Docker is available"
fi

# 4. Install Python dependencies (adapt as needed)
if [ -f "requirements.txt" ]; then
  echo "==> Installing requirements.txt..."
  pip install -r requirements.txt
elif [ -f "pyproject.toml" ]; then
  echo "==> Detected pyproject.toml. Please install dependencies with your chosen tool (poetry/pip)."
else
  echo "==> No requirements.txt or pyproject.toml found; skipping dependency install."
fi

# 5. Run governance guards
echo "==> Running governance guards..."
python scripts/hollow_repo_guard.py
python scripts/program_integrity_guard.py
python scripts/syntax_guard.py
python scripts/critical_import_guard.py
python scripts/canon_guard.py

# 6. Project-specific steps (customized for Adaptive Preference GUI)
echo "==> Running project-specific setup steps for AdaptivePreferenceGUI..."

# If you're using SQLite in backend/.env, the app can usually create tables on first run.
# If you're using Postgres, you'll likely apply database/schema.sql yourself.
if [ -f "database/schema.sql" ]; then
  echo "==> database/schema.sql is present."
  echo "    If DATABASE_URL points to Postgres, apply the schema manually, e.g.:"
  echo "    psql \"$DATABASE_URL\" -f database/schema.sql"
fi

# Optionally run tests
if [ -d "tests" ]; then
  echo "==> Running tests..."
  pytest || { echo '❌ Tests failed'; exit 1; }
fi

echo "✅ [$PROJECT_NAME] Install completed successfully."
