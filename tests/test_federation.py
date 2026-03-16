"""Tests for federation layer."""

import pytest
from nexus.federation import service as fed
from nexus.database import get_db, close_db


@pytest.fixture(autouse=True)
async def setup_db(tmp_path):
    import nexus.config as cfg
    cfg.DB_PATH = tmp_path / "test.db"
    cfg.DATA_DIR = tmp_path
    db = await get_db()
    # Create main schema
    from nexus.database import SCHEMA
    await db.executescript(SCHEMA)
    await fed.ensure_tables()
    await db.commit()
    yield
    await close_db()


@pytest.mark.asyncio
async def test_add_peer():
    result = await fed.add_peer("remote-1", "http://localhost:9600")
    assert result["name"] == "remote-1"
    assert "id" in result


@pytest.mark.asyncio
async def test_list_peers():
    await fed.add_peer("peer-a", "http://a:9500")
    await fed.add_peer("peer-b", "http://b:9500")
    peers = await fed.list_peers()
    assert len(peers) == 2


@pytest.mark.asyncio
async def test_duplicate_peer():
    await fed.add_peer("dup", "http://dup:9500")
    result = await fed.add_peer("dup2", "http://dup:9500")
    assert result["status"] == "already_exists"


@pytest.mark.asyncio
async def test_remove_peer():
    result = await fed.add_peer("remove-me", "http://rm:9500")
    ok = await fed.remove_peer(result["id"])
    assert ok is True


@pytest.mark.asyncio
async def test_remove_nonexistent():
    ok = await fed.remove_peer("nonexistent")
    assert ok is False


@pytest.mark.asyncio
async def test_sync_nonexistent_peer():
    result = await fed.sync_peer("nonexistent")
    assert "error" in result


@pytest.mark.asyncio
async def test_federation_stats():
    stats = await fed.get_federation_stats()
    assert stats["peers"] == 0
    assert stats["remote_agents"] == 0
    assert stats["peers_online"] == 0


@pytest.mark.asyncio
async def test_search_remote_empty():
    agents = await fed.search_remote_agents()
    assert agents == []
