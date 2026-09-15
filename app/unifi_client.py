"""Bounded, GET-only official UniFi cloud transport. No arbitrary URLs or paths."""
import json
import re
import threading
import time
from urllib.parse import urlencode, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from fastapi import HTTPException
from .integration_rate import wait_turn, backoff

ID = r'[A-Za-z0-9_-]{1,128}'
HOST = r'[A-Za-z0-9_:-]{1,200}'
READ_PATH = re.compile(r'/v1/(?:sites|sites/'+ID+r'/(?:devices(?:/'+ID+r')?|clients|networks(?:/'+ID+r')?|vpn/site-to-site-tunnels))')
_lock = threading.Lock()
_last = 0.0

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class Client:
    def __init__(self, key):
        if not key:
            raise HTTPException(409, 'Configure UniFi in Global settings first')
        self.key = key
        self.deadline = time.monotonic() + 90

    def get(self, path, host=None, params=None):
        global _last
        if host is None:
            if path != '/v1/hosts':
                raise ValueError('Unsupported UniFi cloud read')
            target = path
        else:
            if not re.fullmatch(HOST, host) or not READ_PATH.fullmatch(path):
                raise ValueError('Unsupported UniFi Network read')
            target = '/v1/connector/consoles/' + quote(host, safe=':') + '/proxy/network/integration' + path
        wait_turn('unifi', .7)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise HTTPException(502, 'UniFi read time limit reached; try a smaller site or retry')
        req = Request('https://api.ui.com' + target + '?' + urlencode(params or {}),
                      headers={'X-API-Key': self.key, 'Accept': 'application/json'}, method='GET')
        try:
            with build_opener(NoRedirect()).open(req, timeout=min(25, remaining)) as response:
                raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise HTTPException(502, 'UniFi response exceeds the safe size limit')
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError()
                return data
        except HTTPError as e:
            if e.code == 429:
                raise HTTPException(429, 'UniFi rate limit reached; retry is queued after the provider cooldown', headers={'Retry-After':backoff('unifi', e.headers.get('Retry-After'))}) from None
            raise HTTPException(502, f'UniFi returned HTTP {e.code}. Check key access, console connectivity and firmware (cloud connector requires 5.0.3+). For 429, wait before retrying.') from None
        except (URLError, TimeoutError, ValueError):
            raise HTTPException(502, 'Unable to read UniFi. Check connectivity and saved credentials.') from None

    def collection(self, path, host=None):
        result = []; seen = set(); row_ids = set(); token = None; offset = 0
        for _ in range(100):
            params = {'pageSize': 100, **({'nextToken': token} if token else {})} if host is None else {'limit': 100, 'offset': offset}
            data = self.get(path, host, params)
            rows = data.get('data')
            if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                raise HTTPException(502, 'Unexpected UniFi collection response; nothing imported')
            for row in rows:
                identity = row.get('id')
                if not isinstance(identity, str) or identity in row_ids:
                    raise HTTPException(502, 'Repeated or missing UniFi identity; collection incomplete, nothing imported')
                row_ids.add(identity)
            result.extend(rows)
            if len(result) > 10000:
                break
            if host is None:
                token = data.get('nextToken')
                if not token:
                    return result
                if not isinstance(token, str) or token in seen:
                    break
                seen.add(token)
            else:
                total = data.get('totalCount')
                if not isinstance(total, int) or total < 0:
                    raise HTTPException(502, 'UniFi pagination metadata missing; nothing imported')
                offset += len(rows)
                if offset >= total:
                    return result
                if not rows:
                    break
        raise HTTPException(502, 'Incomplete or oversized UniFi collection; nothing imported')
