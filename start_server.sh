#!/usr/bin/env bash
set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "============================================================"
echo "  Starting GCE Control Center GUI Server"
echo "============================================================"

echo "[INFO] Project root: $PROJECT_ROOT"

if command -v uv >/dev/null 2>&1; then
    echo "[INFO] Found uv package manager."
    echo "[INFO] Installing/using dependencies from requirements.txt..."
    exec uv run --with-requirements requirements.txt python gui/server.py
fi

if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    echo "[INFO] Found project virtual environment."
    exec "$PROJECT_ROOT/.venv/bin/python" gui/server.py
fi

if command -v python3 >/dev/null 2>&1; then
    echo "[INFO] Using Python 3 from system PATH."
    exec python3 gui/server.py
fi

if command -v python >/dev/null 2>&1; then
    echo "[INFO] Using Python from system PATH."
    exec python gui/server.py
fi

echo "[ERROR] Python environment not found! Please ensure Python or uv is installed."
exit 1
