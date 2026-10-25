"""Serializable local settings/status. Never contains login or Wi-Fi secrets."""
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlparse

MODEL = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$')
PERMISSIONS = {
    'readonly': {'sandbox': 'read-only', 'approvalPolicy': 'on-request'},
    'workspace': {'sandbox': 'workspace-write', 'approvalPolicy': 'on-request'},
    'bypass': {'sandbox': 'danger-full-access', 'approvalPolicy': 'never'},
}


def validate_settings(value):
    if not isinstance(value, dict):
        raise ValueError('Settings must be a JSON object')
    if value.get('backend', 'codex') not in ('codex','hermes'):
        raise ValueError('Unknown backend')
    endpoint = value.get('hermesURL', 'http://127.0.0.1:8642')
    parsed = urlparse(endpoint) if isinstance(endpoint,str) else None
    if not parsed or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1','localhost','::1'))):
        raise ValueError('Hermes endpoint requires HTTPS or local loopback HTTP')
    mode = value.get('permissionMode', 'workspace')
    if mode not in PERMISSIONS:
        raise ValueError('Unknown permission mode')
    port = value.get('port', 9443)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Port must be 1024..65535')
    for name in ('taskModel', 'voiceModel'):
        model = value.get(name, '')
        if not isinstance(model, str) or (model and not MODEL.fullmatch(model)):
            raise ValueError('Invalid model identifier')
    cwd = value.get('workspace', '')
    if cwd and (not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).is_dir()):
        raise ValueError('Workspace must be an existing absolute directory')
    host = value.get('listenHost', 'auto')
    if not isinstance(host, str) or not host or len(host) > 128 or any(c.isspace() for c in host):
        raise ValueError('Invalid listening address')
    return value


def lan_address():
    route = subprocess.check_output(['/sbin/route', '-n', 'get', 'default'], text=True, timeout=3)
    found = re.search(r'interface:\s*(\S+)', route)
    if not found:
        raise ValueError('No active network interface')
    address = subprocess.check_output(['/usr/sbin/ipconfig', 'getifaddr', found.group(1)], text=True, timeout=3).strip()
    if not address:
        raise ValueError('No LAN IPv4 address')
    return address


class RuntimeStatus:
    def __init__(self, path, args):
        self.path = Path(path) if path else None
        self.values = {'pid': os.getpid(), 'managedBy': args.managed_by,
                       'startedAt': time.time(), 'state': 'waiting', 'deviceConnected': False,
                       'listenHost': args.listen, 'port': args.port,
                       'permissionMode': args.permission_mode,
                       'taskModel': args.task_model or 'Codex 默认',
                       'voiceModel': args.voice_model or 'gpt-live-1-codex', 'threadId': None,
                       'error': None, 'backend':getattr(args,'backend','codex')}

    def update(self, **changes):
        self.values.update(changes)
        self.values['updatedAt'] = time.time()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temp = self.path.with_suffix('.tmp')
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as handle:
                json.dump(self.values, handle, ensure_ascii=False)
            os.replace(temp, self.path)
