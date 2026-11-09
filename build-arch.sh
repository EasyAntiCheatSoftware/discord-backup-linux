#!/bin/sh
set -eu
app_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$app_dir"
python3 tools/release.py
cd dist/arch
exec makepkg --force "$@"
