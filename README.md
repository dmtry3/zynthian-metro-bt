# zynthian-metro-bt

[English](README.en.md) · Русский

Метроном Zynthian на браслете Xiaomi Smart Band 10: каждая доля приходит вибрацией.
Удобно на сцене и в наушниках: темп чувствуешь рукой, клик не нужен.

Видео: https://youtu.be/12LIlUnqwzE

Проверено на Zynthian V5 (Raspberry Pi 5, Debian bookworm) с Xiaomi Smart Band 10.
Сам Zynthian не меняется: ставится LV2-плагин и отдельный сервис.

```
[цепочка Zynthian]                         [сервис на Pi]
LV2 MIDI tool «Metro BT»  --UDP localhost-->  metro-bt (Python, systemd)  --Bluetooth SPP-->  Mi Band 10
```

## Что нужно
- Zynthian V5 (или другой Linux с LV2-хостом и BlueZ), `gcc`, `lv2-dev`, `python3-cryptography`.
- Xiaomi Smart Band 10, привязанный к Mi Fitness (нужен его ключ, см. ниже).
- Другие браслеты Xiaomi с протоколом SPP V2, возможно, тоже заработают, но не проверялись.

## Как это работает
Браслет подключается к Pi напрямую по Bluetooth Classic (SPP), как в Gadgetbridge. Нужен ключ браслета (authkey).
Его можно достать из логов Mi Fitness (zip с `XiaomiFit.main.log`, поле `encryptKey`).

Ограничения:
- Пока браслет подключён к Pi, телефон к нему подключиться не может.
- Если браслет привязан к телефону по Bluetooth, Pi получает `Connection refused`, даже при выключенном
  Bluetooth на телефоне. Помогает удалить браслет из списка устройств Bluetooth телефона (ключ не меняется).
- Если отвязать браслет от Mi Fitness или сбросить, ключ меняется: его надо достать заново.
- Ключ — секрет: не публикуй `config/band.json` и zip с логами.

## Установка и проверка на Pi
```bash
git clone https://github.com/dmtry3/zynthian-metro-bt.git
cd zynthian-metro-bt
```
Ключ в репозиторий не входит. Его надо положить на Pi отдельно, одним из двух способов:
```bash
# способ 1: скопировать готовый конфиг из WSL
scp config/band.json root@<ip-пи>:zynthian-metro-bt/config/   # или заполни по образцу config/band.example.json
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
- **Accent**: сильная доля втрое длиннее.
- **Pulse ms**: длина вибрации.
- **Advance ms**: на сколько отправлять долю раньше, чтобы компенсировать задержку Bluetooth.

Доли идут только при запущенном транспорте Zynthian, по его сетке и темпу. Стоп транспорта сразу гасит вибрацию.
Пока плагин в цепочке, сервис держит связь с браслетом. Через 10 с после удаления плагина отключается.
`band_test.py` не сможет подключиться, пока подключён сервис: `sudo systemctl stop metro-bt`.

Лог: `journalctl -u metro-bt -f`. Удаление: `sudo ./scripts/uninstall.sh`.

## Тесты (WSL, без Bluetooth)
```bash
./scripts/test.sh
```

## Лицензия
AGPL-3.0. Протокол браслета портирован из [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge), спасибо его авторам.

Проект не связан с Xiaomi и Zynthian. Используй на свой риск.
