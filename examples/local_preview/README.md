# Local video/audio/call experiment

Use Python 3.12 or later and install FFmpeg. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -r examples/local_preview/requirements.txt
cp examples/local_preview/.env.example .env
chmod 600 .env
```

Fill `.env` with your monitor IP, numeric View Door device password and its
verified SHA-256 TLS certificate fingerprint. Never commit this file. Obtain
and check the fingerprint during HA setup or your own local setup; the preview
requires a pin and checks it before transmitting the device password.
Set `FFMPEG_BINARY` if FFmpeg is not on PATH.

```sh
.venv/bin/python examples/local_preview/server.py
```

Open the private URL saved in `.local/preview.json`. The server binds only to
127.0.0.1:18766. It does not expose the monitor to your LAN or the internet.
Connect camera first, then optionally enable experimental audio. The preview
releases its connections after two minutes, on Disconnect, when hidden, or on
normal server shutdown. Disconnect before opening View Door on a phone.
No audio/video recordings are saved. Microphone access requires holding Talk.

**Calls:** Preview a call is a silent browser-only simulation and sends no device
command. The passive observer checks command 23 during preview; it is NOT proven
to capture initial rings. Open camera & audio opens the experimental media
session, not a verified device answer acknowledgment. Dismiss is local only.
Actual ringing, answer, decline and end-of-call signaling still need capture.
There are no ring or unlock commands in this example.

**Audio:** The 10-second check counts signal versus digital silence. Signal can
be clicks/noise and does not prove useful outdoor sound. The playback test makes
a quiet sound only on the computer. No reliable acoustic or two-way result is
claimed. Audio packet timing includes a control heartbeat to avoid idle expiry.

## Certificate fingerprint

The preview refuses to start with a missing or malformed fingerprint. If HA has
already been configured, its saved `certificate_fingerprint` is the pin used by
the integration. Otherwise, read the certificate from your own monitor before
sending credentials. For example, with OpenSSL installed, replace the example
address with the monitor's actual address:

```sh
MONITOR_IP=192.0.2.10
openssl s_client -connect "$MONITOR_IP:443" -servername "$MONITOR_IP" </dev/null 2>/dev/null | openssl x509 -noout -fingerprint -sha256
```

This reads a certificate without sending the device password. Confirm that the
address and certificate belong to your monitor; the command alone does not
establish that trust. Copy only the fingerprint value into
`CERTIFICATE_FINGERPRINT`, with or without colon separators. Never silently
replace an existing pin after an unexpected certificate change.
