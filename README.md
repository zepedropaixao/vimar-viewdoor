# Vimar View Door for Home Assistant

An experimental local integration for Vimar video door phones that use the
**View Door** mobile app. It provides a Home Assistant camera and a separate
browser-based test app for investigating audio and call notifications.

Maintained by [@zepedropaixao](https://github.com/zepedropaixao).
This is an independent community project, with no affiliation to Vimar or
Qualvision. It is distinct from integrations for Vimar VIEW, By-me or SIP devices.

> **Early beta:** video has been validated on one monitor. Outdoor audio,
> two-way speech and real incoming-call handling are not confirmed. Do not rely
> on this release to alert you when someone is at the door.

## What works, and what is experimental?

| Feature | Home Assistant integration | Standalone test app |
| --- | --- | --- |
| Local device authentication | Tested, with device certificate pinning | Tested, requires a configured certificate pin |
| Live video | Camera stream source and snapshots tested locally; dashboard/HLS playback still needs validation | Live video tested |
| Outdoor audio | Not implemented in the HA camera | Experimental; incoming packets do not prove useful outdoor sound |
| Speak to the outdoor panel | Not implemented | Experimental hold-to-talk; speech at the panel is not verified |
| Incoming doorbell calls | Unverified `call_candidate` event during an active camera preview | Unverified candidate display during preview |
| Simulate a call | Not implemented | Silent local UI simulation; the physical bell is not activated |
| Answer, decline or hang up a real device call | Not implemented | Not implemented; opening audio is not a verified answer acknowledgment |
| Door/gate unlocking | Not implemented | Not implemented |

Neither an Android emulator nor the vendor cloud is required for this project's
local camera connection. The standalone test app is optional; it is not part of
the Home Assistant frontend.

## Tested hardware

| Item | Tested configuration |
| --- | --- |
| Kit | Vimar K42955 |
| Indoor monitor | IDS9457AW |
| Firmware | `V100.R001.A344.00.G0078.B003` |
| Camera selection | Channel 1, stream 2 |
| Home Assistant test environment | Core 2026.10.4, Python 3.14.2 |
| Standalone test environment | macOS |

Testing covers local authentication, H.264 reception, JPEG/video decoding and
the HA camera entity's snapshot method. Installation in a continuously running
HA system, dashboard playback, other models and other firmware are not yet
validated. Similar-looking Vimar devices may use different protocols.

## Requirements

- Home Assistant 2026.10 or later, with FFmpeg available to its FFmpeg integration.
- A compatible indoor monitor reachable from the HA host on HTTPS **443** and
  TCP **34567**. A fixed address or DHCP reservation is useful.
- The numeric **View Door device password**. This is not the Wi-Fi password,
  MyVimar account password or a door-unlock code.
- HACS for the custom-repository installation method, or access to HA's
  `custom_components` directory for manual installation.

The integration installs `quii-helper==0.2.0` and uses HA's `ffmpeg` and `stream`
integrations. Internet access is needed to download dependencies during setup;
local camera operation does not require a cloud account.

## Install with HACS

This project is intended for installation as a **custom repository**. It is not
listed in HACS's default catalogue. HACS installation and automated HACS
validation still need verification on this beta.

1. Open HACS and choose **Custom repositories** from its menu.
2. Add `https://github.com/zepedropaixao/vimar-viewdoor` with category **Integration**.
3. Find **Vimar View Door**, download it, and restart Home Assistant.
4. Continue with the configuration steps below.

### Manual installation

1. Download or clone this repository.
2. Copy `custom_components/vimar_viewdoor` into the `custom_components` directory
   inside your Home Assistant configuration directory. Create it if needed.
3. Check that the final path is
   `<HA configuration>/custom_components/vimar_viewdoor/manifest.json`.
4. Restart Home Assistant, then configure the integration.

## Configure Home Assistant

1. Open **Settings → Devices & services → Add integration**.
2. Search for **Vimar View Door**.
3. Enter a display name, the indoor monitor's local IP address and its numeric
   View Door device password.
4. Add the camera entity to a dashboard using your preferred camera card.

The current setup uses channel 1 and stream 2. Channel selection is not exposed
in the setup form yet. Initial playback can take several seconds.

On first setup, the integration saves the SHA-256 fingerprint of the certificate
presented by the IP address you supplied. Confirm that address belongs to your
monitor. Later HTTPS connections must present the same certificate before the
integration sends credentials. A changed certificate stops authentication;
verify the device before removing and re-adding the integration to trust a new
certificate.

The internal RTSP relay binds only to `127.0.0.1`. It does not need a published
RTSP port. In a container installation, that loopback address refers to the HA
container itself. The relay starts on demand and closes after it has no viewers
and has been idle for approximately 90 seconds.

## Experimental call events

Home Assistant adds a **Call candidate (experimental)** event entity. Its event
type is `call_candidate`; event data includes `channel` and `verified: false`.
The exact entity ID is assigned by HA.

This observer recognizes a transparent notification that the Android app routes
to `onOtherDoorBellCall`. That name may refer to an additional call rather than
the initial doorbell press. **No physical ring has been captured to confirm it.**
Static capability fields such as `calling` are not interpreted as a live ring.

The observer:

- Reuses an existing camera-preview connection and opens no extra connection.
- Watches only while that preview is running; it is not an always-on subscription.
- Does not send a ring, answer, decline, hang-up or unlock command.
- Does not expose device-supplied household names in event data.

An entity with no events is not evidence that nobody rang. Reliable mobile
notifications and call automations should wait until an actual ring source and
background delivery have been verified.

## Standalone video, audio and call test app

The optional app in [`examples/local_preview`](examples/local_preview) brings
live video, listening, hold-to-talk and call experiments into one local page.
It requires Python 3.12 or later and a local FFmpeg installation.

From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -r examples/local_preview/requirements.txt
cp examples/local_preview/.env.example .env
chmod 600 .env
```

Edit `.env` with your device address, numeric password and verified certificate
fingerprint. Then run:

```sh
.venv/bin/python examples/local_preview/server.py
```

Open the private URL saved in `.local/preview.json`. Keep its access token
private. The server listens only on `127.0.0.1:18766` and is intended for use on
the same computer. Do not expose it directly to the internet.

See the [example app setup guide](examples/local_preview/README.md) for obtaining
a certificate fingerprint and the environment-file fields.

### Controls

| Control | What it does |
| --- | --- |
| Connect camera | Opens the local video preview |
| Enable outdoor audio | Opens the experimental talk/audio session |
| Hold to talk outside | Requests microphone access and sends voice while held |
| Check received audio | Counts incoming signal versus digital silence for 10 seconds |
| Test this Mac's playback | Plays a soft tone on the computer only |
| Preview a call | Displays a silent, simulated call locally; sends no device command |
| Open camera & audio | Opens the preview/audio experiment; does not establish that a real call was answered |
| Dismiss locally | Clears the call display; does not decline a call on the device |
| Disconnect | Closes this app's video/audio connections |

A nonzero audio level can be a click or noise. Digital silence can mean either
a quiet scene or an inactive outdoor microphone. Neither result alone proves
the audio path works. A control heartbeat is sent during the audio experiment
to prevent the talk session expiring while media is being sent.

No audio or video recordings are saved by the test app. The app releases its
connections after two minutes, on Disconnect, when its page is hidden, or on
normal server shutdown. The monitor may allow only one active conversation;
disconnect here before opening View Door on a phone.

## Troubleshooting

**The monitor cannot be reached**

Confirm the indoor monitor's address and that the HA host can reach ports 443
and 34567. Guest Wi-Fi, VLAN rules or wireless client isolation may prevent this.

**Authentication fails**

Check the numeric device password in View Door. Do not use account or Wi-Fi
credentials. The integration does not guess passwords.

**Video works, but audio is silent**

This is an unresolved limitation. Test the computer's local playback separately,
then check received audio. A successful audio handshake is not proof that the
outdoor microphone or speaker is active.

**View Door on the phone cannot connect**

Disconnect the standalone preview and close other viewers. HA's idle RTSP relay
may take about 90 seconds to close. Avoid testing with the phone, HA and the
standalone app all connected at once.

**No incoming-call event appears**

Call delivery is unverified, and the experimental observer only sees messages
on an active preview. A future daytime test must capture a real ring and check
whether a separate subscription or vendor-cloud path is needed.

**The certificate changed**

Verify the monitor and address before trusting a replacement certificate. The
integration deliberately stops rather than silently accepting the change.

## Development and validation

```sh
python3 -m venv .venv
.venv/bin/pip install pytest quii-helper==0.2.0
.venv/bin/python -m pytest -q tests
```

The local suite currently has **19 passing tests** covering channel/stream packet
fields, credential rejection, certificate-change handling, dependency isolation,
malformed call data and observer-failure isolation. Synthetic event tests do not
validate real hardware call delivery. CI is configured for Python 3.12 and 3.14;
a CI configuration is not a claim that hosted checks have already passed.

The transport adapter uses a private interface in `quii-helper`, so that
requirement is pinned. No global patches to the installed library are made.

### Remaining work

- Capture a physical button press and identify the initial call event.
- Verify call delivery while no preview is running.
- Identify and validate answer, decline and end-of-call signaling.
- Verify outdoor microphone audio and speech at the outdoor panel.
- Add suitable HA audio/call controls after the underlying behavior is verified.
- Validate installation and dashboard streaming in a running Home Assistant setup.
- Complete HACS validation and collect compatibility reports for other monitors.

When reporting a problem, include the monitor model, firmware, HA version and a
redacted description of the result. Do not post device passwords, UIDs, stream
keys, browser tokens, private network captures or unredacted diagnostic logs.

## License and dependencies

[MIT](LICENSE). Built on [quii-helper](https://github.com/xaer981/quii-helper),
also MIT licensed. Required third-party notices are retained in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). No vendor application binaries,
credentials, media or artwork are distributed with this project.
