"""Analytics API — Request, agent, and cost analytics endpoints.

Queries the existing request_events, interactions, and agents tables
to provide dashboard-ready analytics data.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from nexus.database import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/requests")
async def request_analytics(
    period: str = Query("day", pattern="^(hour|day)$"),
):
    """Request volume, success rate, and average latency over time.

    period: 'hour' groups by hour, 'day' groups by day.
    """
    db = await get_db()

    if period == "hour":
        group_expr = "substr(created_at, 1, 13)"  # YYYY-MM-DDTHH
    else:
        group_expr = "substr(created_at, 1, 10)"  # YYYY-MM-DD

    # Request volume per period from interactions
    rows = await db.execute(
        f"""SELECT {group_expr} as period,
                   COUNT(*) as total,
                   SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                   AVG(response_ms) as avg_latency_ms
            FROM interactions
            GROUP BY {group_expr}
            ORDER BY period DESC
            LIMIT 100"""
    )
    periods = []
    for r in await rows.fetchall():
        total = r["total"]
        successful = r["successful"]
        periods.append({
            "period": r["period"],
            "total": total,
            "successful": successful,
            "failed": total - successful,
            "success_rate": round(successful / total, 4) if total > 0 else 0,
            "avg_latency_ms": round(r["avg_latency_ms"], 1) if r["avg_latency_ms"] else 0,
        })

    # Overall stats
    totals_row = await db.execute(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                  AVG(response_ms) as avg_latency_ms
           FROM interactions"""
    )
    totals = await totals_row.fetchone()

    total_all = totals["total"] or 0
    succ_all = totals["successful"] or 0

    return {
        "period_type": period,
        "periods": periods,
        "totals": {
            "total": total_all,
            "successful": succ_all,
            "failed": total_all - succ_all,
            "success_rate": round(succ_all / total_all, 4) if total_all > 0 else 0,
            "avg_latency_ms": round(totals["avg_latency_ms"], 1) if totals["avg_latency_ms"] else 0,
        },
    }


@router.get("/agents")
async def agent_analytics():
    """Per-agent statistics: total requests, avg latency, error rate, trust trend."""
    db = await get_db()

    # Per-agent interaction stats
    rows = await db.execute(
        """SELECT
               i.provider_id as agent_id,
               a.name as agent_name,
               COUNT(*) as total_requests,
               SUM(CASE WHEN i.success = 1 THEN 1 ELSE 0 END) as successful,
               AVG(i.response_ms) as avg_latency_ms,
               SUM(i.cost) as total_cost,
               a.trust_score as current_trust
           FROM interactions i
           LEFT JOIN agents a ON i.provider_id = a.id
           GROUP BY i.provider_id
           ORDER BY total_requests DESC"""
    )

    agents = []
    for r in await rows.fetchall():
        total = r["total_requests"]
        successful = r["successful"]
        failed = total - successful

        # Get trust score trend (last 10 trust ledger entries)
        trust_rows = await db.execute(
            """SELECT trust_after, created_at
               FROM trust_ledger
               WHERE agent_id = ?
               ORDER BY created_at DESC
               LIMIT 10""",
            (r["agent_id"],),
        )
        trust_history = [
            {"trust": tr["trust_after"], "at": tr["created_at"]}
            for tr in await trust_rows.fetchall()
        ]

        agents.append({
            "agent_id": r["agent_id"],
            "agent_name": r["agent_name"],
            "total_requests": total,
            "successful": successful,
            "failed": failed,
            "error_rate": round(failed / total, 4) if total > 0 else 0,
            "avg_latency_ms": round(r["avg_latency_ms"], 1) if r["avg_latency_ms"] else 0,
            "total_cost": round(r["total_cost"], 4) if r["total_cost"] else 0,
            "current_trust": r["current_trust"],
            "trust_trend": trust_history,
        })

    return {"agents": agents, "count": len(agents)}


@router.get("/costs")
async def cost_analytics():
    """Cost breakdown per agent and per capability."""
    db = await get_db()

    # Per-agent cost
    agent_rows = await db.execute(
        """SELECT
               i.provider_id as agent_id,
               a.name as agent_name,
               SUM(i.cost) as total_cost,
               COUNT(*) as total_requests,
               AVG(i.cost) as avg_cost_per_request
           FROM interactions i
           LEFT JOIN agents a ON i.provider_id = a.id
           WHERE i.cost > 0
           GROUP BY i.provider_id
           ORDER BY total_cost DESC"""
    )

    by_agent = []
    for r in await agent_rows.fetchall():
        by_agent.append({
            "agent_id": r["agent_id"],
            "agent_name": r["agent_name"],
            "total_cost": round(r["total_cost"], 4),
            "total_requests": r["total_requests"],
            "avg_cost_per_request": round(r["avg_cost_per_request"], 4),
        })

    # Total cost
    total_row = await db.execute(
        "SELECT SUM(cost) as total, COUNT(*) as paid_requests FROM interactions WHERE cost > 0"
    )
    total = await total_row.fetchone()

    return {
        "by_agent": by_agent,
        "totals": {
            "total_cost": round(total["total"], 4) if total["total"] else 0,
            "paid_requests": total["paid_requests"],
        },
    }
