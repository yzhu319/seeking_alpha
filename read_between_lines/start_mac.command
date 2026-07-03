#!/bin/bash
# Double-click this file to start Read Between Lines.
# First run: right-click -> Open (macOS blocks double-clicking unsigned
# scripts the first time only).
cd "$(dirname "$0")"

if ! command -v python3 &> /dev/null; then
  echo "Python 3 isn't installed on this Mac."
  echo "Get it from https://www.python.org/downloads/ then run this again."
  read -p "Press Enter to close..."
  exit 1
fi

# python3 refuses to create a venv in a path containing ":" (the PATH
# separator) — and folder names like "Seeking Alpha: Investment Ideas"
# have one. Fall back to a venv in the home directory in that case.
case "$PWD" in
  *:*) VENV="$HOME/.venvs/read-between-lines" ;;
  *)   VENV="$PWD/.venv" ;;
esac

if [ ! -d "$VENV" ]; then
  echo "First-time setup — this takes a minute..."
  python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"
pip install -q -r requirements.txt
echo "Starting Read Between Lines at http://localhost:8502 — your browser will open automatically."
streamlit run app.py --server.port 8502
