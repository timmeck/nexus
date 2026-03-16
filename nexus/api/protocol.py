"""Protocol API — Core message handling endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from nexus.models.protocol import NexusRequest, NexusResponse
from nexus.protocol import handler

router = APIRouter(prefix="/api/protocol", tags=["protocol"])


@router.post("/request", response_model=NexusResponse)
async def submit_request(request: NexusRequest):
    """Submit a NexusRequest — routes to best agent and returns response."""
    return await handler.handle_request(request)


@router.get("/active")
async def active_requests():
    """Get currently active (in-flight) requests."""
    return {"active": handler.get_active_requests()}
