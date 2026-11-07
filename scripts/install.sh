#!/bin/bash
# Установка на Zynthian: sudo ./scripts/install.sh
# Плагин: ссылка /usr/local/lib/lv2/metro_bt.lv2 -> build/metro_bt.lv2
# Сервис: /etc/systemd/system/metro-bt.service (работает от root, как сам Zynthian).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$(id -u)" != 0 ]; then echo "Запусти через sudo: sudo ./scripts/install.sh"; exit 1; fi
"$ROOT/scripts/build.sh"
LV2_DIR="${LV2_DIR:-/usr/local/lib/lv2}"
mkdir -p "$LV2_DIR"
ln -sfn "$ROOT/build/metro_bt.lv2" "$LV2_DIR/metro_bt.lv2"

if [ ! -f "$ROOT/config/band.json" ]; then
    echo "Внимание: нет config/band.json с ключом браслета. Сервис не запустится, пока его нет."
fi
cat > /etc/systemd/system/metro-bt.service <<UNIT
[Unit]
Description=Metro BT: метроном Zynthian на Mi Band 10
After=bluetooth.service
Wants=bluetooth.service

[Service]
ExecStart=/usr/bin/python3 $ROOT/scripts/metro_bt_service.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable metro-bt.service
systemctl restart metro-bt.service
echo "Готово. Перезапусти Zynthian: sudo systemctl restart zynthian"
echo "Лог сервиса: journalctl -u metro-bt -f"
