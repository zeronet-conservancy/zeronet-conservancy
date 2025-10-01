#!/usr/bin/env bash

SAMEDIR="$(dirname $(realpath $0))"; cd "$SAMEDIR" || exit # directory where this .sh file is located
VENVPATH="venv/bin/activate"

if [ ! -f "$VENVPATH" ]; then
    python3 -m venv venv
fi

source "$VENVPATH"
python3 -m pip install -r requirements.txt
python3 zeronet.py "$@"
