"""Bounded GET-only Meraki Dashboard transport. Keys never enter URLs or errors."""
import json
import re
import time
from urllib.parse import urlencode, urljoin, urlsplit, parse_qs
from urllib.request import Request, build_opener
from urllib.error import HTTPError, URLError
from fastapi import HTTPException
from .unifi_client import NoRedirect
from .integration_rate import wait_turn, backoff

ID = r'[A-Za-z0-9_-]{1,128}'
BASE = 'https://api.meraki.com/api/v1'
READ = re.compile(r'(?:/organizations(?:/'+ID+r'/networks)?|/networks/'+ID+r'(?:/(?:devices|clients|appliance/vlans|appliance/vpn/siteToSiteVpn|topology/linkLayer))?|/devices/'+ID+r'/switch/ports)')

class Client:
    def __init__(self, key):
        if not key:
            raise HTTPException(409, 'Save a Meraki API key for this clinic first')
        self.key = key
        self.deadline = time.monotonic() + 240

    def page(self, path, params=None):
        if not READ.fullmatch(path):
            raise ValueError('Unsupported Meraki read path')
        # One conservative budget across all clinic keys also protects shared orgs/IPs.
        wait_turn('meraki', .7)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise HTTPException(502, 'Meraki read time limit reached; no partial inventory imported')
        url = BASE + path + ('?' + urlencode(params) if params else '')
        request = Request(url, headers={'X-Cisco-Meraki-API-Key': self.key, 'Accept': 'application/json'}, method='GET')
        try:
            with build_opener(NoRedirect()).open(request, timeout=min(25, remaining)) as response:
                raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise ValueError()
                return json.loads(raw), response.headers.get('Link', '')
        except HTTPError as e:
            if e.code == 429:
                raise HTTPException(429, 'Meraki rate limit reached; wait for the shared cooldown', headers={'Retry-After': backoff('meraki', e.headers.get('Retry-After'))}) from None
            raise HTTPException(502, f'Meraki returned HTTP {e.code}. Check this clinic’s key permissions, network and API access.') from None
        except (URLError, TimeoutError, ValueError):
            raise HTTPException(502, 'Unable to read a valid bounded Meraki response. Check connectivity and credentials.') from None

    def get(self, path):
        data, _ = self.page(path)
        if not isinstance(data, dict):
            raise HTTPException(502, 'Unexpected Meraki detail response')
        return data

    def collection(self, path, params=None):
        params = dict(params or {})
        result = []; seen = set()
        for _ in range(100):
            data, links = self.page(path, params)
            if not isinstance(data, list) or any(not isinstance(r, dict) for r in data):
                raise HTTPException(502, 'Unexpected Meraki collection response')
            result.extend(data)
            if len(result) > 10000:
                break
            next_links = re.findall(r'<([^>]+)>\s*;\s*rel=["\']?next\b', links)
            if not next_links:
                if re.search(r'rel=["\']?next\b', links):
                    break
                return result
            if len(next_links) != 1:
                break
            # Never follow a supplied URL with the key. Extract only a pagination token
            # after verifying exact origin and path, and keep original filters fixed.
            parsed = urlsplit(urljoin(BASE + path, next_links[0]))
            query = parse_qs(parsed.query)
            token = query.get('startingAfter', [])
            if parsed.scheme != 'https' or parsed.netloc != 'api.meraki.com' or parsed.path != '/api/v1'+path or len(token) != 1 or not token[0] or len(token[0]) > 1024 or token[0] in seen:
                break
            seen.add(token[0]); params['startingAfter'] = token[0]
        raise HTTPException(502, 'Incomplete, repeated or oversized Meraki pagination; nothing imported')
