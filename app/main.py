"""Area Book Planner - FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .routers import appointments, billing, clinics, contacts, devices, extras, misc, quotes, tasks

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Area Book Planner", version="1.0.0", lifespan=lifespan)

app.include_router(clinics.router)
app.include_router(contacts.router)
app.include_router(appointments.router)
app.include_router(tasks.router)
app.include_router(extras.router)
app.include_router(devices.router)
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
