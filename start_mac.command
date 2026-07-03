#!/bin/bash
# Double-click this file to start AI Infra Watch.
# First run: right-click -> Open (macOS blocks double-clicking unsigned
# scripts the first time only).
cd "$(dirname "$0")"

if ! command -v python3 &> /dev/null; then
  echo "Python 3 isn't installed on this Mac."
  echo "Get it from https://www.python.org/downloads/ then run this again."
  read -p "Press Enter to close..."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "First-time setup — this takes a minute..."
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt
echo "Starting AI Infra Watch — your browser will open automatically."
streamlit run app.py
