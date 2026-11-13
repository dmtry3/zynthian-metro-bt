# zynthian-metro-bt

English · [Русский](README.md)

A Zynthian metronome on your wrist: every beat arrives as a vibration on a Xiaomi Smart Band 10.
Handy on stage or with in-ear monitors: you feel the tempo instead of hearing a click.

[![Video on YouTube](https://img.youtube.com/vi/12LIlUnqwzE/hqdefault.jpg)](https://youtu.be/12LIlUnqwzE)

Tested on Zynthian V5 (Raspberry Pi 5, Debian bookworm) with a Xiaomi Smart Band 10.
Zynthian itself is not modified: you install an LV2 plugin and a separate service.

```
[Zynthian chain]                          [service on the Pi]
LV2 MIDI tool "Metro BT"  --UDP localhost-->  metro-bt (Python, systemd)  --Bluetooth SPP-->  Mi Band 10
```

- The plugin follows the Zynthian transport (tempo, bar position) and passes MIDI through untouched.
- The service talks to the band over Bluetooth Classic (SPP), the same way [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge) does,
  and sends each beat slightly early to compensate for Bluetooth latency.

## Requirements
- Zynthian V5 (or any Linux with an LV2 host and BlueZ), `gcc`, `lv2-dev`, `python3-cryptography`.
- A Xiaomi Smart Band 10 paired with Mi Fitness (you need its auth key, see below).
- Other Xiaomi bands using the SPP V2 protocol may work, but are untested.

## Getting the auth key
The band only talks to a client that knows its key. The key is in the Mi Fitness logs:
export the logs from the Mi Fitness app (a zip containing `XiaomiFit.main.log`) and run
```bash
python3 scripts/extract_key.py /path/to/logs.zip     # writes config/band.json
```
The key (`encryptKey`) is a secret: never publish `config/band.json` or the log zip.
If you unpair the band from Mi Fitness or reset it, the key changes and you need fresh logs.

## Install on the Pi
```bash
git clone https://github.com/dmtry3/zynthian-metro-bt.git
cd zynthian-metro-bt
# put config/band.json here (extract_key.py, or copy it, or fill in config/band.example.json)
python3 scripts/band_test.py scan        # find the band, store its MAC
python3 scripts/band_test.py buzz -v     # connect, authenticate, one vibration
python3 scripts/band_test.py beats 100   # 16 beats at 100 BPM

sudo ./scripts/install.sh                # builds the plugin, installs the metro-bt systemd service
sudo systemctl restart zynthian
```

## Usage
Add the MIDI tool **Metro BT** to any MIDI chain in Zynthian. Controls:
- **On**: metronome on/off. Map it to a footswitch button with Zynthian's MIDI learn.
- **Accent**: the downbeat vibrates three times longer.
- **Pulse ms**: vibration length.
- **Advance ms**: how early to send each beat, to compensate Bluetooth latency.

Beats are sent only while the Zynthian transport is running; stopping the transport stops the vibration immediately.
While the plugin is in a chain the service keeps the band connected; it disconnects 10 s after the plugin is removed.

Log: `journalctl -u metro-bt -f`. Uninstall: `sudo ./scripts/uninstall.sh`.

## Known limitations
- While the band is connected to the Pi, the phone can't connect to it.
- If the band is paired with the phone over Bluetooth, the Pi gets `Connection refused`, even with the phone's Bluetooth off.
  Remove the band from the phone's Bluetooth device list (the key stays the same).
- `band_test.py` can't connect while the service holds the band: `sudo systemctl stop metro-bt` first.

## Tests (no Bluetooth needed)
```bash
./scripts/test.sh    # protocol and service against a fake band, metronome core and the .so in a mock host
```

## License
AGPL-3.0. The band protocol is ported from [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge), thanks to its authors.

Not affiliated with Xiaomi or Zynthian. Use at your own risk.
