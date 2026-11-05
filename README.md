# ambilight-hue-sync

Stream the colours of a Philips TV's own Ambilight to Philips Hue lights in real time, using the Hue Entertainment API. No Hue Play HDMI Sync Box, no HDMI capture card, no camera pointed at the screen.

It runs as a small Python service on any always-on Linux box (tested on a Raspberry Pi 5) and has been driving five Hue lights from a living room TV every evening.

## Why

Philips sells two ways to get Hue lights to follow the picture: the Ambilight+Hue feature, which only some TV models have, and the HDMI Sync Box, which sits between your sources and the TV. My TV (a 65PUS8209 running Titan OS) has a three sided Ambilight but no Ambilight+Hue, and with an Apple TV and a PS5 plugged in, a Sync Box would mean extra cost, an extra HDMI hop and HDR/VRR passthrough worries.

The TV already does the hard part. Its Ambilight engine analyses whatever is on screen, from any HDMI input or app, and exposes the result as per pixel edge colours over the local JointSpace API. This project reads that data and forwards it to Hue.

## How it works

```mermaid
flowchart LR
    S[Apple TV / PS5 / apps] -->|HDMI| TV[Philips TV<br>Ambilight engine]
    TV -->|HTTPS + digest auth<br>/6/ambilight/processed<br>every 0.15 s| R[TV reader thread]
    R -->|dominant hue per light<br>CIE xy + brightness| T[(targets)]
    T --> L[stream loop 25 Hz<br>exponential smoothing]
    L -->|HueStream v2 packets<br>DTLS 1.2 PSK, UDP 2100| B[Hue Bridge]
    B --> H[Hue lights in an<br>entertainment area]
```

1. A reader thread polls `https://<tv>:1926/6/ambilight/processed` over one long lived HTTPS session. The answer lists RGB values for every Ambilight zone on the left, top and right edges.
2. Each configured light owns a slice of an edge (for example "right edge, lower half") or the whole frame. For that slice the service picks the dominant hue, converts it to CIE xy and computes a brightness.
3. The stream loop runs at 25 Hz, eases every light toward its latest target and sends one UDP packet containing all lights to the bridge.
4. When the TV stops answering it ends the stream and puts every light back exactly as it was before streaming started.

## Engineering notes

These are the parts that took real debugging, and the reason the code looks the way it does.

### Reuse one TV session, always

The first version opened a new HTTPS connection for each request. On this TV that is a TLS handshake plus an HTTP digest challenge every 150 ms, and after a while the JointSpace server gave up: every endpoint returned 404 or 403, and only a cold reboot (unplugging the TV) brought it back. Switching to a single `requests.Session` with keep alive fixed it completely. With a reused session the TV answers in about 70 to 90 ms and has run for days without trouble. After any error the reader also drops to a slower 0.4 s interval for a minute instead of hammering a struggling API.

### Sample slowly, stream fast

The TV's processed data does not update faster than about every 100 ms; polling quicker only returns duplicates. Hue lights, on the other hand, look much smoother when driven at 25 Hz. So the two run separately: the reader updates targets at roughly 7 Hz, and the stream loop interpolates toward them at 25 Hz. The result looks fluid even though the input is coarse.

### Dominant hue, not the average

Averaging the pixels of an edge that shows an orange sunset over a blue sea gives purple, a colour that is not on screen. Instead each pixel votes into a 12 bin hue histogram, weighted by value times saturation squared so vivid pixels count more than washed out ones. The histogram is smoothed with its neighbours, the strongest bin wins, and only pixels within 45 degrees of it are averaged. Nearly grey scenes fall back to a plain average, and in dim scenes the colour is gradually pulled toward white because hue is mostly noise there.

### Smoothing with separate rise and fall

Each light uses exponential smoothing with three time constants: one for getting brighter, a slower one for getting darker, and one for colour. Flashes feel immediate, fades feel calm, and a long light strip can be given slower constants than a small lamp. Two small rules avoid ugly artefacts: below a darkness threshold the light really switches off, and a light coming back from black jumps straight to the new colour instead of fading in through white.

### Snapshot and restore

Entertainment streaming takes over the lights, and when it ends they would otherwise stay on the last streamed colour. Before each stream starts the service saves on/off, brightness and colour temperature or xy of every light to a small JSON file, and writes them back after the TV turns off or the service stops. If a previous run died mid stream (lights still report `mode: streaming`), the older snapshot is kept, because the current state is the stream's colour and not yours.

### DTLS through openssl

The Hue Entertainment API needs DTLS 1.2 with a pre shared key, which the Python standard library does not provide. Rather than pulling in a native DTLS binding, the service starts `openssl s_client -dtls1_2 -psk ...` as a subprocess and writes packets to its stdin. It is a few lines, uses a TLS stack that is already on every Linux system, and a dropped connection simply shows up as a broken pipe that triggers a reconnect.

### TV off detection

Three failed reads in a row mean the TV is off or in standby. The stream is stopped and the lights are restored. When the TV answers again, a fresh snapshot is taken and streaming restarts on its own, so the service can run permanently.

## Hardware tested

| Part | Model |
| --- | --- |
| TV | Philips 65PUS8209/12, Titan OS, three sided Ambilight (no Ambilight+Hue on this model) |
| Bridge | Hue Bridge v2 (BSB002) |
| Lights | Hue Lightstrip Plus, a Hue Go style lamp, two Hue Play bars, a colour bulb, all in one entertainment area (each reports one segment) |
| Sources | Apple TV and PS5 over HDMI, plus the TV's built in apps |
| Host | Raspberry Pi 5, Debian, Python 3.13, OpenSSL 3 |

Other Philips TVs that expose JointSpace API v6 on port 1926 should work, since the processed Ambilight endpoint has been stable across many model years. Multi segment gradient lights are driven as one colour per light.

## Quick start

Requirements: Python 3.11 or newer, `openssl` on the PATH, the TV and the bridge on the same network.

```bash
git clone https://github.com/sahindemirbas/ambilight-hue-sync.git
cd ambilight-hue-sync
python3 -m venv ~/.local/share/ambilight-hue-sync/venv
~/.local/share/ambilight-hue-sync/venv/bin/pip install .
export PATH="$HOME/.local/share/ambilight-hue-sync/venv/bin:$PATH"
```

1. Create an entertainment area in the Hue app and add the lights you want to follow the TV.

2. Get Hue Entertainment credentials. Run this, then press the link button on the bridge:

   ```bash
   ambilight-hue-sync register --host 192.168.1.10
   ```

   It writes `~/.config/ambilight-hue-sync/hue.json` (mode 0600) with the application key, client key and application id.

3. Get TV credentials. Android and Titan OS Philips TVs protect the API with a digest user and password created by a one time PIN pairing. The easiest way is the pairing command from [ha-philipsjs](https://github.com/danielperna84/ha-philipsjs):

   ```bash
   pip install ha-philipsjs
   python -m haphilipsjs -i 192.168.1.20 -a 6 pair
   ```

   Enter the PIN shown on the TV and keep the printed username and password. If you already use the Philips TV integration in Home Assistant, it holds the same pair.

4. Configure:

   ```bash
   mkdir -p ~/.config/ambilight-hue-sync
   cp config.example.toml ~/.config/ambilight-hue-sync/config.toml
   chmod 600 ~/.config/ambilight-hue-sync/config.toml
   ambilight-hue-sync check
   ambilight-hue-sync run
   ```

## Configuration

Everything lives in `config.toml`; see [config.example.toml](config.example.toml) for all keys with comments. The important part is the light mapping:

```toml
[[light]]
name = "Play bar right low"   # device name as shown in the Hue app
side = "right"                # left, right, top, bottom or all
start = 0.0                   # slice of the edge, 0.0 = bottom
end = 0.5
scale = 1.0                   # brightness multiplier
smoothing = [0.12, 0.25, 0.18] # optional: rise, fall, colour in seconds
```

Place each light's slice where the light physically sits relative to the screen. A light behind the sofa usually works best with `side = "all"` and a lower `scale`.

Secrets do not have to be in the file. These environment variables override it:

| Variable | Meaning |
| --- | --- |
| `AMBILIGHT_CONFIG` | path to config.toml |
| `AMBILIGHT_TV_HOST`, `AMBILIGHT_TV_USERNAME`, `AMBILIGHT_TV_PASSWORD` | TV address and digest credentials |
| `AMBILIGHT_HUE_HOST`, `AMBILIGHT_HUE_USERNAME`, `AMBILIGHT_HUE_CLIENTKEY`, `AMBILIGHT_HUE_APPID` | bridge address and Entertainment credentials |

## Run as a systemd user service

```bash
mkdir -p ~/.config/systemd/user
cp systemd/ambilight-hue-sync.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ambilight-hue-sync
sudo loginctl enable-linger "$USER"
journalctl --user -u ambilight-hue-sync -f
```

The unit restarts on failure and gives the service 20 seconds on stop so it can end the stream and restore the lights. Secrets can go in `~/.config/ambilight-hue-sync/env` as `AMBILIGHT_*=value` lines, which the unit loads if present.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `tv error: HTTPError 401` | Wrong TV username or password; pair again. |
| TV API returns 404 or 403 for everything, even from curl | The JointSpace server is stuck, usually after many fresh connections. Unplug the TV for a minute. This service reuses one connection so it should not cause it again. |
| `tv error: ConnectTimeout` while the TV is on | The TV turns its network off in some standby modes; enable the "Wake on WiFi" style option in the TV network settings, and give the TV a fixed IP. |
| `entertainment area ... not found` | The name in `entertainment_area` must match the Hue app exactly. |
| `lights not in area` | Each `[[light]] name` must be the device name of a light inside that area. |
| `DTLS failed` | Check that `openssl` supports `PSK-AES128-GCM-SHA256`, that UDP 2100 to the bridge is not blocked, and that `hue.json` came from `register` with a client key. |
| Lights stay on the last colour after a crash | Start and stop the service once; the saved snapshot is restored on the next clean stop. |
| Colours lag or flicker | Raise the smoothing constants for that light, or lower `interval` to 0.1. Going below 0.1 only returns duplicate frames. |

## Limitations

- Works only with Philips TVs that expose the JointSpace v6 processed Ambilight endpoint. The Ambilight must be on (any mode) for the data to follow the picture.
- The data is the TV's processed Ambilight output, so it inherits the TV's own latency and zone resolution. In practice the lights trail the Ambilight LEDs by roughly one TV sample, about 100 to 150 ms.
- One colour per light. Gradient strips and Play bars with several segments get a single colour each.
- The bridge and TV certificates are self signed, so TLS verification is disabled for these two local hosts. Run it on a trusted home network only.
- The DTLS stream depends on the system `openssl` binary, and the client key is passed to it on the command line, so other local users on the host can see it in the process list. Use a single user machine.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

The tests cover the pure logic without any hardware: edge slicing, dominant hue selection, RGB to xy, the dim scene white pull, smoothing, the HueStream packet layout, snapshot and restore body building, TV off detection and config parsing.

```
src/ambilight_hue_sync/
  color.py      edge slicing, dominant hue, xy conversion
  smoothing.py  per light exponential smoothing
  protocol.py   HueStream v2 packet
  state.py      channel mapping, snapshot/restore, TV health
  config.py     TOML and environment loading
  sync.py       TV reader, bridge calls, DTLS stream (the only networked part)
  register.py   bridge link button registration
```

## Credits

- The JointSpace API endpoints and pairing flow are documented by the community, in particular [pylips](https://github.com/eslavnov/pylips) and [ha-philipsjs](https://github.com/danielperna84/ha-philipsjs). No code was copied from either; ha-philipsjs is only recommended as a tool for pairing.
- [Hue Entertainment API](https://developers.meethue.com/develop/hue-entertainment/) and CLIP v2 documentation from Signify (free developer account required) describe the stream format and DTLS setup.
- The RGB to xy matrix is the wide gamut conversion published in the Hue developer documentation.

Philips, Ambilight and Hue are trademarks of their owners. This project is not affiliated with or endorsed by TP Vision or Signify.

## License

MIT, see [LICENSE](LICENSE). A Turkish version of this README is in [README.tr.md](README.tr.md).
