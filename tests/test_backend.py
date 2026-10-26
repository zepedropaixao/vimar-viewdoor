"""Regressions for the device-specific playback and TLS boundary."""
import hashlib
import importlib.util
from pathlib import Path
import sys
from unittest.mock import MagicMock

import pytest
from quii_helper.protocols.quii.crypto import aes_cbc_crypt

path = Path(__file__).parents[1] / 'custom_components/vimar_viewdoor/backend.py'
spec = importlib.util.spec_from_file_location('viewdoor_backend_test', path)
b = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = b
spec.loader.exec_module(b)

@pytest.mark.parametrize('channel,stream,expected', [(1,1,(1,0,0)),(1,2,(1,0,1)),(2,2,(2,0,1)),(255,1,(255,0,0))])
def test_packet_matches_android_channel_quality_fields(channel, stream, expected):
    key = 'a' * 32
    builder = b.ViewDoorPacketBuilder('adminapp2', 'credential', '/mode=real', key, channel, stream)
    packet = builder.build_live_open_packet(crypto_mode=2, timestamp_ms=100)
    header = aes_cbc_crypt(packet[:32], key, crypto_mode=2, decrypt=True)
    assert (header[13], header[14], header[16]) == expected
    assert header[0] == 1
    assert header[15] == 1


def test_changed_certificate_blocks_password_transmission(monkeypatch):
    backend = b.ViewDoorBackend('192.0.2.10', '1234', fingerprint='00' * 32)
    conn = MagicMock()
    conn.sock.getpeercert.return_value = b'new certificate'
    monkeypatch.setattr(b.http.client, 'HTTPSConnection', lambda *a, **k: conn)
    with pytest.raises(b.CertificateChangedError):
        backend.read_status()
    conn.request.assert_not_called()
    conn.close.assert_called_once()


def test_auth_failure_is_not_success_or_empty_metadata(monkeypatch):
    backend = b.ViewDoorBackend('192.0.2.10', '1234')
    conn = MagicMock()
    conn.sock.getpeercert.return_value = b'certificate'
    response = conn.getresponse.return_value
    response.status = 200
    response.read.return_value = b'<envelope><body><error>401</error><content/></body></envelope>'
    monkeypatch.setattr(b.http.client, 'HTTPSConnection', lambda *a, **k: conn)
    with pytest.raises(b.AuthenticationError):
        backend.initialize()
    assert backend.info is None


def test_secrets_are_hidden_from_device_info():
    info = b.DeviceInfo('id', 'model', 'fw', 'fingerprint', 'sensitive-key')
    assert 'sensitive-key' not in repr(info)


def test_connector_keeps_upstream_class_unmodified():
    from quii_helper.config import AutonomousConfig
    from quii_helper.protocols.tcp.transport.client import QuiiClient
    from quii_helper.protocols.tcp.live.packet_builder import QuiiLiveOpenPacketBuilder
    config = AutonomousConfig(connection_mode='lan', device_host='192.0.2.10',
                              auth_code='1234', stream_key='a'*32, channel=2, stream=2)
    session = b.ViewDoorConnector(config).create_lan_session()
    assert isinstance(session._client.live_open_builder, b.ViewDoorPacketBuilder)
    other = QuiiClient('192.0.2.10',34567,'adminapp2','p','/mode=real&idc=1&ids=1&ap=2','a'*32)
    assert isinstance(other.live_open_builder, QuiiLiveOpenPacketBuilder)
    session.close()
