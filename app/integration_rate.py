"""Cross-process provider pacing shared by automatic and interactive reads.

Separate SQLite sidecar avoids changing the application's open read snapshots.
No credentials or response data are stored here.
"""
import sqlite3
import time
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from fastapi import HTTPException
from . import database

@contextmanager
def connection():
    c = sqlite3.connect(str(database.DATABASE_PATH)+'.rate.sqlite3', timeout=10)
    try:
        c.execute('CREATE TABLE IF NOT EXISTS pacing(provider TEXT PRIMARY KEY, next_at REAL NOT NULL, cooldown REAL NOT NULL)')
        yield c
        c.commit()
    except Exception:
        c.rollback();raise
    finally:c.close()

def wait_turn(provider, spacing):
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT next_at,cooldown FROM pacing WHERE provider=?',(provider,)).fetchone()
        now = time.time()
        if row and row[1] > now:
            raise HTTPException(429, 'Provider is cooling down; refresh remains queued', headers={'Retry-After':str(int(row[1]-now)+1)})
        slot = max(now, row[0] if row else now)
        # Do not tie up request threads behind an oversized queue.
        if slot-now > 20:
            raise HTTPException(429, 'Provider queue is busy; retry shortly', headers={'Retry-After':'30'})
        c.execute('INSERT INTO pacing VALUES (?,?,0) ON CONFLICT(provider) DO UPDATE SET next_at=excluded.next_at',(provider,slot+spacing))
    time.sleep(max(0,slot-time.time()))

def backoff(provider, header):
    try:
        seconds = max(1,float(header))
    except (TypeError,ValueError):
        try: seconds = max(1,parsedate_to_datetime(header).timestamp()-time.time())
        except (TypeError,ValueError,OverflowError): seconds = 60
    if not 0 < seconds < float('inf'): seconds = 60
    until=time.time()+seconds
    with connection() as c:
        c.execute('INSERT INTO pacing VALUES (?,0,?) ON CONFLICT(provider) DO UPDATE SET cooldown=MAX(cooldown,excluded.cooldown)',(provider,until))
    return str(int(seconds)+1)
