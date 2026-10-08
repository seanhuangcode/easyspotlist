#!/bin/bash
# Mac launcher: double-click this file (or run: bash start.command)
cd "$(dirname "$0")" || exit 1

fail() {
    echo
    echo "$1"
    read -r -p "Press Enter to close."
    exit 1
}

if [ ! -d .venv ]; then
    echo "Setting up for the first time..."
    command -v python3 >/dev/null || fail "Python 3 is needed. Get it from https://www.python.org/downloads/macos/"
    # Apple's built-in python3 ships an old, broken Tk; the python.org installer includes a working one.
    python3 -c "import sys, tkinter; sys.exit(tkinter.TkVersion < 8.6)" 2>/dev/null \
        || fail "Your Python is missing a working Tk (needed for the pop-up). Install Python from https://www.python.org/downloads/macos/ and try again."
    python3 -m venv .venv || fail "Setup failed while creating the virtual environment."
    .venv/bin/python -m pip install -q -r requirements.txt || { rm -rf .venv; fail "Setup failed while installing packages."; }
fi

.venv/bin/python main.py
read -r -p "Vibe Queue stopped. Press Enter to close."
