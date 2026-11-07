#!/bin/bash
# Собирает LV2-плагин в build/metro_bt.lv2 (на Pi или в WSL).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
B="$ROOT/build/metro_bt.lv2"
mkdir -p "$B"
cp "$ROOT/lv2/manifest.ttl" "$ROOT/lv2/metro_bt.ttl" "$B/"
gcc -O2 -fPIC -shared -Wall $(pkg-config --cflags lv2) \
    -o "$B/metro_bt.so" "$ROOT/src/metro_bt.c" "$ROOT/src/metro_core.c" -lm -lpthread
echo "Собрано: $B"
