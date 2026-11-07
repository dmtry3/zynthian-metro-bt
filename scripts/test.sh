#!/bin/bash
# Офлайн-тесты: протокол браслета (Python) и метроном (ядро + плагин на имитации хоста).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -s tests
"$ROOT/scripts/build.sh" >/dev/null
mkdir -p build_test
gcc -O1 -g -Wall $(pkg-config --cflags lv2) -o build_test/test_metro test/test_metro.c src/metro_core.c -lm -ldl
./build_test/test_metro "$ROOT/build/metro_bt.lv2/metro_bt.so"
