"""Reject false ring detections and preserve the transport boundary."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
p=Path(__file__).parents[1]/'custom_components/vimar_viewdoor/calls.py'
spec=importlib.util.spec_from_file_location('viewdoor_call_tests',p)
c=importlib.util.module_from_spec(spec);sys.modules[spec.name]=c;spec.loader.exec_module(c)

def message(op=23,payload=b'\x01Private household',*,media=False,size=None):
    raw=bytearray(32);raw[13]=op
    return {'header':SimpleNamespace(packet_type=254,raw=raw,raw_size=len(payload) if size is None else size),'payload':payload,'is_media':media}

def test_only_known_callback_is_a_candidate_and_never_verified():
    event=c.parse_call_candidate(message())
    assert event.channel==1 and event.verified is False
    assert 'Private' not in repr(event)

@pytest.mark.parametrize('m',[message(9),message(15),message(media=True),message(payload=b''),message(size=257),message(size=200),{}])
def test_unsupported_or_malformed_data_cannot_be_a_ring(m):
    assert c.parse_call_candidate(m) is None

def test_observer_does_not_send_commands_or_change_received_data():
    class Session:
        def __init__(self):self.timeouts=[]
        def recv_message(self,*,timeout):self.timeouts.append(timeout);return incoming
    incoming=message();s=Session();events=[]
    c.observe_session(s,events.append)
    assert s.recv_message(timeout=.7) is incoming
    assert s.timeouts==[.7] and len(events)==1


def test_zero_channel_is_preserved_without_assuming_numbering():
    assert c.parse_call_candidate(message(payload=b"\0Name")).channel == 0


def test_observer_failure_cannot_break_video():
    incoming=message()
    class Session:
        def recv_message(self,*,timeout):return incoming
    def fail(event):raise RuntimeError('test observer unavailable')
    s=c.observe_session(Session(),fail)
    assert s.recv_message(timeout=.5) is incoming
