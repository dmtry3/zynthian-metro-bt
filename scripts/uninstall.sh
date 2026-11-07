#!/bin/bash
# Удаление: sudo ./scripts/uninstall.sh (убирает ссылку на плагин и сервис, код и ключ остаются)
LV2_DIR="${LV2_DIR:-/usr/local/lib/lv2}"
rm -f "$LV2_DIR/metro_bt.lv2"
systemctl disable --now metro-bt.service 2>/dev/null
rm -f /etc/systemd/system/metro-bt.service
systemctl daemon-reload
echo "Удалено. Перезапусти Zynthian: sudo systemctl restart zynthian"
