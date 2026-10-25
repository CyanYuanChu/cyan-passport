"""LAN discovery and user-opened pairing window. No plaintext bridge credentials on LAN."""
import asyncio
from contextlib import suppress
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import socket
import time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SERVICE = '_cyan-passport._tcp.local.'
PREFIX = b'CYAN-PASSPORT/1:'
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def pairing_key(code):
    clean = code.replace('-', '').replace(' ', '').upper()
    if len(clean) != 16 or any(c not in ALPHABET for c in clean):
        raise ValueError('Invalid pairing code')
    return hashlib.sha256(clean.encode('ascii')).digest()


def make_envelope(window, challenge, proof, pairing, now=None):
    now = time.time() if now is None else now
    if not isinstance(window, dict) or window.get('expiresAt', 0) <= now:
        raise ValueError('Pairing window closed')
    if not isinstance(challenge, str) or len(challenge) != 32 or any(c not in '0123456789abcdef' for c in challenge):
        raise ValueError('Invalid challenge')
    key = pairing_key(window['code'])
    aad = PREFIX + challenge.encode('ascii')
    expected = hmac.new(key, aad, hashlib.sha256).hexdigest()
    if not isinstance(proof, str) or not hmac.compare_digest(proof, expected):
        raise ValueError('Pairing code mismatch')
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(key).encrypt(nonce, json.dumps(pairing, separators=(',', ':')).encode(), aad)
    return {'nonce': nonce.hex(), 'ciphertext': encrypted.hex()}


class PairingService:
    def __init__(self, directory, host, audio_port):
        self.directory = Path(directory)
        self.host, self.audio_port = host, audio_port
        self.server = self.zc = self.info = None
        self.lock = asyncio.Lock()
        self.last_attempt = 0
        self.last_response = None

    async def start(self):
        from zeroconf import ServiceInfo, IPVersion
        from zeroconf.asyncio import AsyncZeroconf
        self.server = await asyncio.start_server(self.handle, self.host, 0, limit=8192)
        port = self.server.sockets[0].getsockname()[1]
        self.zc = AsyncZeroconf(interfaces=[self.host], ip_version=IPVersion.V4Only)
        # Hostname is a user-facing computer identity, never a token or password.
        label = socket.gethostname().split('.')[0][:40] or 'Cyan-Grove'
        identity = hashlib.sha256(self.host.encode()).hexdigest()[:8]
        self.info = ServiceInfo(SERVICE, f'{label}-{identity}.{SERVICE}',
            addresses=[socket.inet_aton(self.host)], port=port,
            properties={'version':'1', 'name':label, 'audio_port':str(self.audio_port)},
            server=f'cyan-passport-{identity}.local.')
        try:
            await self.zc.async_register_service(self.info)
        except BaseException:
            await self.close()
            raise

    async def handle(self, reader, writer):
        status, response = 400, {'error':'Invalid pairing request'}
        try:
            header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 3)
            if len(header)>2048:raise ValueError('Header too large')
            lines=header.decode('ascii').split('\r\n')
            if lines[0] != 'POST /pair HTTP/1.1':raise ValueError('Unknown endpoint')
            headers={}
            for line in lines[1:]:
                if not line:continue
                name,value=line.split(':',1)
                name=name.strip().lower()
                if name in headers:raise ValueError('Duplicate header')
                headers[name]=value.strip()
            if 'transfer-encoding' in headers or 'origin' in headers:raise ValueError('Unsupported request')
            if headers.get('content-type') != 'application/json':raise ValueError('JSON required')
            length=int(headers.get('content-length','0'))
            if not 1<=length<=256:raise ValueError('Body too large')
            request=json.loads(await asyncio.wait_for(reader.readexactly(length),3))
            async with self.lock:
                # One active request and one attempt/second, including wrong codes.
                now=time.time()
                if now-self.last_attempt<1:raise ValueError('Retry later')
                self.last_attempt=now
                signature=(request.get('challenge'),request.get('proof'))
                if self.last_response and self.last_response[0]==signature and now<self.last_response[1]:
                    response=self.last_response[2]
                else:
                    window_path=self.directory/'pairing-window.json'
                    window=json.loads(window_path.read_text())
                    pairing={'host':self.host,'port':self.audio_port,
                             'cert':(self.directory/'server.pem').read_text(),
                             'token':(self.directory/'token').read_text()}
                    response=make_envelope(window,request.get('challenge'),request.get('proof'),pairing,now)
                    # Consume the window. Only this same authenticated challenge may retry for 30s.
                    window_path.unlink()
                    self.last_response=(signature,now+30,response)
                status=200
        except (ValueError,KeyError,TypeError,OSError,UnicodeError,asyncio.IncompleteReadError,
                asyncio.LimitOverrunError,TimeoutError):
            pass
        try:
            body=json.dumps(response,separators=(',',':')).encode()
            writer.write(f'HTTP/1.1 {status} {"OK" if status==200 else "Bad Request"}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n'.encode()+body)
            await asyncio.wait_for(writer.drain(),2)
        except (ConnectionError,TimeoutError):pass
        finally:
            writer.close()
            with suppress(ConnectionError):await writer.wait_closed()

    async def close(self):
        if self.server:
            self.server.close();await self.server.wait_closed();self.server=None
        if self.zc:
            if self.info:
                with suppress(Exception):await self.zc.async_unregister_service(self.info)
            await self.zc.async_close();self.zc=None
