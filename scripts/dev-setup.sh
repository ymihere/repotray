#!/bin/sh
# Create .venv (with system site-packages, so gi is visible), bootstrap pip without
# needing a system pip, and install repotray in editable mode with the dev extras.
# Idempotent: re-running it upgrades nothing it does not have to.
set -eu

cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}

"$PY" - <<'EOF'
import sys
if sys.version_info < (3, 11):
    sys.exit(f"repotray needs Python >= 3.11, found {sys.version.split()[0]}")
EOF

if [ ! -x .venv/bin/python ]; then
    "$PY" -m venv --without-pip --system-site-packages .venv
fi

if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
    if ! .venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1; then
        echo "ensurepip unavailable, downloading get-pip.py" >&2
        tmp=$(mktemp -d)
        trap 'rm -rf "$tmp"' EXIT
        if command -v curl >/dev/null 2>&1; then
            curl -sSf https://bootstrap.pypa.io/get-pip.py -o "$tmp/get-pip.py"
        else
            wget -q https://bootstrap.pypa.io/get-pip.py -O "$tmp/get-pip.py"
        fi
        .venv/bin/python "$tmp/get-pip.py" -q
    fi
fi

.venv/bin/python -m pip install -q -e '.[dev]'
echo "ready: . .venv/bin/activate && pytest -q"
