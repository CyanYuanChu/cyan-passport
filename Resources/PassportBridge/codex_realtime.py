"""Codex 0.162.1 public experimental App Server + WebRTC handset backend.

Uses the installed CLI's normal authentication. Does not read credentials or
control the desktop UI. Network audio uses Opus/WebRTC; the Passport uses PCM16.
"""
import asyncio
from collections import deque
from contextlib import suppress
from fractions import Fraction
import json
import os
from pathlib import Path
import threading
import signal
import sys
import time
from runtime_settings import PERMISSIONS


class RpcError(RuntimeError):
    pass


class AppServer:
    def __init__(self, on_event):
        self.on_event = on_event
        self.process = None
        self.reader_task = None
        self.pending = {}
        self.next_id = 0

    async def start(self):
        child_env = os.environ.copy()
        child_env['VIRTUAL_ENV'] = sys.prefix
        child_env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + child_env.get('PATH', '')
        self.process = await asyncio.create_subprocess_exec(
            'codex', 'app-server', '--listen', 'stdio://',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=2 * 1024 * 1024,
            start_new_session=True, env=child_env)
        self.reader_task = asyncio.create_task(self._read())
        await self.request('initialize', {
            'clientInfo': {'name': 'passport_handset', 'title': 'AI Passport handset', 'version': '0.2.0'},
            'capabilities': {'experimentalApi': True}})
        await self.send({'method': 'initialized'})

    async def send(self, message):
        if not self.process or self.process.returncode is not None:
            raise RpcError('Codex App Server is not running')
        self.process.stdin.write((json.dumps(message, separators=(',', ':')) + '\n').encode())
        await asyncio.wait_for(self.process.stdin.drain(), 3)

    async def request(self, method, params, timeout=25):
        self.next_id += 1
        request_id = self.next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.send({'id': request_id, 'method': method, 'params': params})
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(request_id, None)

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                msg = json.loads(line)
                if 'id' in msg and 'method' in msg:
                    # Never auto-approve tool execution or replace the user's permission policy.
                    await self.send({'id': msg['id'], 'error': {
                        'code': -32000, 'message': 'Handset cannot approve this request; review in Codex.'}})
                    self.on_event('handset/approvalRequired', {})
                elif 'id' in msg:
                    future = self.pending.get(msg['id'])
                    if future is None or future.done():
                        continue
                    if 'error' in msg:
                        error = msg['error']
                        future.set_exception(RpcError(str(error.get('message', 'RPC failed'))[:600]))
                    else:
                        future.set_result(msg.get('result', {}))
                elif 'method' in msg:
                    self.on_event(msg['method'], msg.get('params') or {})
            raise RpcError('Codex App Server closed')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RpcError(type(exc).__name__ + ': App Server connection failed'))
            self.on_event('handset/connectionLost', {})

    async def close(self):
        if self.reader_task:
            self.reader_task.cancel()
            await asyncio.gather(self.reader_task, return_exceptions=True)
        if self.process and self.process.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                await self.process.wait()
        for future in self.pending.values():
            if not future.done():
                future.cancel()
        self.pending.clear()
        self.process = None
        self.reader_task = None


class CodexRealtime:
    def __init__(self, thread_id, cwd=None, target_file=None, permission_mode='workspace', task_model=None, voice_model=None):
        self.thread_id = thread_id
        self.cwd = cwd
        self.target_file = Path(target_file) if target_file else None
        self.permission_mode = permission_mode
        self.task_model = task_model
        self.voice_model = voice_model
        self.mic = deque(maxlen=6)
        self.speaker = deque(maxlen=100)
        self.active = threading.Event()
        self.rpc = None
        self.pc = None
        self.channel = None
        self.audio_tasks = set()
        self.started = asyncio.Event()
        self.transport_ready = asyncio.Event()
        self.answer = asyncio.Event()
        self.failed = asyncio.Event()
        self.answer_sdp = None
        self.failure_reason = None
        self.state = 'idle'
        self.rx_frames = 0
        self.tx_frames = 0
        self.microphone_peak = 0
        self.mic_packets = 0
        self.mic_input_peak = 0
        self.received_peak = 0
        self.dropped_frames = 0
        self.tail = bytearray()
        self.start_requested = False
        self.last_diagnostic = 0
        self.disconnect_lock = asyncio.Lock()

    def ingest_microphone(self, data):
        import audioop
        self.mic_packets += 1
        self.mic_input_peak = max(self.mic_input_peak, audioop.max(data, 2))
        self.mic.append(data)

    def clear(self):
        self.active.clear()
        self.mic.clear()
        self.speaker.clear()
        self.tail.clear()

    def _event(self, method, params):
        if params.get('threadId', self.thread_id) != self.thread_id:
            return
        if method == 'thread/realtime/sdp':
            self.answer_sdp = params.get('sdp')
            self.answer.set()
        elif method == 'thread/realtime/started':
            self.started.set()
        elif method in ('thread/realtime/error', 'handset/connectionLost'):
            self.failure_reason = params.get('message', 'Codex realtime connection lost')
            self.state = 'error'
            self.failed.set()
            self.clear()
        elif method == 'thread/realtime/closed':
            self.state = 'idle'
            self.failed.set()
            self.clear()
        elif method == 'handset/approvalRequired':
            print('Codex requested approval; no approval was granted by the handset.', flush=True)
        elif method == 'thread/realtime/transcript/done':
            print('Codex transcript:', params.get('role'), 'characters=', len(params.get('text', '')), flush=True)

    async def _wait_or_fail(self, event, timeout=25):
        ready = asyncio.create_task(event.wait())
        failed = asyncio.create_task(self.failed.wait())
        try:
            done, _ = await asyncio.wait([ready, failed], timeout=timeout,
                                         return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise RpcError('Codex call connection timed out')
            if self.failed.is_set():
                raise RpcError(self.failure_reason or 'Codex call closed during connection')
        finally:
            for task in (ready, failed):
                task.cancel()
            await asyncio.gather(ready, failed, return_exceptions=True)

    async def connect(self):
        from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription, RTCRtpSender
        self.state = 'dialing'
        self.started.clear(); self.transport_ready.clear(); self.answer.clear(); self.failed.clear()
        self.failure_reason = None
        self.clear()
        self.rpc = AppServer(self._event)
        try:
            await self.rpc.start()
            settings = dict(PERMISSIONS[self.permission_mode])
            if self.task_model:
                settings['model'] = self.task_model
            if self.thread_id:
                result = await self.rpc.request('thread/resume', {
                    'threadId': self.thread_id, 'excludeTurns': True,
                    'cwd': self.cwd,
                    **settings})
            else:
                result = await self.rpc.request('thread/start', {
                    'cwd': self.cwd, **settings})
                self.thread_id = result['thread']['id']
                if self.target_file:
                    self.target_file.write_text(json.dumps({'threadId': self.thread_id, 'cwd': self.cwd}) + '\n')
                    self.target_file.chmod(0o600)
                print('Dedicated Codex voice thread:', self.thread_id, flush=True)
            expected = PERMISSIONS[self.permission_mode]
            policy = result.get('sandbox', {})
            actual_sandbox = policy.get('type') if isinstance(policy, dict) else policy
            response_sandbox = {'read-only':'readOnly','workspace-write':'workspaceWrite','danger-full-access':'dangerFullAccess'}[expected['sandbox']]
            if actual_sandbox != response_sandbox or result.get('approvalPolicy') != expected['approvalPolicy']:
                raise RpcError('Codex returned a different execution permission policy')
            print('Codex effective policy:', actual_sandbox, result['approvalPolicy'],
                  'model:', result.get('model', 'default'), flush=True)
            self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
            self.pc.addTrack(self._microphone_track())
            for transceiver in self.pc.getTransceivers():
                codecs = [codec for codec in RTCRtpSender.getCapabilities('audio').codecs
                          if codec.mimeType.lower() == 'audio/opus']
                transceiver.setCodecPreferences(codecs)
            self.channel = self.pc.createDataChannel('oai-events', ordered=True)

            @self.channel.on('open')
            def on_open():
                self.transport_ready.set()

            @self.pc.on('connectionstatechange')
            async def on_connection():
                if self.pc and self.pc.connectionState in ('failed', 'closed') and self.state != 'idle':
                    self.failure_reason = 'WebRTC connection closed'
                    self.state = 'error'; self.failed.set(); self.clear()

            @self.pc.on('track')
            def on_track(track):
                if track.kind == 'audio':
                    task = asyncio.create_task(self._receive_audio(track))
                    self.audio_tasks.add(task)
                    task.add_done_callback(self.audio_tasks.discard)

            offer = await self.pc.createOffer()
            await self.pc.setLocalDescription(offer)
            self.start_requested = True
            voice_settings = {'model': self.voice_model} if self.voice_model else {}
            await self.rpc.request('thread/realtime/start', {
                'threadId': self.thread_id, 'outputModality': 'audio', 'version': 'v3',
                'transport': {'type': 'webrtc', 'sdp': self.pc.localDescription.sdp},
                'includeStartupContext': True, 'clientManagedHandoffs': False, **voice_settings})
            await self._wait_or_fail(self.answer)
            await self.pc.setRemoteDescription(RTCSessionDescription(sdp=self.answer_sdp, type='answer'))
            await self._wait_or_fail(self.started)
            await self._wait_or_fail(self.transport_ready)
            self.state = 'active'
            return self.state
        except BaseException:
            await self.disconnect()
            self.state = 'error'
            raise

    def _microphone_track(self):
        from aiortc import MediaStreamTrack
        import av
        owner = self

        class Microphone(MediaStreamTrack):
            kind = 'audio'

            def __init__(self):
                super().__init__()
                self.origin = None
                self.samples = 0

            async def recv(self):
                if self.origin is None:
                    self.origin = time.monotonic()
                await asyncio.sleep(max(0, self.origin + self.samples / 16000 - time.monotonic()))
                try:
                    data = owner.mic.popleft() if owner.active.is_set() else bytes(640)
                except IndexError:
                    data = bytes(640)
                import audioop
                if owner.active.is_set():
                    owner.microphone_peak = max(owner.microphone_peak, audioop.max(data, 2))
                frame = av.AudioFrame(format='s16', layout='mono', samples=320)
                frame.planes[0].update(data)
                frame.sample_rate = 16000
                frame.pts = self.samples
                frame.time_base = Fraction(1, 16000)
                self.samples += 320
                owner.tx_frames += 1
                return frame

        return Microphone()

    async def _receive_audio(self, track):
        import av
        import audioop
        resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
        try:
            while True:
                frame = await track.recv()
                for output in resampler.resample(frame):
                    # AV planes may be padded; use the declared sample count, not plane size.
                    data = bytes(output.planes[0])[:output.samples * 2]
                    self.received_peak = max(self.received_peak, audioop.max(data, 2))
                    if not self.active.is_set():
                        continue
                    self.tail.extend(data)
                    while len(self.tail) >= 640:
                        if len(self.speaker) == self.speaker.maxlen:
                            self.dropped_frames += 1
                        self.speaker.append(bytes(self.tail[:640]))
                        del self.tail[:640]
                        self.rx_frames += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            if self.state == 'active':
                self.state = 'error'; self.failed.set(); self.clear()

    async def disconnect(self):
        async with self.disconnect_lock:
            await self._disconnect()

    async def _disconnect(self):
        had_connection = self.pc is not None or self.rpc is not None
        self.state = 'idle'
        self.clear()
        if self.start_requested and self.rpc:
            with suppress(Exception):
                await self.rpc.request('thread/realtime/stop', {'threadId': self.thread_id}, timeout=3)
        self.start_requested = False
        if self.pc:
            with suppress(TimeoutError):
                await asyncio.wait_for(self.pc.close(), 3)
            self.pc = None
        for task in list(self.audio_tasks):
            task.cancel()
        await asyncio.gather(*self.audio_tasks, return_exceptions=True)
        self.audio_tasks.clear()
        if self.rpc:
            await self.rpc.close()
            self.rpc = None
        if had_connection:
            print(f'WebRTC counters: microphone={self.tx_frames}, speaker={self.rx_frames}, '
                  f'microphone_peak={self.microphone_peak}, speaker_peak={self.received_peak}, '
                  f'dropped={self.dropped_frames}', flush=True)

    async def control(self, action):
        if action == 'start':
            return await self.connect()
        if action == 'stop':
            await self.disconnect()
        if action == 'status' and self.pc and time.monotonic() - self.last_diagnostic > 5:
            self.last_diagnostic = time.monotonic()
            stats = await self.pc.getStats()
            inbound = sum(getattr(item, 'packetsReceived', 0) for item in stats.values() if item.type == 'inbound-rtp')
            outbound = sum(getattr(item, 'packetsSent', 0) for item in stats.values() if item.type == 'outbound-rtp')
            print(f'Audio diagnostic: handset_packets={self.mic_packets}, handset_peak={self.mic_input_peak}, '
                  f'rtp_sent={outbound}, rtp_received={inbound}, remote_peak={self.received_peak}', flush=True)
        return self.state
