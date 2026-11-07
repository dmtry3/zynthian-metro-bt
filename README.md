# zynthian-metro-bt

Метроном Zynthian на браслете Xiaomi Smart Band 10: каждая доля приходит вибрацией.

Статус: этап 2. Проверяем связь с браслетом на Pi. Плагина в цепочке пока нет.

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

## Тесты протокола (без Bluetooth)
```bash
python3 -m unittest discover -s tests
```

## Лицензия
AGPL-3.0. Протокол браслета портирован из [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge).
