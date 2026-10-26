"""Private live video/audio preview. No recordings and no ring/unlock commands."""
import asyncio, audioop, hmac, importlib.util, json, math, secrets, sys, threading, time
from pathlib import Path
from aiohttp import web, WSMsgType
from dotenv import dotenv_values
from quii_helper.media.frames.cframe_pack import QuiiCFramePack
from talk import TalkConnection
ROOT=Path(__file__).resolve().parents[2]
(ROOT/'.local').mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('viewdoor_ui_backend',ROOT/'custom_components/vimar_viewdoor/backend.py')
b=importlib.util.module_from_spec(spec);sys.modules[spec.name]=b;spec.loader.exec_module(b)
call_spec=importlib.util.spec_from_file_location('viewdoor_calls',ROOT/'custom_components/vimar_viewdoor/calls.py')
call_module=importlib.util.module_from_spec(call_spec);sys.modules[call_spec.name]=call_module;call_spec.loader.exec_module(call_module)
CFG=dotenv_values(ROOT/'.env');PORT=18766;TOKEN=secrets.token_urlsafe(24)
PIN=CFG.get('CERTIFICATE_FINGERPRINT','').replace(':','').lower()
if len(PIN)!=64 or any(c not in '0123456789abcdef' for c in PIN):raise ValueError('Set a verified CERTIFICATE_FINGERPRINT in the local environment file')
metadata=ROOT/'.local/preview.json'
if metadata.exists():
    from urllib.parse import urlsplit,parse_qs
    saved=parse_qs(urlsplit(json.loads(metadata.read_text()).get('url','')).query).get('token',[''])[0]
    if len(saved)>=24:TOKEN=saved

def authorize(request):
    if not hmac.compare_digest(request.query.get('token',''),TOKEN):raise web.HTTPForbidden()

async def index(request):
    authorize(request)
    return web.Response(text=(Path(__file__).parent/'index.html').read_text(),content_type='text/html',headers={'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self' ws://127.0.0.1:18766; img-src 'self' blob:; media-src 'self' blob:"})

async def socket_handler(request):
    authorize(request)
    if request.headers.get('Origin')!=f'http://127.0.0.1:{PORT}':raise web.HTTPForbidden()
    if request.app['active']:raise web.HTTPConflict(text='Disconnect the other preview first.')
    request.app['active']=True
    ws=web.WebSocketResponse(heartbeat=15,max_msg_size=65536)
    try:await ws.prepare(request)
    except BaseException:request.app['active']=False;raise
    request.app['sockets'].add(ws)
    backend=b.ViewDoorBackend(CFG['CAMERA_DEVICE_HOST'],CFG['AUTH_CODE'],fingerprint=CFG['CERTIFICATE_FINGERPRINT'],data_dir=ROOT/'.local/preview')
    loop=asyncio.get_running_loop();stop=threading.Event();out=asyncio.Queue(60);video=asyncio.Queue(100)
    session=None;talk=None;reader=None;decoder=None;tasks=[];talking=False
    stats={'audio_frames':0,'video_frames':0,'signal_frames':0,'peak':0,'rms':0,'codecs':[]}
    async def message(**data):
        if not ws.closed:await ws.send_json(data)
    def put(queue,item):
        if not stop.is_set() and not queue.full():queue.put_nowait(item)
    def read_media():
        pack=QuiiCFramePack()
        try:
            while not stop.is_set():
                try:m=session.recv_message(timeout=.5)
                except TimeoutError:continue
                if not m['is_media']:
                    candidate=call_module.parse_call_candidate(m)
                    if candidate is not None:
                        loop.call_soon_threadsafe(put,out,{'call_candidate':{'channel':candidate.channel,'verified':False,'source':'device'}})
                    continue
                for f in pack.feed(m['payload']):
                    codec=f.get('codec');kind=f.get('frame_type');data=f['bitstream']
                    if codec==1 and kind in (0,1,9,10):
                        offset=f.get('nal_offset',-1)
                        if offset>=0:loop.call_soon_threadsafe(put,video,data[offset:])
                    elif kind==3 and codec in (4,5):
                        pcm=(audioop.alaw2lin if codec==4 else audioop.ulaw2lin)(data,2)
                        loop.call_soon_threadsafe(received_audio,pcm,codec)
        except Exception:
            if not stop.is_set():loop.call_soon_threadsafe(put,out,{'status':'Camera connection ended. Reconnect to try again.'})
    def received_audio(pcm,codec):
        if stop.is_set():return
        peak=audioop.max(pcm,2);stats['audio_frames']+=1;stats['signal_frames']+=int(peak>8)
        stats['peak']=max(stats['peak'],peak);stats['rms']=audioop.rms(pcm,2)
        if codec not in stats['codecs']:stats['codecs'].append(codec)
        put(out,b'\x02'+pcm)
    async def send_output():
        while True:
            item=await out.get()
            if isinstance(item,dict):await message(**item)
            else:await ws.send_bytes(item)
    async def feed_decoder():
        while True:
            decoder.stdin.write(await video.get());await decoder.stdin.drain()
    async def read_jpegs():
        pending=bytearray()
        while True:
            block=await decoder.stdout.read(65536)
            if not block:return
            pending.extend(block)
            while True:
                start=pending.find(b'\xff\xd8');end=pending.find(b'\xff\xd9',max(0,start+2))
                if start<0 or end<0:break
                frame=bytes(pending[start:end+2]);del pending[:end+2]
                stats['video_frames']+=1;put(out,b'\x01'+frame)
            if len(pending)>4*1024*1024:raise ValueError('Video frame exceeded limit')
    async def diagnostics():
        while True:
            await asyncio.sleep(1);await message(diagnostics=dict(stats),audio_enabled=talk is not None)
    async def silence():
        deadline=loop.time();last_keepalive=deadline
        try:
            while not ws.closed:
                if loop.time()-last_keepalive>=4:
                    await asyncio.to_thread(talk.keepalive);last_keepalive=loop.time()
                if not talking:await asyncio.to_thread(talk.send_pcm,bytes(1024))
                deadline=max(deadline+.064,loop.time());await asyncio.sleep(max(0,deadline-loop.time()))
        except Exception as exc:
            print('Audio sender ended: '+type(exc).__name__,flush=True)
            await message(status='Audio connection ended. Disconnect to release it.');await ws.close()
    async def limit():
        await asyncio.sleep(120);await message(status='Two-minute preview ended. The connection has been released.');await ws.close()
    try:
        await message(status='Connecting to Front Door…')
        await asyncio.to_thread(backend.initialize)
        session=backend.create_camera().connector.create_lan_session();await asyncio.to_thread(session.open)
        decoder=await asyncio.create_subprocess_exec(CFG.get('FFMPEG_BINARY','ffmpeg'),'-hide_banner','-loglevel','error','-probesize','32768','-analyzeduration','0','-f','h264','-i','pipe:0','-an','-vf','fps=8,scale=960:-2','-threads','1','-filter_threads','1','-c:v','mjpeg','-q:v','5','-f','image2pipe','pipe:1',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        reader=threading.Thread(target=read_media,daemon=True);reader.start()
        tasks=[asyncio.create_task(fn()) for fn in (send_output,feed_decoder,read_jpegs,diagnostics,limit)]
        await message(status='Camera connected. Audio is optional and experimental.',connected=True,audio_enabled=False)
        async for msg in ws:
            if msg.type==WSMsgType.TEXT:
                action=msg.json().get('action')
                if action=='enable_audio' and talk is None:
                    candidate=TalkConnection(CFG['CAMERA_DEVICE_HOST'],CFG['AUTH_CODE'],backend.info.stream_key)
                    try:
                        await asyncio.to_thread(candidate.open);await asyncio.to_thread(candidate.route_receive_to_video)
                        talk=candidate;tasks.append(asyncio.create_task(silence()))
                        await message(status='Audio session enabled. Use the quiet check to inspect the incoming signal.',audio_enabled=True)
                    except Exception:
                        await asyncio.to_thread(candidate.close);await message(status='Audio could not connect. Video remains available.',audio_enabled=False)
                elif action=='talk_start' and talk:talking=True
                elif action=='talk_stop':
                    talking=False
                    if talk:await asyncio.to_thread(talk.clear_pending)
                elif action=='reset_diagnostics':stats.update(audio_frames=0,signal_frames=0,peak=0,rms=0)
                elif action=='disconnect':break
            elif msg.type==WSMsgType.BINARY and talking and talk:await asyncio.to_thread(talk.send_pcm,msg.data)
    except Exception as exc:
        await message(status='Connection ended: '+type(exc).__name__)
    finally:
        stop.set()
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        if session:await asyncio.to_thread(session.close)
        if talk:await asyncio.to_thread(talk.close)
        if reader:await asyncio.to_thread(reader.join,2)
        if decoder and decoder.returncode is None:
            decoder.terminate()
            try:await asyncio.wait_for(decoder.wait(),3)
            except asyncio.TimeoutError:decoder.kill();await decoder.wait()
        await asyncio.to_thread(backend.close)
        await ws.close();request.app['sockets'].discard(ws);request.app['active']=False
    return ws

async def shutdown(app):
    await asyncio.gather(*(ws.close(code=1001,message=b'Server stopping') for ws in list(app['sockets'])))
app=web.Application();app['active']=False;app['sockets']=set();app.on_shutdown.append(shutdown)
app.router.add_get('/',index);app.router.add_get('/ws',socket_handler)
metadata.write_text(json.dumps({'url':f'http://127.0.0.1:{PORT}/?token={TOKEN}'}));metadata.chmod(0o600)
if __name__=='__main__':web.run_app(app,host='127.0.0.1',port=PORT,print=lambda _:print('Front Door preview ready on port 18766',flush=True))
