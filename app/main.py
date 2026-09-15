"""Area Book Planner - FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .routers import appointments, billing, clinics, contacts, devices, extras, misc, quotes, tasks, vpn, it_dashboard
from .routers import network
from .routers import connections
from .routers import topology_admin
from .routers import topology_trace
from .routers import syncro
from .routers import unifi
from .routers import integration_sync

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    from .integration_sync import start
    stop,threads=start()
    try:
        yield
    finally:
        stop.set()
        for thread in threads:thread.join(timeout=1)


app = FastAPI(title="Area Book Planner", version="1.0.0", lifespan=lifespan)
from .auth import router as auth_router, admin_router, session_user
from .database import get_db
from .access import permission_for

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(it_dashboard.router)
app.include_router(syncro.router)
app.include_router(unifi.router)
app.include_router(integration_sync.router)


def _origin_key(value: str):
    """Canonical browser origin, rejecting credentials and non-origin URL parts."""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            return None
        return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == 'https' else 80)
    except ValueError:
        return None


def allowed_write_origin(origin: str, request_url: str) -> bool:
    source = _origin_key(origin)
    target = _origin_key(request_url)
    if source is None or target is None:
        return False
    if source == target:
        return True
    # TLS-terminating proxies (including Nginx Proxy Manager) preserve the public
    # Host while forwarding over HTTP. Accept HTTPS for that exact authority,
    # without trusting arbitrary X-Forwarded-* headers or unrelated origins.
    if target[0] == 'http' and source[0] == 'https':
        return source == _origin_key('https://' + urlsplit(request_url).netloc)
    return False


@app.middleware("http")
async def access_gate(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        # Same-origin writes, including login, prevent login CSRF and session switching CSRF.
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin is not None and not allowed_write_origin(origin, str(request.base_url)):
            return JSONResponse({"detail": "Cross-origin writes are not allowed"}, status_code=403)
        if not path.startswith("/api/auth/"):
            try:
                with get_db() as conn:
                    user = session_user(request, conn)
                    if user["must_change_password"]:
                        raise HTTPException(403, "Change your password first")
                    if 'admin' not in user['roles'] and not path.startswith("/api/admin/") and user["active_role"] not in permission_for(path, request.method):
                        raise HTTPException(403, "This action is unavailable in your workspace")
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    response = await call_next(request)
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if path.startswith('/api/attachments/') and path.endswith('/file'):
            # Uploaded HTML/SVG must never execute with the application's session.
            response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
    response.headers['X-Frame-Options'] = 'DENY'
    if not path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-cache'
    return response

app.include_router(clinics.router)
app.include_router(contacts.router)
app.include_router(appointments.router)
app.include_router(tasks.router)
app.include_router(extras.router)
app.include_router(devices.router)
app.include_router(network.router)
app.include_router(connections.router)
app.include_router(topology_admin.router)
app.include_router(topology_trace.router)
app.include_router(vpn.router)
app.include_router(quotes.router)
app.include_router(billing.router)
app.include_router(misc.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    """Serve the single-page app for any non-API path."""
    return FileResponse(STATIC_DIR / "index.html")
