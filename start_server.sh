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
    exec uv run --with-requirements requirements.txt python gce/main/gui/server.py
fi

if [ -x "$PROJECT_ROOT/.venv_gce/bin/python" ]; then
    echo "[INFO] Found virtual environment at .venv_gce."
    exec "$PROJECT_ROOT/.venv_gce/bin/python" gce/main/gui/server.py
fi

if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    echo "[INFO] Found virtual environment at .venv."
    exec "$PROJECT_ROOT/.venv/bin/python" gce/main/gui/server.py
fi

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

if [ -n "$PYTHON_BIN" ]; then
    if "$PYTHON_BIN" -c "import flask" >/dev/null 2>&1; then
        echo "[INFO] Using $PYTHON_BIN from system PATH."
        exec "$PYTHON_BIN" gce/main/gui/server.py
    else
        echo "[INFO] Flask not found in system $PYTHON_BIN. Initializing .venv_gce virtual environment..."
        "$PYTHON_BIN" -m venv "$PROJECT_ROOT/.venv_gce"
        "$PROJECT_ROOT/.venv_gce/bin/python" -m pip install -r requirements.txt
        exec "$PROJECT_ROOT/.venv_gce/bin/python" gce/main/gui/server.py
    fi
fi

echo "[ERROR] Python environment not found! Please ensure Python or uv is installed."
exit 1

