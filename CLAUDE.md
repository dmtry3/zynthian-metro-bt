# zynthian-metro-bt

## Цель
Метроном Zynthian на браслете: каждая доля приходит вибрацией на Xiaomi Smart Band 10.
Zynthian V5 (Raspberry Pi 5). Сам Zynthian не меняем: ставим только свои файлы.

## Как устроено
```
[цепочка Zynthian]                          [отдельный сервис на Pi]
LV2 MIDI-плагин "Metro BT"  --UDP 127.0.0.1-->  metro_bt (Python, systemd)  --Bluetooth SPP-->  Mi Band 10
  time:Position -> доли, BPM                     расписание вибраций,
  контроллеры: вкл, акцент, сдвиг                 подключение и авторизация
```
- Плагин добавляется в цепочку как MIDI tool, MIDI пропускает насквозь (как generative-arp).
  Из `run()` в сокет писать нельзя: доли идут через lock-free очередь в свой поток плагина, тот шлёт UDP.
- Bluetooth живёт только в сервисе: переподключение и шифрование в аудиопоток не тащим.
- Вкл/выкл метронома: toggle-контроллер плагина «On». Его мапят на кнопку MIDI-футсвитча штатным
  MIDI learn Zynthian, без правок Zynthian. При выключении сервис сразу гасит вибрацию.
- Задержку Bluetooth компенсируем: сервис знает темп и шлёт вибрацию заранее на «сдвиг» мс.

## Протокол браслета (по Gadgetbridge)
Портировано из Gadgetbridge (codeberg.org/Freeyourgadget/Gadgetbridge, AGPL-3.0), поэтому лицензия проекта AGPL-3.0.
Файлы-образцы: `XiaomiSppPacketV1/V2`, `XiaomiSppProtocolV2`, `XiaomiAuthService`, `MiBand10Coordinator`,
proto в `GBProtobufGenerator/src/main/proto/xiaomi/`.
- Band 10 работает через Bluetooth Classic, SPP (RFCOMM), а не через BLE. Протокол SPP V2.
- Порядок: V1-запрос версии → V2 session config → nonce (cmd 1/26) → ответ браслета → cmd 1/27 → авторизован.
- Ключ: поле `encryptKey` (16 байт hex) из логов Mi Fitness (`XiaomiFit.main.log`). Это и есть authkey.
- Данные после авторизации: AES-CTR, IV = ключ (так у Xiaomi). Информация об устройстве в авторизации: AES-CCM, тег 4 байта.
- Вибрация: команды «вибрируй один раз» нет. Пробуем find-watch (тип 2, подтип 18, `findDevice` 0 = старт, 1 = стоп)
  и свои узоры вибрации (подтипы 46/58/61).
- На Pi: RFCOMM канал 5, версия SPP 03 00 41. Пользователь `zynthian` не в группе bluetooth: проверки через sudo, сервис от root.
- Пока браслет подключён к Pi, телефон к нему подключиться не может.

## Репозиторий
Публичный: github.com/dmtry3/zynthian-metro-bt, ветка `main`. На Pi ставится через `git clone`, ключ копируется отдельно (`scp config/band.json`).

## Секреты
`*.zip` с логами и `config/band.json` с ключом лежат в `.gitignore`. Ключ не печатать целиком, не коммитить.
Если браслет отвязать от Mi Fitness или сбросить, ключ меняется: нужен новый zip.

## Структура
```
band/      протокол и клиент браслета на Python (без зависимостей от Zynthian)
scripts/   extract_key.py, band_test.py, install.sh, deploy.sh
tests/     офлайн-тесты протокола (WSL, без Bluetooth)
lv2/, src/ LV2-плагин «Metro BT»
test/      тест ядра и плагина на C
config/    band.json (не в git), band.example.json
```

## Правила
- Python 3.11 (как на Zynthian V5, Debian bookworm): без синтаксиса новее 3.11.
- Зависимости: только `python3-cryptography` (есть в Debian). Новые зависимости без вопроса не добавлять.
- Плагин (этап 3): C, LV2, по образцу `../zynthian-generative-arp` и `../zynthian-midi-looper`.
  В `run()` никаких malloc, блокировок, printf, сокетов.
- Соседние проекты только читаем, ничего в них не меняем. `../midi-looper` к делу не относится.
- Работать маленькими шагами, следующий этап только после проверки текущего на устройстве.
- Общение и документация на русском. Коммиты маленькие, сообщения на русском.

## Проверка
- WSL: `./scripts/test.sh`: протокол и сервис (Python, поддельный браслет), ядро метронома и `.so` на имитации хоста (C).
- Плагин: URI `urn:metrobt:metro`, бандл `metro_bt.lv2`, имя «Metro BT». Исходники: `src/metro_bt.c` (LV2, очередь, поток UDP),
  `src/metro_core.c/.h` (когда слать долю, без LV2). Сервис: `band/service.py`, запуск `scripts/metro_bt_service.py`,
  systemd `metro-bt.service` (ставит `scripts/install.sh`). UDP 127.0.0.1:47801: `alive`, `beat <мс> <акцент>`, `off`, `bye`.
- Pi: `python3 scripts/band_test.py buzz` подключается к браслету и вибрирует; `latency` меряет задержку.

## План этапов
1. Ключ из zip, протокол, офлайн-тесты. ✔
2. На Pi: подключение, авторизация, вибрация по команде. ✔ (find-watch вибрирует как надо, `beats 100` понравился)
3. LV2-плагин в цепочке шлёт доли, сервис вибрирует в такт. Контроллер «On» для футсвитча.
4. Акцент сильной доли, сдвиг задержки, автозапуск, переподключение.
