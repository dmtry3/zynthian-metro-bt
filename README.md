# zynthian-metro-bt

Метроном Zynthian на браслете Xiaomi Smart Band 10: каждая доля приходит вибрацией.

Статус: этап 3. Связь с браслетом проверена на Pi. Плагин «Metro BT» в цепочке шлёт доли, сервис вибрирует.

## Как это работает
Браслет подключается к Pi напрямую по Bluetooth Classic (SPP), как в Gadgetbridge. Нужен ключ браслета (authkey).
Его можно достать из логов Mi Fitness (zip с `XiaomiFit.main.log`, поле `encryptKey`).

Пока браслет подключён к Pi, телефон к нему подключиться не может. Перед проверкой выключи Bluetooth на телефоне.

## Установка и проверка на Pi
```bash
git clone https://github.com/dmtry3/zynthian-metro-bt.git
cd zynthian-metro-bt
```
Ключ в репозиторий не входит. Его надо положить на Pi отдельно, одним из двух способов:
```bash
# способ 1: скопировать готовый конфиг из WSL
scp config/band.json root@<ip-пи>:zynthian-metro-bt/config/
# способ 2: скопировать на Pi zip с логами и достать ключ там
python3 scripts/extract_key.py /путь/к/логам.zip
```
Проверка связи:
```bash
python3 scripts/band_test.py scan        # найти браслет, запомнить MAC
python3 scripts/band_test.py buzz -v     # подключиться, авторизоваться, одна вибрация
python3 scripts/band_test.py beats 100   # 16 долей в темпе 100 BPM
```
Нужен пакет `python3-cryptography` (в Zynthian обычно уже стоит).

## Плагин в цепочке
```bash
cd ~/zynthian-metro-bt && git pull
sudo ./scripts/install.sh            # сборка плагина + сервис metro-bt (systemd)
sudo systemctl restart zynthian
```
В Zynthian добавь в любую MIDI-цепочку MIDI tool **Metro BT**. Контроллеры:
- **On**: метроном вкл/выкл. Его можно назначить на кнопку футсвитча через MIDI learn.
- **Accent**: сильная доля вдвое длиннее.
- **Pulse ms**: длина вибрации.
- **Advance ms**: на сколько отправлять долю раньше, чтобы компенсировать задержку Bluetooth.

Транспорт играет: доли идут по сетке Zynthian. Транспорт стоит: свои часы в темпе Zynthian, с сильной доли.
Пока плагин в цепочке, сервис держит связь с браслетом. Через 10 с после удаления плагина отключается.
`band_test.py` не сможет подключиться, пока подключён сервис: `sudo systemctl stop metro-bt`.

Лог: `journalctl -u metro-bt -f`. Удаление: `sudo ./scripts/uninstall.sh`.

## Тесты (WSL, без Bluetooth)
```bash
./scripts/test.sh
```

## Лицензия
AGPL-3.0. Протокол браслета портирован из [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge).
