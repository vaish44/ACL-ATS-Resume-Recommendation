#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PORT=1114
URL="http://127.0.0.1:$PORT"
CORE_IMPORTS="flask, flask_sqlalchemy, google.genai, openai, bs4, docx, olefile, PIL, pypdf, pytesseract"
PIP_FLAGS="--prefer-binary --only-binary=PyMuPDF --disable-pip-version-check"

PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" >/dev/null 2>&1 && "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"; then
    PYTHON="$cmd"; break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "Python 3.9+ is required. Install it (e.g. sudo apt install python3 python3-venv, or from python.org)."; exit 1
fi

if [ ! -x venv/bin/python ]; then
  echo "Creating virtual environment..."
  "$PYTHON" -m venv venv || { echo "Could not create venv. On Debian/Ubuntu run: sudo apt install python3-venv"; exit 1; }
fi
VENV_PY="venv/bin/python"

# python.org builds on macOS ship without trusted SSL certificates; use the bundle that comes with pip.
if [ "$(uname)" = "Darwin" ] && [ -z "$SSL_CERT_FILE" ]; then
  CERT_FILE=$("$VENV_PY" -c "import pip._vendor.certifi as c; print(c.where())" 2>/dev/null || true)
  if [ -n "$CERT_FILE" ]; then
    export SSL_CERT_FILE="$CERT_FILE" REQUESTS_CA_BUNDLE="$CERT_FILE"
  fi
fi

install_libraries() {
  echo "Installing required libraries..."
  "$VENV_PY" -m pip install --upgrade pip --quiet --disable-pip-version-check || true
  if ! "$VENV_PY" -m pip install $PIP_FLAGS -r requirements.txt; then
    echo "Full install failed. Installing packages one by one..."
    while IFS= read -r pkg || [ -n "$pkg" ]; do
      pkg=$(echo "$pkg" | tr -d '\r' | xargs)
      [ -z "$pkg" ] && continue
      "$VENV_PY" -m pip install $PIP_FLAGS --quiet "$pkg" || echo "WARNING: could not install $pkg"
    done < requirements.txt
  fi
  touch venv/.installed
}

if ! "$VENV_PY" -c "import $CORE_IMPORTS" 2>/dev/null || [ ! -f venv/.installed ] || [ requirements.txt -nt venv/.installed ]; then
  install_libraries
fi

if ! "$VENV_PY" -c "import $CORE_IMPORTS" 2>/dev/null; then
  echo ""
  echo "ERROR: Some required libraries could not be installed. Details:"
  "$VENV_PY" -c "import $CORE_IMPORTS" || true
  echo "Check your internet connection, then delete the 'venv' folder and run ./run.sh again."
  exit 1
fi
"$VENV_PY" -c "import fitz" 2>/dev/null || echo "Note: PyMuPDF is not available. PDFs are read with pypdf; scanned PDFs need an AI key."

grep -qE '(GEMINI|OPENAI)_API_KEY\s*=\s*"[^"]+"' env_app.py 2>/dev/null || echo "Tip: set GEMINI_API_KEY or OPENAI_API_KEY in env_app.py to enable AI evaluation."
command -v tesseract >/dev/null 2>&1 || echo "Tip: install Tesseract OCR for local scanned-resume reading (apt install tesseract-ocr / brew install tesseract)."

if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use. Opening $URL"
  (open "$URL" || xdg-open "$URL") >/dev/null 2>&1 || true
  exit 0
fi

open_browser() {
  for _ in $(seq 1 30); do
    if curl -s -o /dev/null "$URL/login" 2>/dev/null; then
      if [ "$(uname)" = "Darwin" ]; then open "$URL"; else xdg-open "$URL"; fi >/dev/null 2>&1 || true
      return
    fi
    sleep 1
  done
}
open_browser &

echo "Starting RR - Resume Recommendation on $URL  (Ctrl+C to stop)"
exec "$VENV_PY" app.py
