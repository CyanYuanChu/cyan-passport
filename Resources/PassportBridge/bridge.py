#!/usr/bin/env python3
"""AI Passport TLS audio bridge. No private Codex endpoints or session cookies."""
import argparse
import asyncio
from collections import deque
from contextlib import suppress
from datetime import datetime, timedelta, timezone
import hmac
import json
import os
from pathlib import Path
import secrets
import ssl
import sys
import threading
from runtime_settings import RuntimeStatus, validate_settings, lan_address

from protocol import (AUTH, READY, CALL, STATE, MIC, SPEAKER, PING, IDLE,
                      DIALING, ACTIVE, ERROR, Decoder, encode)

LOCAL = Path(os.environ.get('CYAN_PASSPORT_DATA_DIR', str(Path(__file__).resolve().parent / 'local'))).expanduser()


def initialize():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    paths = [LOCAL / n for n in ('server.pem', 'server-key.pem', 'token')]
    if all(p.exists() for p in paths):
        return
    if any(p.exists() for p in paths):
        raise RuntimeError('Partial pairing files; preserve them and inspect before retrying')
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'dots-bridge')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('dots-bridge')]), critical=False)
            .sign(key, hashes.SHA256()))
    data = [cert.public_bytes(serialization.Encoding.PEM),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()), secrets.token_hex(32).encode()]
    for p, value in zip(paths, data):
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as out:
            out.write(value)


def agent_backend(args):
    return getattr(args,'backend','codex') == 'hermes' or bool(getattr(args,'codex_thread',None) or getattr(args,'codex_new',False))


def put_latest(queue, data):
    # At most 120 ms; stale audio is discarded instead of growing latency.
    queue.append(data)


class Audio:
    def __init__(self, input_device, output_device):
        import sounddevice as sd
        if input_device == output_device:
            raise ValueError('Use two separate virtual buses to avoid feedback')
        self.mic = deque(maxlen=6)
        self.speaker = deque(maxlen=6)
        self.active = threading.Event()
        self.xruns = 0

        def play(outdata, frames, timing, status):
            if status:
                self.xruns += 1
            try:
                data = self.mic.popleft() if self.active.is_set() else bytes(640)
            except IndexError:
                data = bytes(640)
            outdata[:] = data

        def record(indata, frames, timing, status):
            if status:
                self.xruns += 1
            if self.active.is_set():
                put_latest(self.speaker, bytes(indata))

        self.output = sd.RawOutputStream(device=output_device, samplerate=16000,
                                        blocksize=320, channels=1, dtype='int16', callback=play)
        try:
            self.input = sd.RawInputStream(device=input_device, samplerate=16000,
                                          blocksize=320, channels=1, dtype='int16', callback=record)
        except BaseException:
            self.output.close()
            raise

    def start(self):
        self.output.start()
        try:
            self.input.start()
        except BaseException:
            self.stop()
            raise

    def stop(self):
        self.active.clear()
        self.input.close()
        self.output.close()

    def clear(self):
        self.active.clear()
        self.mic.clear()
        self.speaker.clear()


class Session:
    def __init__(self, reader, writer, args, audio):
        self.reader, self.writer, self.args, self.audio = reader, writer, args, audio
        self.decoder = Decoder()
        self.pending = deque()
        self.state = IDLE
        self.call_lock = asyncio.Lock()
        self.authenticated = False
        self.last_seen = 0
        self.control_task = None

    async def send(self, kind, payload=b''):
        self.writer.write(encode(kind, payload))
        await asyncio.wait_for(self.writer.drain(), 2)

    async def set_state(self, state):
        self.state = state
        if self.audio:
            self.audio.clear()
            if state == ACTIVE:
                self.audio.active.set()
        await self.send(STATE, bytes([state]))
        print('Bridge state:', ['idle', 'dialing', 'active', 'error'][state], flush=True)
        if getattr(self.args, '_runtime_status', None):
            self.args._runtime_status.update(state=['idle', 'dialing', 'active', 'error'][state],
                deviceConnected=self.authenticated,
                threadId=getattr(self.audio, 'thread_id', None))

    async def controller(self, action):
        if agent_backend(self.args):
            state = await self.audio.control(action)
            return {'idle': IDLE, 'dialing': DIALING, 'active': ACTIVE, 'error': ERROR}[state]
        if self.args.controller:
            # A local adapter must implement start/stop/status and report observed state.
            proc = await asyncio.create_subprocess_exec(
                self.args.controller, action, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            try:
                output, _ = await asyncio.wait_for(proc.communicate(), 3)
            except BaseException:
                proc.kill()
                await proc.wait()
                raise
            if proc.returncode or len(output) > 4096:
                raise RuntimeError('Call controller failed')
            result = json.loads(output)
            if result.get('state') not in ('idle', 'dialing', 'active', 'error'):
                raise RuntimeError('Controller returned an invalid state')
            return {'idle': IDLE, 'dialing': DIALING, 'active': ACTIVE, 'error': ERROR}[result['state']]
        if self.args.manual:
            if action == 'stop':
                print('Audio disconnected. End the Codex call manually.', flush=True)
                return IDLE
            if action == 'start':
                print('Open the intended Codex voice call; type answer after it is connected.', flush=True)
                return DIALING
            return self.state
        raise RuntimeError('No supported Codex call controller is configured')

    async def change_call(self, start):
        async with self.call_lock:
            if start:
                await self.set_state(DIALING)
            try:
                state = await asyncio.wait_for(self.controller('start' if start else 'stop'), 28)
                await self.set_state(state)
            except Exception as exc:
                print(str(exc), file=sys.stderr, flush=True)
                await self.set_state(ERROR)

    async def request_call(self, start):
        if self.control_task and not self.control_task.done():
            self.control_task.cancel()
            await asyncio.gather(self.control_task, return_exceptions=True)
        self.control_task = asyncio.create_task(self.change_call(start))

    async def close(self):
        if self.control_task:
            self.control_task.cancel()
            await asyncio.gather(self.control_task, return_exceptions=True)
        if self.authenticated and (self.state in (ACTIVE, DIALING) or agent_backend(self.args)):
            with suppress(Exception):
                await self.controller('stop')

    async def receive(self):
        while True:
            if not self.pending:
                data = await asyncio.wait_for(self.reader.read(2048), 10)
                if not data:
                    raise EOFError('Device disconnected')
                self.pending.extend(self.decoder.feed(data))
                self.last_seen = asyncio.get_running_loop().time()
                continue
            yield self.pending.popleft()

    async def run(self):
        frames = self.receive()
        kind, payload, _ = await asyncio.wait_for(anext(frames), 5)
        token = (LOCAL / 'token').read_bytes()
        if kind != AUTH or not hmac.compare_digest(payload, token):
            raise ValueError('Authentication failed')
        self.authenticated = True
        await self.send(READY)
        await self.set_state(IDLE)
        async for kind, payload, _ in frames:
            if kind == CALL and payload in (b'\x00', b'\x01'):
                # Keep receiving heartbeats during WebRTC negotiation.
                await self.request_call(payload == b'\x01')
            elif kind == MIC:
                if self.state == ACTIVE and self.audio:
                    if hasattr(self.audio, 'ingest_microphone'):
                        self.audio.ingest_microphone(payload)
                    else:
                        put_latest(self.audio.mic, payload)
            elif kind == PING and not payload:
                await self.send(PING)
            else:
                raise ValueError('Unexpected client frame')

    async def transmit(self):
        loop = asyncio.get_running_loop()
        last_status = loop.time()
        dial_deadline = None
        while True:
            await asyncio.sleep(.02)
            if self.state == ACTIVE and self.audio and self.audio.speaker:
                await self.send(SPEAKER, self.audio.speaker.popleft())
            if self.state == DIALING:
                dial_deadline = dial_deadline or loop.time() + 30
                if loop.time() > dial_deadline:
                    await self.set_state(ERROR)
            else:
                dial_deadline = None
            if self.authenticated and (self.args.controller or agent_backend(self.args)) and loop.time() - last_status >= 2:
                if not self.call_lock.locked() and self.state in (ACTIVE, DIALING):
                    async with self.call_lock:
                        state = await self.controller('status')
                        if state != self.state:
                            await self.set_state(state)
                last_status = loop.time()


async def serve(args):
    initialize()
    status = RuntimeStatus(args.status_file, args)
    args._runtime_status = status
    direct = agent_backend(args)
    if direct:
        if getattr(args,'backend','codex') == 'hermes':
            from hermes_voice import HermesVoice
            audio = HermesVoice(args.hermes_url,LOCAL,args.codex_cwd,args.task_model,args.permission_mode)
        else:
            from codex_realtime import CodexRealtime
            target_file = LOCAL / 'target-thread.json'
            thread_id = args.codex_thread
            if args.codex_new and target_file.exists():
                thread_id = json.loads(target_file.read_text())['threadId']
            audio = CodexRealtime(thread_id, args.codex_cwd, target_file,
                                  args.permission_mode, args.task_model, args.voice_model)
    else:
        audio = None if args.no_audio else Audio(args.input_device, args.output_device)
    if audio and not direct:
        audio.start()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(LOCAL / 'server.pem', LOCAL / 'server-key.pem')
    current = None
    connection_task = None

    async def accept(reader, writer):
        nonlocal current, connection_task
        # One paired device at a time; unauthenticated clients time out in five seconds.
        if current is not None:
            writer.close()
            await writer.wait_closed()
            return
        session = Session(reader, writer, args, audio)
        current = session
        connection_task = asyncio.current_task()
        tasks = [asyncio.create_task(session.run()), asyncio.create_task(session.transmit())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (ConnectionError, EOFError, ValueError, TimeoutError, RuntimeError) as exc:
            print('Session closed:', str(exc), flush=True)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await session.close()
            if audio:
                audio.clear()
            writer.close()
            with suppress(ConnectionError, ssl.SSLError):
                await writer.wait_closed()
            current = None
            connection_task = None
            status.update(state='waiting', deviceConnected=False)

    async def console():
        # Manual proof-of-concept only; this does not operate Codex UI.
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)
        while line := await reader.readline():
            command = line.decode().strip()
            if current and args.manual:
                if command == 'answer' and current.state == DIALING:
                    await current.set_state(ACTIVE)
                elif command == 'ended':
                    await current.set_state(IDLE)

    server = await asyncio.start_server(accept, args.listen, args.port, ssl=ctx,
                                       ssl_handshake_timeout=5)
    pairing_service = None
    if args.managed_by == 'cyangrove':
        try:
            from pairing_service import PairingService
            pairing_service = PairingService(LOCAL, args.listen, args.port)
            await pairing_service.start()
            status.update(discoveryState='ready')
        except Exception as exc:
            if pairing_service:
                await pairing_service.close()
            pairing_service = None
            status.update(discoveryState='error')
            print('LAN discovery unavailable:', type(exc).__name__, flush=True)
    status.update()
    async def heartbeat():
        while True:
            await asyncio.sleep(2)
            status.update(threadId=getattr(audio, 'thread_id', None))
    heartbeat_task = asyncio.create_task(heartbeat())
    print(f'TLS bridge listening on {args.listen}:{args.port}', flush=True)
    print('Mode:', 'MANUAL CALL CONTROL' if args.manual else 'EXTERNAL CONTROLLER' if args.controller
          else ('HERMES / LOCAL STT / MACOS TTS' if getattr(args,'backend','codex') == 'hermes' else 'CODEX APP SERVER / WEBRTC') if direct
          else 'NO CALL CONTROL; requests will report ERROR', flush=True)
    print('Audio:', ('local STT/TTS <-> Passport PCM16' if getattr(args,'backend','codex') == 'hermes' else 'WebRTC Opus <-> Passport PCM16') if direct else
          'DISABLED / PROTOCOL TEST ONLY' if args.no_audio else 'virtual audio buses', flush=True)
    console_task = asyncio.create_task(console()) if args.manual and sys.stdin.isatty() else None
    try:
        async with server:
            await server.serve_forever()
    finally:
        if pairing_service:
            await pairing_service.close()
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        if console_task:
            console_task.cancel()
        if connection_task:
            connection_task.cancel()
            await asyncio.gather(connection_task, return_exceptions=True)
        if direct:
            await audio.disconnect()
        elif audio:
            audio.stop()
        status.update(state='stopped', deviceConnected=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    sub.add_parser('devices')
    p = sub.add_parser('serve')
    p.add_argument('--listen', default='127.0.0.1')
    p.add_argument('--port', type=int, default=9443)
    p.add_argument('--config')
    p.add_argument('--status-file')
    p.add_argument('--managed-by', default='standalone')
    p.add_argument('--permission-mode', choices=['readonly','workspace','bypass'], default='workspace')
    p.add_argument('--task-model')
    p.add_argument('--voice-model')
    p.add_argument('--backend', choices=['codex','hermes'], default='codex')
    p.add_argument('--hermes-url', default='http://127.0.0.1:8642')
    p.add_argument('--input-device', default='BlackHole 16ch')
    p.add_argument('--output-device', default='BlackHole 2ch')
    p.add_argument('--no-audio', action='store_true', help='Protocol tests only, not a Dots call')
    control = p.add_mutually_exclusive_group()
    control.add_argument('--manual', action='store_true')
    control.add_argument('--controller', help='Absolute executable path: start/stop/status -> JSON state')
    control.add_argument('--codex-thread', help='Existing Codex thread UUID; direct experimental WebRTC')
    control.add_argument('--codex-new', action='store_true', help='Create or reuse the dedicated handset thread')
    p.add_argument('--codex-cwd', default=str(Path(__file__).resolve().parent.parent), help='Workspace for a new dedicated Codex voice thread')
    args = parser.parse_args()
    if args.command == 'init':
        initialize()
        print('Pairing keys generated in companion/local (not printed).')
    elif args.command == 'devices':
        import sounddevice
        print(sounddevice.query_devices())
    else:
        if args.config:
            settings = validate_settings(json.loads(Path(args.config).read_text()))
            args.listen = settings.get('listenHost', 'auto')
            args.port = settings.get('port', 9443)
            args.permission_mode = settings.get('permissionMode', 'workspace')
            args.task_model = settings.get('taskModel') or None
            args.voice_model = settings.get('voiceModel') or None
            args.backend = settings.get('backend') or 'codex'
            args.hermes_url = settings.get('hermesURL') or 'http://127.0.0.1:8642'
            args.codex_cwd = settings.get('workspace') or args.codex_cwd
        if args.listen == 'auto':
            args.listen = lan_address()
        if agent_backend(args) and args.no_audio:
            parser.error('Direct Codex mode already supplies audio; do not combine with --no-audio')
        if args.controller and not Path(args.controller).is_absolute():
            parser.error('--controller must be an absolute local path')
        try:
            asyncio.run(serve(args))
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
