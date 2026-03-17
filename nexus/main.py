"""Nexus — AI-to-AI Protocol Layer.

Main FastAPI application entry point.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from nexus import __version__
from nexus.api import protocol, registry, router, trust, websocket, federation, payments, schemas, defense
from nexus.config import STATIC_DIR
from nexus.database import close_db, get_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-20s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("nexus")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    log.info("=" * 60)
    log.info("  NEXUS v%s — AI-to-AI Protocol Layer", __version__)
    log.info("  The network is coming online.")
    log.info("=" * 60)
    await get_db()
    from nexus.federation.service import ensure_tables
    await ensure_tables()
    from nexus.payments.service import ensure_tables as ensure_payment_tables
    await ensure_payment_tables()
    from nexus.defense.service import ensure_tables as ensure_defense_tables
    await ensure_defense_tables()
    yield
    await close_db()
    log.info("Nexus shut down.")


app = FastAPI(
    title="Nexus",
    description="AI-to-AI Protocol Layer — Discovery, Trust, Protocol, Routing",
    version=__version__,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(registry.router)
app.include_router(protocol.router)
app.include_router(router.router)
app.include_router(trust.router)
app.include_router(websocket.router)
app.include_router(federation.router)
app.include_router(payments.router)
app.include_router(schemas.router)
app.include_router(defense.router)

# Dashboard static files
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    """Serve the Nexus dashboard."""
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {
        "name": "Nexus",
        "version": __version__,
        "description": "AI-to-AI Protocol Layer",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": __version__}


@app.get("/api/stats")
async def stats():
    """Network statistics."""
    from nexus.database import get_db

    db = await get_db()

    agents = await db.execute("SELECT COUNT(*) as c FROM agents")
    agents_count = (await agents.fetchone())["c"]

    online = await db.execute("SELECT COUNT(*) as c FROM agents WHERE status = 'online'")
    online_count = (await online.fetchone())["c"]

    interactions = await db.execute("SELECT COUNT(*) as c FROM interactions")
    interactions_count = (await interactions.fetchone())["c"]

    success = await db.execute("SELECT COUNT(*) as c FROM interactions WHERE success = 1")
    success_count = (await success.fetchone())["c"]

    ws_agents = websocket.get_connected_agents()

    auth_enabled = await db.execute("SELECT COUNT(*) as c FROM agents WHERE auth_enabled = 1")
    auth_count = (await auth_enabled.fetchone())["c"]

    verifications = await db.execute("SELECT COUNT(*) as c FROM verifications")
    verifications_count = (await verifications.fetchone())["c"]

    consensus = await db.execute("SELECT COUNT(*) as c FROM verifications WHERE consensus = 1")
    consensus_count = (await consensus.fetchone())["c"]

    from nexus.federation.service import get_federation_stats
    fed_stats = await get_federation_stats()

    from nexus.payments.service import get_payment_stats
    pay_stats = await get_payment_stats()

    from nexus.defense.service import get_defense_stats
    def_stats = await get_defense_stats()

    return {
        "agents_total": agents_count,
        "agents_online": online_count,
        "agents_ws_connected": len(ws_agents),
        "agents_auth_enabled": auth_count,
        "interactions_total": interactions_count,
        "interactions_successful": success_count,
        "success_rate": round(success_count / interactions_count, 4) if interactions_count > 0 else 0,
        "verifications_total": verifications_count,
        "verifications_consensus": consensus_count,
        "federation": fed_stats,
        "payments": pay_stats,
        "defense": def_stats,
        "version": __version__,
    }
