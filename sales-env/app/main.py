"""Shiftpoint sales environment: Jmail + Jdrive + Habspot in one web app.

Run:   .venv/bin/uvicorn app.main:app --port 8000 --reload
Reset: curl -X POST localhost:8000/api/admin/reset
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import events, store
from .routers import admin, calendar, crm, drive, mail, quotes, ui

app = FastAPI(title="Shiftpoint sales environment")
ui.install(app)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.on_event("startup")
def _startup():
    store.load()
    if not events.RUN:
        events.start_run()


@app.get("/")
def root():
    return RedirectResponse("/mail")


for r in (mail.router, drive.router, crm.router, calendar.router, quotes.router, ui.router, admin.router):
    app.include_router(r)
