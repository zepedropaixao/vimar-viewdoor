"""Local-only View Door transport; Home Assistant independent for testing."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import http.client
import ipaddress
from pathlib import Path
import ssl
import threading
import time
import xml.etree.ElementTree as ET

from quii_helper import Camera
from quii_helper.camera.connection.session import CameraConnector
from quii_helper.protocols.quii.live_packets import build_live_play_packet
from quii_helper.protocols.tcp.live.session import LanTcpSession


class AuthenticationError(Exception):
    """The monitor rejected the device password."""


class CertificateChangedError(Exception):
    """The monitor no longer presents its configured certificate."""


@dataclass(frozen=True)
class DeviceInfo:
    identifier: str
    model: str
    firmware: str
    fingerprint: str
    stream_key: str = field(repr=False)


@dataclass
class ViewDoorPacketBuilder:
    """Match View Door's native channel/stream fields, without global patches.

    Packet layout derived from View Door Android V2.2.11's CQUIIStreamLive.
    QUII packet/encryption implementation is provided by quii-helper (MIT).
    """
    username: str
    password: str = field(repr=False)
    path: str
    key: str = field(repr=False)
    channel: int
    stream: int

    def build_live_open_packet(self, *, crypto_mode: int, play_param: int = 1,
                               stream_flag: int = 0,
                               timestamp_ms: int | None = None) -> bytes:
        return build_live_play_packet(
            self.username, self.password, self.path,
            timestamp_ms=timestamp_ms,
            ext_len_low=self.channel & 255,
            ext_len_high=self.channel >> 8,
            stream_flag=self.stream - 1,
            play_param=play_param, crypto_mode=crypto_mode, sha_mode=1,
            key=self.key.encode(), encrypt=crypto_mode != 0,
        )[2]


class ViewDoorConnector(CameraConnector):
    """Replace only this connection's playback packet builder."""
    call_observer = None

    def create_lan_session(self) -> LanTcpSession:
        session = super().create_lan_session()
        client = session._client  # Internal API: dependency pinned to 0.2.0.
        client.live_open_builder = ViewDoorPacketBuilder(
            username=client.username, password=client.password, path=client.path,
            key=client.key, channel=self.config.channel, stream=self.config.stream,
        )
        if self.call_observer is not None:
            from .calls import observe_session
            observe_session(session, self.call_observer)
        return session


class ViewDoorBackend:
    """Pinned TLS metadata and an on-demand loopback RTSP bridge."""
    def __init__(self, host: str, password: str, *, fingerprint: str = "",
                 channel: int = 1, stream: int = 2, data_dir: Path | None = None):
        self.host = str(ipaddress.ip_address(host))
        if not password or not password.isdigit():
            raise ValueError("Enter the numeric View Door device password")
        if not 1 <= channel <= 255 or stream not in (1, 2):
            raise ValueError("Invalid camera channel or stream")
        self._password = password
        self.fingerprint = fingerprint.lower().replace(":", "")
        self.channel, self.stream = channel, stream
        self.data_dir = data_dir or Path(".")
        self.info: DeviceInfo | None = None
        self._stream = None
        self._last_request = 0.0
        self._lock = threading.RLock()
        self.call_observer = None

    def read_status(self) -> ET.Element:
        """Read metadata only. Pin the certificate before sending credentials."""
        # The device uses a private vendor CA. Subsequent connections are
        # authenticated by the exact fingerprint saved during user setup.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(self.host, 443, timeout=5, context=context)
        try:
            conn.connect()
            fingerprint = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest()
            if self.fingerprint and fingerprint != self.fingerprint:
                raise CertificateChangedError("The device certificate changed")
            self.fingerprint = fingerprint
            envelope = ET.Element("envelope")
            body = ET.SubElement(envelope, "body")
            ET.SubElement(body, "command").text = "get.device.status"
            ET.SubElement(body, "content")
            header = ET.SubElement(envelope, "header")
            for tag, value in {
                "security": "username", "username": "adminapp2",
                "password": hashlib.sha256(self._password.encode()).hexdigest(),
                "passwordencode": "1",
            }.items():
                ET.SubElement(header, tag).text = value
            conn.request("POST", "/tdkcgi", body=ET.tostring(envelope),
                         headers={"Content-Type": "application/xml"})
            response = conn.getresponse()
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Device response too large")
            if response.status in (401, 403):
                raise AuthenticationError("Device password rejected")
            if response.status != 200:
                raise OSError("Device returned an HTTP error")
            root = ET.fromstring(raw)
            error = root.findtext("./body/error", "missing")
            if error in ("401", "-3", "-4", "-45"):
                raise AuthenticationError("Device password rejected")
            if error != "0":
                raise OSError("Device rejected the status request")
            return root
        finally:
            conn.close()

    def initialize(self) -> DeviceInfo:
        with self._lock:
            root = self.read_status()
            prefix = "./body/content/"
            identifier = root.findtext(prefix + "info/mac", "").replace(":", "").lower()
            key = root.findtext(prefix + "key", "")
            if not identifier or len(key.encode()) != 32:
                raise ValueError("This monitor did not supply the expected metadata/key")
            self.info = DeviceInfo(
                identifier=identifier,
                model=root.findtext(prefix + "info/model", "Vimar View Door"),
                firmware=root.findtext(prefix + "info/version", ""),
                fingerprint=self.fingerprint, stream_key=key,
            )
            return self.info

    def create_camera(self) -> Camera:
        if self.info is None:
            self.initialize()
        camera = Camera(
            connection_mode="lan", device_host=self.host,
            auth_code=self._password, stream_key=self.info.stream_key,
            channel=self.channel, stream=self.stream, data_dir=self.data_dir,
        )
        camera.connector = ViewDoorConnector(camera.config)
        camera.connector.call_observer = self.call_observer
        return camera

    def stream_url(self) -> str:
        """Start only on request; never expose the unauthenticated bridge on LAN."""
        with self._lock:
            self._last_request = time.monotonic()
            if self._stream is not None:
                try:
                    self._stream.wait(timeout=0)
                except Exception:
                    self._stream.close()
                    self._stream = None
            if self._stream is None:
                self.initialize()  # Refresh the key and recheck the pinned certificate.
                self._stream = self.create_camera().serve_rtsp(host="127.0.0.1", port=0)
            return self._stream.url

    def close_if_idle(self) -> None:
        with self._lock:
            if self._stream is not None and self._stream.server.client_count == 0:
                if time.monotonic() - self._last_request > 90:
                    self.close()

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
