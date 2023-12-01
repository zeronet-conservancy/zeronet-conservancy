#!/usr/bin/env bash

VENVPATH="venv/bin/activate"

if [ ! -f "$VENVPATH" ]; then
    python3 -m venv venv
fi

source "$VENVPATH"
python3 -m pip install -r requirements.txt
python3 zeronet.py "$@"
