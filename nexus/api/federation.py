"""Federation API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nexus.federation import service as fed

router = APIRouter(prefix="/api/federation", tags=["federation"])


class PeerCreate(BaseModel):
    name: str
    endpoint: str


@router.get("/peers")
async def list_peers():
    return {"peers": await fed.list_peers()}


@router.post("/peers")
async def add_peer(body: PeerCreate):
    result = await fed.add_peer(body.name, body.endpoint)
    return result


@router.delete("/peers/{peer_id}")
async def remove_peer(peer_id: str):
    ok = await fed.remove_peer(peer_id)
    if not ok:
        raise HTTPException(404, "Peer not found")
    return {"status": "removed"}


@router.post("/sync/{peer_id}")
async def sync_peer(peer_id: str):
    return await fed.sync_peer(peer_id)


@router.post("/sync")
async def sync_all():
    return {"results": await fed.sync_all_peers()}


@router.get("/agents")
async def search_remote(capability: str = None, tag: str = None):
    return {"remote_agents": await fed.search_remote_agents(capability=capability, tag=tag)}


@router.get("/stats")
async def federation_stats():
    return await fed.get_federation_stats()
