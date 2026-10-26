"""A stand-in for DeviceVault's monitoring endpoints and a receiver relay, for ``make zabbix-validate``.

Serves the recorded answers in ``responses/`` (standard library only):

- ``<base>/api/monitoring/{summary,device-groups,workers,storage-targets,receivers}/``;
- ``<base>/device/?ip=&id=`` (a relay) and ``<base>/api/monitoring/device/``: ``device.json`` for
  192.0.2.10 or id 12, 503 ``stale`` for 192.0.2.53, and ``found: 0`` for anything else;
- 401 for a missing or wrong bearer token, and for every path under ``/refused/``.

The clock-dependent fields are set at answer time: the summary's ``server_time`` runs ten
minutes slow (so the clock-skew trigger fires) and ``computed_at`` is ten seconds old.
"""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

TOKEN = 'dvt_zabbixte_validation-only-token'
FOUND_IP, FOUND_ID, STALE_IP = '192.0.2.10', '12', '192.0.2.53'
LISTS = {'device-groups', 'workers', 'storage-targets', 'receivers'}

responses = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / 'responses')


def recorded(name: str) -> dict:
    return json.loads((responses / f'{name}.json').read_text())


class Handler(BaseHTTPRequestHandler):
    def answer(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802 (http.server's name)
        url = urlsplit(self.path)
        parts = [part for part in url.path.split('/') if part]
        if self.headers.get('Authorization') != f'Bearer {TOKEN}' or 'refused' in parts:
            return self.answer(401, {'detail': 'Invalid token.'})
        if not parts:
            return self.answer(404, {'detail': 'Not found.'})
        name = parts[-1]
        now = int(time.time())
        if name == 'summary':
            body = recorded('summary')
            body.update(server_time=now - 600, computed_at=now - 10, computed_age=10)
            return self.answer(200, body)
        if name in LISTS:
            return self.answer(200, recorded(name))
        if name == 'device':
            query = {key: values[0] for key, values in parse_qs(url.query).items()}
            ip, device_id = query.get('ip', ''), query.get('id', '')
            if ip == STALE_IP and not device_id:
                return self.answer(503, {'error': 'stale'})
            if device_id == FOUND_ID or (not device_id and ip == FOUND_IP):
                return self.answer(200, recorded('device'))
            device = recorded('device')
            return self.answer(200, {'found': 0, 'published_at': device['published_at'], 'published_age': 120})
        return self.answer(404, {'detail': 'Not found.'})

    def log_message(self, format, *args):  # noqa: A002
        sys.stderr.write(f'stub: {self.command} {self.path} {args[1] if len(args) > 1 else ""}\n')


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
