"""Hermes Runs API + local automatic-turn speech; handset wire protocol stays unchanged."""
import asyncio
import audioop
from collections import deque
from contextlib import suppress
import json
import os
from pathlib import Path
import re
import signal
import tempfile
import threading
import time
import uuid
from urllib.parse import urlparse

class HermesVoice:
    def __init__(self, endpoint, directory, cwd, model=None, permission_mode='bypass'):
        self.endpoint=endpoint.rstrip('/');self.directory=Path(directory);self.cwd=cwd;self.model=model
        self.permission_mode=permission_mode;self.active=threading.Event();self.speaker=deque(maxlen=100)
        self.state='idle';self.thread_id=None;self.http=None;self.recognizer=None;self.loop_task=None
        self.gateway=None;self.gateway_log=None;self.run_id=None;self.busy=False
        self.frames=[];self.preroll=deque(maxlen=15);self.voiced=0;self.silence=0
        self.target=self.directory/'hermes-thread.json'
        if self.target.exists():self.thread_id=json.loads(self.target.read_text()).get('sessionId')
        self.thread_id=self.thread_id or ('passport-'+uuid.uuid4().hex)
        self.turns=asyncio.Queue(maxsize=1)

    def clear(self):
        self.active.clear();self.speaker.clear();self.frames.clear();self.preroll.clear();self.voiced=self.silence=0
        while not self.turns.empty():
            with suppress(asyncio.QueueEmpty):self.turns.get_nowait()

    def ingest_microphone(self,data):
        if not self.active.is_set() or self.busy:return
        loud=audioop.rms(data,2)>350
        if not self.frames:
            self.preroll.append(data)
            if not loud:return
            self.frames=list(self.preroll);self.preroll.clear()
        else:self.frames.append(data)
        self.voiced+=1 if loud else 0
        self.silence=0 if loud else self.silence+1
        if self.silence>=50 or len(self.frames)>=750:
            pcm=b''.join(self.frames) if self.voiced>=12 else None
            self.frames.clear();self.voiced=self.silence=0
            if pcm and not self.turns.full():self.busy=True;self.turns.put_nowait(pcm)

    async def _request(self,method,path,payload=None):
        async with self.http.request(method,self.endpoint+path,json=payload) as response:
            if response.status>=400:raise RuntimeError('Hermes API request failed: HTTP '+str(response.status))
            if response.content_length and response.content_length>1_000_000:raise RuntimeError('Hermes response too large')
            data=bytearray()
            async for chunk in response.content.iter_chunked(16384):
                data.extend(chunk)
                if len(data)>1_000_000:raise RuntimeError('Hermes response too large')
            return json.loads(data)

    async def connect(self):
        import aiohttp
        if self.permission_mode!='bypass':raise RuntimeError('Hermes voice currently requires its explicitly configured Bypass policy')
        self.state='dialing'
        key=(self.directory/'hermes-key').read_text().strip()
        self.http=aiohttp.ClientSession(headers={'Authorization':'Bearer '+key},timeout=aiohttp.ClientTimeout(total=10))
        try:
            try:await self._request('GET','/v1/capabilities')
            except Exception:
                parsed=urlparse(self.endpoint)
                if parsed.hostname not in ('127.0.0.1','localhost','::1'):raise
                executable=Path.home()/'.local/bin/hermes'
                environment=os.environ.copy();environment['HERMES_YOLO_MODE']='1'
                environment['TERMINAL_CWD']=self.cwd
                log=self.directory/'hermes-gateway.log';fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600);self.gateway_log=os.fdopen(fd,'wb')
                self.gateway=await asyncio.create_subprocess_exec(str(executable),'gateway','run',stdin=asyncio.subprocess.DEVNULL,stdout=self.gateway_log,stderr=self.gateway_log,env=environment,start_new_session=True,cwd=self.cwd)
                deadline=time.monotonic()+20
                while True:
                    try:await self._request('GET','/v1/capabilities');break
                    except Exception:
                        if time.monotonic()>deadline or self.gateway.returncode is not None:raise RuntimeError('Hermes gateway did not become ready')
                        await asyncio.sleep(.4)
            capabilities=await self._request('GET','/v1/capabilities')
            if not capabilities.get('features',{}).get('run_status'):raise RuntimeError('Hermes Runs API unavailable')
            if self.recognizer is None:
                from faster_whisper import WhisperModel
                self.recognizer=await asyncio.to_thread(WhisperModel,'base',device='cpu',compute_type='int8',download_root=str(self.directory/'models'),local_files_only=True)
            self.target.write_text(json.dumps({'sessionId':self.thread_id})+'\n');self.target.chmod(0o600)
            self.state='active';self.active.set();self.loop_task=asyncio.create_task(self._turn_loop())
            print('Hermes voice ready: local STT / Runs API / macOS TTS',flush=True)
        except BaseException:
            await self.disconnect();raise

    def _transcribe(self,pcm):
        import numpy as np
        segments,info=self.recognizer.transcribe(np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768,language='zh',beam_size=1,vad_filter=True,condition_on_previous_text=False)
        return ''.join(s.text for s in segments).strip()

    async def _ask(self,text):
        payload={'input':text,'session_id':self.thread_id,'instructions':'你正在通过 AI Passport 与用户语音通话。用简洁自然的中文回复，少用 Markdown；实际完成文件和终端任务后再报告结果。工作目录：'+self.cwd}
        if self.model:payload['model']=self.model
        # Single creation, no automatic retry: do not duplicate an action on uncertain delivery.
        result=await self._request('POST','/v1/runs',payload);self.run_id=result['run_id']
        deadline=time.monotonic()+180
        try:
            while time.monotonic()<deadline:
                result=await self._request('GET','/v1/runs/'+self.run_id)
                status=result.get('status')
                if status=='completed':return result.get('output','')
                if status in ('failed','cancelled','interrupted','unknown','waiting_for_approval'):raise RuntimeError('Hermes run did not complete: '+status)
                await asyncio.sleep(.5)
            raise RuntimeError('Hermes turn timed out')
        finally:
            if result.get('status')!='completed':
                with suppress(Exception):await self._request('POST','/v1/runs/'+self.run_id+'/stop',{})
            self.run_id=None

    async def _speak(self,text):
        import av
        text=re.sub(r'<think>.*?</think>','',str(text),flags=re.S)
        text=re.sub(r'[`#*]','',text).strip()[:1800]
        if not text:return
        with tempfile.TemporaryDirectory(prefix='passport-speech-') as temp:
            source=Path(temp)/'speech.txt';output=Path(temp)/'speech.aiff';source.write_text(text)
            process=await asyncio.create_subprocess_exec('/usr/bin/say','-v','Tingting','-f',str(source),'-o',str(output),stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
            try:
                await asyncio.wait_for(process.wait(),30)
                if process.returncode:raise RuntimeError('macOS speech synthesis failed')
            finally:
                if process.returncode is None:process.terminate();await process.wait()
            resampler=av.AudioResampler(format='s16',layout='mono',rate=16000);tail=bytearray()
            with av.open(str(output)) as container:
                for frame in container.decode(audio=0):
                    for converted in resampler.resample(frame):
                        tail.extend(bytes(converted.planes[0])[:converted.samples*2])
                        while len(tail)>=640 and self.active.is_set():
                            self.speaker.append(bytes(tail[:640]));del tail[:640];await asyncio.sleep(.02)
            if tail and self.active.is_set():self.speaker.append(bytes(tail).ljust(640,b'\0'))
            await asyncio.sleep(.2)  # drain the last playback packet before accepting echo-prone input

    async def _turn_loop(self):
        try:
            while self.active.is_set():
                pcm=await self.turns.get()
                try:
                    text=await asyncio.to_thread(self._transcribe,pcm)
                    if text:
                        print('Hermes transcript characters=',len(text),flush=True)
                        reply=await self._ask(text);await self._speak(reply)
                finally:self.busy=False
        except asyncio.CancelledError:raise
        except Exception as exc:
            print('Hermes voice stopped:',type(exc).__name__,flush=True);self.state='error';self.clear()

    async def control(self,action):
        if action=='start':await self.connect()
        elif action=='stop':await self.disconnect()
        return self.state

    async def disconnect(self):
        self.clear();self.state='idle'
        if self.run_id and self.http:
            with suppress(Exception):await self._request('POST','/v1/runs/'+self.run_id+'/stop',{})
        if self.loop_task:
            self.loop_task.cancel();await asyncio.gather(self.loop_task,return_exceptions=True);self.loop_task=None
        if self.http:await self.http.close();self.http=None
        if self.gateway and self.gateway.returncode is None:
            with suppress(ProcessLookupError):os.killpg(self.gateway.pid,signal.SIGTERM)
            try:await asyncio.wait_for(self.gateway.wait(),5)
            except TimeoutError:
                with suppress(ProcessLookupError):os.killpg(self.gateway.pid,signal.SIGKILL)
                await self.gateway.wait()
        self.gateway=None
        if self.gateway_log:self.gateway_log.close();self.gateway_log=None
