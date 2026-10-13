# Omipods

Per-earbud battery — plus an ANC/transparency switch — for Redmi/Xiaomi
earbuds, right in the [Omarchy](https://omarchy.org/) status bar.

Unlike the battery percentage BlueZ already exposes for most Bluetooth
headsets (a single combined number), this plugin talks the earbuds' own
Xiaomi control protocol directly over a classic-Bluetooth RFCOMM channel, so
it can show the **left and right bud** separately — the same kind of detail
AirPods-focused bar widgets show for Apple's earbuds.

## Features

- Left / right battery percentage and charging state
- Bar icon that reflects connection state
- Popup panel (click the bar icon) with per-component battery bars
- Listening-mode switch: Off / Transparency / Noise Cancellation

## How it works

Redmi earbuds don't expose per-component battery over the standard BLE
Battery Service — BlueZ only sees one combined percentage. The real detail
(and ANC control) lives behind a small proprietary protocol the earbuds speak
over a classic-Bluetooth RFCOMM channel once paired: a fixed packet framing,
a SAFER+-based challenge/response handshake, and a handful of opcodes for
device info, battery, and configuration.

That protocol was reverse-engineered by the [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge)
project for the **Redmi Buds 5 Pro** (AGPL-3.0). This plugin ports that same
framing/handshake/opcodes to Python — and it turns out the **Redmi Buds 6
Lite** speaks the identical protocol byte-for-byte (confirmed empirically
against real hardware), so the same client works unmodified for this
cheaper, more recent model too. It may well work for other Redmi/Xiaomi
earbuds that share the same firmware family — untested, but worth a try if
you have one.

`scripts/redmi_buds_battery.py` is a standalone script with no third-party
dependencies (plain `socket.AF_BLUETOOTH` RFCOMM, stdlib only):

```
redmi_buds_battery.py <mac-address> [--channel N] [--loop SECONDS]
redmi_buds_battery.py <mac-address> --set-anc {0,1,2}
```

The QML widget runs it in `--loop` mode and reads one JSON line per poll from
its stdout.

## Requirements

- Omarchy with the Quickshell-based shell
- The earbuds already paired and trusted via BlueZ (`bluetoothctl pair` /
  `bluetoothctl trust`) — this plugin does not handle pairing
- Python 3 (stdlib only, nothing to install)

## Installation

```bash
omarchy plugin add https://github.com/felipeoliboni/omipods.git --enable
```

(or clone it manually: `git clone https://github.com/felipeoliboni/omipods.git ~/.config/omarchy/plugins/omipods && omarchy-shell shell rescanPlugins`)

Then add the widget to your bar — either through Omarchy's bar settings UI,
or by adding it to `~/.config/omarchy/shell.json`:

```json
{
  "id": "omipods",
  "address": "AA:BB:CC:DD:EE:FF"
}
```

## Configuration

| Key            | Default | Description                                            |
|----------------|---------|----------------------------------------------------------|
| `address`      | `""`    | Bluetooth MAC address of your earbuds (required)         |
| `channel`      | `29`    | RFCOMM control channel                                    |
| `pollInterval` | `30`    | Seconds between battery reads                             |

**Finding your MAC address:**

```bash
bluetoothctl devices | grep -i redmi
```

**Finding your RFCOMM channel**, if `29` doesn't work (brute-force probe,
read-only — it only sends an auth challenge and reads whatever comes back):

```bash
for ch in $(seq 1 30); do
  python3 - "$ch" <<'EOF'
import socket, sys
s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
s.settimeout(1.5)
try:
    s.connect(("AA:BB:CC:DD:EE:FF", int(sys.argv[1])))
    print(f"channel {sys.argv[1]}: connected")
except OSError:
    pass
EOF
done
```

Channel `29` corresponds to the Xiaomi vendor control service (SIG-assigned
UUID `0000fd2d-...`) and has been consistent across the devices this was
tested on.

## Compatible devices

| Device                          | Status                                                                 |
|----------------------------------|-------------------------------------------------------------------------|
| Redmi Buds 6 Lite                | ✅ Confirmed — personally tested, battery and the ANC switch both work   |
| Redmi Buds 5 Pro                 | 🟡 Likely — this plugin's protocol is a direct port of Gadgetbridge's Redmi Buds 5 Pro support, but it hasn't been retested here against that model |
| Redmi Buds 6 / 6 Play / 6 Pro     | ❓ Untested — same product generation as the 6 Lite, may share firmware, unconfirmed |
| Other Redmi/Xiaomi earbuds        | ❓ Untested — Gadgetbridge supports several other models (3 Pro, 4 Active, 8 Active) through a *different* internal protocol, so compatibility here isn't guaranteed |

If you try it on a model that isn't listed as confirmed, please open an
issue with the result (worked / didn't connect / connected but no battery /
etc.) — happy to expand this table.

## Known limitations

- The earbuds don't acknowledge the ANC/transparency command, so the popup
  shows "last mode sent," not a confirmed device readback.
- The wire byte that means "Transparency" vs. "Noise Cancellation" isn't
  guaranteed to match the official Xiaomi app's own convention on every
  unit (it was swapped on the one this was tested against — see the
  comments in `RedmiBuds.qml` if you need to flip it back for yours).
- No wearing/ear-detection state (the protocol does push it, just not wired
  up here yet).
- The case has its own battery level over this protocol too, but it only
  reports a real number while a bud is actually in the case, so it's left
  out of the popup for now rather than showing "n/a" most of the time.

## Credits

- Protocol framing, handshake, and opcodes ported from
  [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge)'s Redmi
  Buds 5 Pro support (`RedmiBuds5ProProtocol.java`, `Authentication.java`),
  AGPL-3.0, by Jonathan Gobbo and contributors.
- UI modeled after [thisisgm/omarchy-pods](https://github.com/thisisgm/omarchy-pods).

## License

AGPL-3.0 — see [LICENSE](LICENSE). This is a derivative work of Gadgetbridge
(AGPL-3.0), so the same license applies to the protocol client; the Omarchy
plugin glue (manifest/QML) is released under the same terms for simplicity.
