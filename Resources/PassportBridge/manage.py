#!/usr/bin/env python3
"""Small JSON-only native-app helper. No inference or authentication-token reads."""
import argparse
import asyncio
import json
from codex_realtime import AppServer

async def models():
    rpc = AppServer(lambda *args: None)
    try:
        await rpc.start()
        result = await rpc.request('model/list', {'includeHidden': False})
        return {'models': [{'id': item.get('model') or item.get('id'),
                            'name': item.get('displayName') or item.get('model') or item.get('id')}
                           for item in result.get('data', [])]}
    finally:
        await rpc.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['models'])
    parser.parse_args()
    try:
        print(json.dumps(asyncio.run(models()), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'error': str(error)[:300]}, ensure_ascii=False))
        raise SystemExit(1)
