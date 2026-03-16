"""WebSocket API — Real-time agent-to-agent and dashboard communication."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])
log = logging.getLogger("nexus.ws")

# Connected clients
_connections: dict[str, WebSocket] = {}
_dashboard_connections: list[WebSocket] = []


@router.websocket("/ws/agent/{agent_id}")
async def agent_websocket(websocket: WebSocket, agent_id: str):
    """WebSocket for agent-to-agent real-time communication."""
    await websocket.accept()
    _connections[agent_id] = websocket
    log.info("Agent %s connected via WebSocket", agent_id)

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            message["from_agent"] = agent_id
            message["timestamp"] = datetime.utcnow().isoformat()

            # Forward to target agent if specified
            target = message.get("to_agent")
            if target and target in _connections:
                await _connections[target].send_text(json.dumps(message))

            # Broadcast to dashboard
            await broadcast_to_dashboard({
                "type": "agent_message",
                "data": message,
            })

    except WebSocketDisconnect:
        _connections.pop(agent_id, None)
        log.info("Agent %s disconnected", agent_id)
    except Exception as e:
        _connections.pop(agent_id, None)
        log.error("WebSocket error for agent %s: %s", agent_id, e)


@router.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    """WebSocket for real-time dashboard updates."""
    await websocket.accept()
    _dashboard_connections.append(websocket)
    log.info("Dashboard client connected")

    try:
        while True:
            # Keep alive — dashboard sends pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        _dashboard_connections.remove(websocket)
        log.info("Dashboard client disconnected")
    except Exception:
        if websocket in _dashboard_connections:
            _dashboard_connections.remove(websocket)


async def broadcast_to_dashboard(message: dict) -> None:
    """Send an update to all connected dashboard clients."""
    if not _dashboard_connections:
        return
    text = json.dumps(message, default=str)
    disconnected = []
    for ws in _dashboard_connections:
        try:
            await ws.send_text(text)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _dashboard_connections.remove(ws)


async def notify_event(event_type: str, data: dict) -> None:
    """Notify dashboards of a Nexus event."""
    await broadcast_to_dashboard({
        "type": event_type,
        "data": data,
        "timestamp": datetime.utcnow().isoformat(),
    })


def get_connected_agents() -> list[str]:
    """Get list of agents connected via WebSocket."""
    return list(_connections.keys())
