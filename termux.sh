#!/usr/bin/env bash
# Script for running zeronet-conservancy in Termux on Android

REPO_DIR="zeronet-conservancy"
VENV_SCRIPT="start-venv.sh"

if [[ -d "$REPO_DIR" ]]; then
    (cd "$REPO_DIR" && git pull --ff-only)
else
    git clone https://github.com/zeronet-conservancy/zeronet-conservancy "$REPO_DIR"
fi

pkg update -y
pkg install -y python automake git binutils tor

echo "Starting tor..."
tor --ControlPort 9051 --CookieAuthentication 1 >/dev/null &

echo "Starting zeronet-conservancy..."
(cd "$REPO_DIR" && ./"$VENV_SCRIPT")
