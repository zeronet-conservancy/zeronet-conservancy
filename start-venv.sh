#! /usr/bin/env bash

if [ ! -f venv/bin/activate ] ; then
    python3 -m venv venv
fi
source venv/bin/activate
python3 -m pip install -r requirements.txt
python3 zeronet.py $1 $2 $3 $4 $5 $6 $7 $8 $9
