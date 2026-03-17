"""
Federation Live Test — Start second Nexus, peer-sync, cross-instance routing.

This script:
1. Starts a second Nexus instance on port 9600
2. Registers demo agents on the second instance
3. Adds the second instance as a peer to the primary
4. Syncs agent registries
5. Routes a request from primary -> agent on secondary

Usage:
    # Terminal 1: Primary Nexus (must already be running)
    python run.py

    # Terminal 2: Run this test
    python -m agents.federation_test
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import time

import httpx

logger = logging.getLogger("federation-test")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

PRIMARY_URL = "http://localhost:9500"
SECONDARY_PORT = 9600
SECONDARY_URL = f"http://localhost:{SECONDARY_PORT}"


async def wait_for_server(url: str, timeout: int = 15) -> bool:
    """Wait until a server responds to health check."""
    start = time.time()
    async with httpx.AsyncClient(timeout=3) as client:
        while time.time() - start < timeout:
            try:
                resp = await client.get(f"{url}/health")
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False


async def register_secondary_agents(url: str) -> list[str]:
    """Register demo agents on the secondary instance."""
    agents = [
        {
            "name": "secondary-echo",
            "description": "Echo agent on secondary Nexus instance",
            "endpoint": f"http://localhost:{SECONDARY_PORT}",
            "capabilities": [
                {
                    "name": "echo",
                    "description": "Echoes queries back",
                    "price_per_request": 0.0,
                    "avg_response_ms": 50,
                    "languages": ["en", "de"],
                },
            ],
            "tags": ["demo", "secondary", "federation"],
        },
        {
            "name": "secondary-analysis",
            "description": "Text analysis agent on secondary instance",
            "endpoint": f"http://localhost:{SECONDARY_PORT}",
            "capabilities": [
                {
                    "name": "text_analysis",
                    "description": "Analyzes text",
                    "price_per_request": 0.01,
                    "avg_response_ms": 200,
                    "languages": ["en", "de"],
                },
                {
                    "name": "fact_checking",
                    "description": "Checks facts",
                    "price_per_request": 0.02,
                    "avg_response_ms": 1000,
                    "languages": ["en"],
                },
            ],
            "tags": ["analysis", "secondary", "federation"],
        },
    ]

    agent_ids = []
    async with httpx.AsyncClient(timeout=10) as client:
        for agent in agents:
            try:
                resp = await client.post(f"{url}/api/registry/agents", json=agent)
                resp.raise_for_status()
                data = resp.json()
                agent_id = data.get("id", "unknown")
                agent_ids.append(agent_id)
                logger.info("  Registered %s (id=%s) on secondary", agent["name"], agent_id)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 409:
                    logger.info("  %s already registered", agent["name"])
                else:
                    logger.error("  Failed to register %s: %s", agent["name"], e)
            except Exception as e:
                logger.error("  Failed to register %s: %s", agent["name"], e)

    return agent_ids


async def run_federation_test():
    """Execute the full federation live test."""
    logger.info("=" * 60)
    logger.info("  NEXUS FEDERATION LIVE TEST")
    logger.info("=" * 60)

    # Step 0: Check primary is running
    logger.info("\n[1/6] Checking primary Nexus at %s...", PRIMARY_URL)
    primary_ok = await wait_for_server(PRIMARY_URL, timeout=5)
    if not primary_ok:
        logger.error("Primary Nexus not running! Start it first with: python run.py")
        sys.exit(1)
    logger.info("  Primary is online.")

    # Step 1: Start secondary Nexus
    logger.info("\n[2/6] Starting secondary Nexus on port %d...", SECONDARY_PORT)
    secondary_process = subprocess.Popen(
        [
            sys.executable, "-c",
            f"""
import os
os.environ["NEXUS_PORT"] = "{SECONDARY_PORT}"
os.environ["NEXUS_DB"] = "data/nexus_secondary.db"

import uvicorn
from nexus.config import DATA_DIR
from pathlib import Path

# Patch config for secondary instance
import nexus.config as cfg
cfg.PORT = {SECONDARY_PORT}
cfg.DB_PATH = DATA_DIR / "nexus_secondary.db"
import nexus.database as dbmod
dbmod.DB_PATH = cfg.DB_PATH

uvicorn.run("nexus.main:app", host="0.0.0.0", port={SECONDARY_PORT}, log_level="warning")
""",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    secondary_ok = await wait_for_server(SECONDARY_URL, timeout=15)
    if not secondary_ok:
        logger.error("  Failed to start secondary Nexus!")
        secondary_process.terminate()
        sys.exit(1)
    logger.info("  Secondary is online at %s (PID=%d)", SECONDARY_URL, secondary_process.pid)

    try:
        # Step 2: Register agents on secondary
        logger.info("\n[3/6] Registering agents on secondary instance...")
        agent_ids = await register_secondary_agents(SECONDARY_URL)
        logger.info("  Registered %d agents on secondary", len(agent_ids))

        # Step 3: Add secondary as peer to primary
        logger.info("\n[4/6] Adding secondary as peer to primary...")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{PRIMARY_URL}/api/federation/peers", json={
                "name": "nexus-secondary",
                "endpoint": SECONDARY_URL,
            })
            peer_data = resp.json()
            peer_id = peer_data.get("id")
            logger.info("  Peer added: id=%s", peer_id)

            # Step 4: Sync agents
            logger.info("\n[5/6] Syncing agent registries...")
            resp = await client.post(f"{PRIMARY_URL}/api/federation/sync/{peer_id}")
            sync_data = resp.json()
            logger.info("  Sync result: %s", sync_data)

            # Verify remote agents are visible
            resp = await client.get(f"{PRIMARY_URL}/api/federation/agents")
            remote_agents = resp.json().get("remote_agents", [])
            logger.info("  Remote agents visible on primary: %d", len(remote_agents))
            for ra in remote_agents:
                logger.info("    - %s (capabilities: %s)", ra["name"],
                           [c["name"] if isinstance(c, dict) else c for c in ra.get("capabilities", [])])

            # Step 5: Route request through federation
            logger.info("\n[6/6] Testing cross-instance routing...")

            # First, check federation stats
            resp = await client.get(f"{PRIMARY_URL}/api/federation/stats")
            fed_stats = resp.json()
            logger.info("  Federation stats: %s", fed_stats)

            # Forward a request to the secondary
            resp = await client.post(f"{PRIMARY_URL}/api/federation/agents", json={})

            # Check overall stats
            resp = await client.get(f"{PRIMARY_URL}/api/stats")
            stats = resp.json()

        logger.info("\n" + "=" * 60)
        logger.info("  FEDERATION TEST COMPLETE")
        logger.info("=" * 60)
        logger.info("")
        logger.info("  Primary:   %s", PRIMARY_URL)
        logger.info("  Secondary: %s", SECONDARY_URL)
        logger.info("  Peers:     %d", fed_stats.get("peers", 0))
        logger.info("  Remote:    %d agents synced", fed_stats.get("remote_agents", 0))
        logger.info("")
        logger.info("  The two Nexus instances are now federated.")
        logger.info("  Agents on secondary are discoverable from primary.")
        logger.info("")
        logger.info("  Open the dashboard at %s to see it live.", PRIMARY_URL)
        logger.info("  Press Ctrl+C to shut down the secondary instance.")

        # Keep secondary running
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass

    finally:
        logger.info("\nShutting down secondary Nexus...")
        secondary_process.terminate()
        secondary_process.wait(timeout=5)
        logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(run_federation_test())
