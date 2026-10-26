"""Experimental QUII talk channel, derived from View Door Android V2.2.11."""
import audioop
import hashlib
import socket
import struct
import threading
import time

from quii_helper.device.security.auth import encode_device_password
from quii_helper.protocols.quii.crypto import aes_cbc_crypt
from quii_helper.protocols.quii.live_packets import build_live_play_packet
from quii_helper.protocols.quii.live_envelope import build_live_play_packet_from_body
from quii_helper.protocols.tcp.codec.message_codec import decode_tcp_header, decode_tcp_payload
from quii_helper.protocols.tcp.transport.client import QuiiClient

class TalkConnection:
    def __init__(self, host, password, key, channel=65535):
        if not isinstance(channel,int) or not 0<=channel<=65535:raise ValueError('Invalid talk channel')
        self.channel=channel
        self.key = key.encode()
        self.client = QuiiClient(host,34567,'adminapp2',encode_device_password(password),f'/talk/idc={channel}&ap=2',key)
        self.lock = threading.RLock()
        self.pending = bytearray()
        self.opened = False
        self.frames_sent = 0

    def packet(self, kind, enable=0, codec=0):
        h=bytearray(32);h[0]=kind
        struct.pack_into('<Q',h,1,int(time.time()))
        struct.pack_into('<H',h,9,32);struct.pack_into('<H',h,11,self.channel);h[13]=enable
        if kind==12:h[14]=codec;struct.pack_into('<H',h,15,8000)
        return aes_cbc_crypt(bytes(h),self.key,crypto_mode=2)+aes_cbc_crypt(hashlib.sha256(h).digest(),self.key,crypto_mode=2)

    def receive(self):
        raw=self.client.recv_exact(32)
        h=decode_tcp_header(raw,crypto_mode=2,key=self.key)
        if not 0<=h.read_size<=1024*1024:raise ValueError('Unexpected audio packet size')
        payload=decode_tcp_payload(h,self.client.recv_exact(h.read_size),crypto_mode=2,key=self.key) if h.read_size else b''
        if not h.is_media:
            size=h.header.raw_size if h.header.packet_type==254 else 0
            digest=hashlib.sha256(h.header.raw+payload[:size]).digest()
            if payload[size:size+32]!=digest:raise ValueError('Audio response integrity check failed')
        return h,payload

    def open(self):
        try:
            self.client.connect(timeout=4);self.client.transport.set_timeout(3)
            setup=bytearray(32);setup[0]=169;setup[9]=2
            self.client.transport.send_all(setup)
            response=self.client.recv_setup()
            if response['status']!=0 or response['crypto_mode']!=2 or response['raw'][11]!=1:raise ValueError('Unsupported audio setup')
            packet=build_live_play_packet(self.client.username,self.client.password,self.client.path,packet_type=11,ext_len_low=self.channel&255,ext_len_high=self.channel>>8,play_param=0,crypto_mode=2,sha_mode=1,key=self.key,encrypt=True)[2]
            self.client.transport.send_all(packet)
            h,_=self.receive()
            if h.header.packet_type!=11 or h.header.raw[11]!=0:raise ValueError('Monitor rejected audio session')
            mask=int.from_bytes(h.header.raw[12:14],'little')
            if not mask&1:raise ValueError('Monitor does not support the verified A-law profile')
            self.client.transport.send_all(self.packet(12,1))
            h,_=self.receive()
            if h.header.packet_type!=12 or h.header.raw[11]!=0:raise ValueError('Monitor rejected talk direction')
            self.client.transport.send_all(self.packet(13,1))
            h,_=self.receive()
            if h.header.packet_type!=13 or h.header.raw[11]!=0:raise ValueError('Monitor rejected listening direction')
            self.opened=True
        except BaseException:
            self.client.close();raise

    def send_pcm(self, pcm):
        with self.lock:
            if not self.opened:return
            if len(pcm)%2 or len(pcm)>32000:raise ValueError('Invalid microphone block')
            self.pending.extend(audioop.lin2alaw(pcm,2))
            # Live Android trace uses 512 A-law samples (64 ms) per packet.
            while len(self.pending)>=512:
                audio=bytes(self.pending[:512]);del self.pending[:512]
                body=struct.pack('<IBBH',0xf0010000,14,2,len(audio))+audio
                h=bytearray(32);h[0]=162
                struct.pack_into('<Q',h,1,int(time.time()))
                struct.pack_into('<H',h,9,32)
                struct.pack_into('<I',h,11,len(body))
                packet=aes_cbc_crypt(bytes(h),self.key,crypto_mode=2)+aes_cbc_crypt(body[:32],self.key,crypto_mode=2)+body[32:]
                self.client.transport.send_all(packet);self.frames_sent+=1

    def route_receive_to_video(self):
        """Use the preview audio path while starting the talk media stream."""
        with self.lock:
            if not self.opened:raise RuntimeError('Audio session is not open')
            self.client.transport.send_all(self.packet(13,0))
            h,_=self.receive()
            if h.header.packet_type!=13 or h.header.raw[11]!=0:
                raise ValueError('Monitor rejected preview audio routing')

    def keepalive(self):
        """Use the native stream control heartbeat while talk media is active."""
        with self.lock:
            if self.opened:
                packet=build_live_play_packet_from_body(b'',packet_type=0,play_param=0,crypto_mode=2,sha_mode=1,key=self.key,encrypt=True)[2]
                self.client.transport.send_all(packet)

    def clear_pending(self):
        with self.lock:self.pending.clear()

    def close(self):
        with self.lock:
            if self.opened:
                for kind in (12,13):
                    try:self.client.transport.send_all(self.packet(kind,0))
                    except OSError:pass
            self.opened=False;self.pending.clear();self.client.close()
