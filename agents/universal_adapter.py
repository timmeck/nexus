"""
Universal Nexus Adapter — Proxy NexusRequests to any product's existing API.

Wraps all 8 products (Cortex, DocBrain, Mnemonic, DeepResearch, Sentinel,
CostControl, SafetyProxy, LogAnalyst) behind the Nexus protocol.

Usage:
    python -m agents.universal_adapter

Or selectively:
    python -m agents.universal_adapter --agents cortex,docbrain
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

import httpx

logger = logging.getLogger("nexus-adapter")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

NEXUS_URL = "http://localhost:9500"

# ─── Product API Mappings ────────────────────────────────────────────────
# Maps capability -> product endpoint that handles the actual work.
# Each entry defines how to translate a NexusRequest into a product API call.

PRODUCT_APIS: dict[str, dict[str, Any]] = {
    "cortex": {
        "base_url": "http://localhost:8100",
        "capabilities": {
            "text_generation": {
                "method": "POST",
                "path": "/api/generate",
                "map_request": lambda q, p: {"prompt": q, **p},
                "map_response": lambda r: {
                    "result": r.get("text", r.get("response", str(r))),
                    "confidence": r.get("confidence", 0.85),
                },
            },
            "code_analysis": {
                "method": "POST",
                "path": "/api/analyze",
                "map_request": lambda q, p: {"code": q, **p},
                "map_response": lambda r: {
                    "result": r.get("analysis", str(r)),
                    "confidence": r.get("confidence", 0.8),
                },
            },
        },
    },
    "docbrain": {
        "base_url": "http://localhost:8200",
        "capabilities": {
            "document_analysis": {
                "method": "POST",
                "path": "/api/analyze",
                "map_request": lambda q, p: {"query": q, **p},
                "map_response": lambda r: {
                    "result": r.get("analysis", str(r)),
                    "confidence": r.get("confidence", 0.8),
                },
            },
            "knowledge_retrieval": {
                "method": "POST",
                "path": "/api/search",
                "map_request": lambda q, p: {"query": q, "top_k": p.get("top_k", 5)},
                "map_response": lambda r: {
                    "result": r.get("answer", str(r.get("results", r))),
                    "confidence": r.get("confidence", 0.75),
                    "sources": r.get("sources", []),
                },
            },
        },
    },
    "mnemonic": {
        "base_url": "http://localhost:8300",
        "capabilities": {
            "memory_management": {
                "method": "POST",
                "path": "/api/memory",
                "map_request": lambda q, p: {"action": p.get("action", "search"), "query": q, **p},
                "map_response": lambda r: {
                    "result": r.get("result", str(r)),
                    "confidence": r.get("confidence", 0.9),
                },
            },
            "context_tracking": {
                "method": "POST",
                "path": "/api/context",
                "map_request": lambda q, p: {"query": q, "session_id": p.get("session_id", "default")},
                "map_response": lambda r: {
                    "result": r.get("context", str(r)),
                    "confidence": 0.95,
                },
            },
        },
    },
    "deep-research": {
        "base_url": "http://localhost:8400",
        "capabilities": {
            "deep_research": {
                "method": "POST",
                "path": "/api/research",
                "map_request": lambda q, p: {"query": q, "depth": p.get("depth", "standard")},
                "map_response": lambda r: {
                    "result": r.get("report", r.get("result", str(r))),
                    "confidence": r.get("confidence", 0.8),
                    "sources": r.get("sources", []),
                },
            },
            "fact_checking": {
                "method": "POST",
                "path": "/api/factcheck",
                "map_request": lambda q, p: {"claim": q},
                "map_response": lambda r: {
                    "result": r.get("verdict", str(r)),
                    "confidence": r.get("confidence", 0.7),
                    "sources": r.get("sources", []),
                },
            },
        },
    },
    "sentinel": {
        "base_url": "http://localhost:8500",
        "capabilities": {
            "security_analysis": {
                "method": "POST",
                "path": "/api/scan",
                "map_request": lambda q, p: {"content": q, "scan_type": p.get("scan_type", "full")},
                "map_response": lambda r: {
                    "result": r.get("report", str(r)),
                    "confidence": r.get("confidence", 0.85),
                },
            },
            "threat_detection": {
                "method": "POST",
                "path": "/api/detect",
                "map_request": lambda q, p: {"input": q},
                "map_response": lambda r: {
                    "result": r.get("threats", str(r)),
                    "confidence": r.get("confidence", 0.9),
                },
            },
        },
    },
    "costcontrol": {
        "base_url": "http://localhost:8600",
        "capabilities": {
            "cost_tracking": {
                "method": "POST",
                "path": "/api/track",
                "map_request": lambda q, p: {"query": q, **p},
                "map_response": lambda r: {
                    "result": r.get("costs", str(r)),
                    "confidence": 0.95,
                },
            },
            "budget_management": {
                "method": "POST",
                "path": "/api/budget",
                "map_request": lambda q, p: {"query": q, **p},
                "map_response": lambda r: {
                    "result": r.get("status", str(r)),
                    "confidence": 0.95,
                },
            },
        },
    },
    "safetyproxy": {
        "base_url": "http://localhost:8700",
        "capabilities": {
            "prompt_injection_detection": {
                "method": "POST",
                "path": "/api/check",
                "map_request": lambda q, p: {"text": q},
                "map_response": lambda r: {
                    "result": r.get("result", str(r)),
                    "confidence": r.get("confidence", 0.9),
                },
            },
            "pii_detection": {
                "method": "POST",
                "path": "/api/pii",
                "map_request": lambda q, p: {"text": q},
                "map_response": lambda r: {
                    "result": r.get("result", str(r)),
                    "confidence": r.get("confidence", 0.85),
                },
            },
        },
    },
    "loganalyst": {
        "base_url": "http://localhost:8800",
        "capabilities": {
            "log_analysis": {
                "method": "POST",
                "path": "/api/analyze",
                "map_request": lambda q, p: {"logs": q, "format": p.get("format", "auto")},
                "map_response": lambda r: {
                    "result": r.get("analysis", str(r)),
                    "confidence": r.get("confidence", 0.8),
                },
            },
            "error_explanation": {
                "method": "POST",
                "path": "/api/explain",
                "map_request": lambda q, p: {"error": q},
                "map_response": lambda r: {
                    "result": r.get("explanation", str(r)),
                    "confidence": r.get("confidence", 0.75),
                    "sources": r.get("sources", []),
                },
            },
        },
    },
}


async def proxy_request(
    product_name: str,
    capability: str,
    query: str,
    params: dict | None = None,
) -> dict:
    """Proxy a NexusRequest to a product's real API.

    Returns {"result": str, "confidence": float, ...}.
    """
    product = PRODUCT_APIS.get(product_name)
    if not product:
        return {"result": f"Unknown product: {product_name}", "confidence": 0.0}

    cap_config = product["capabilities"].get(capability)
    if not cap_config:
        return {"result": f"Unknown capability: {capability}", "confidence": 0.0}

    url = f"{product['base_url']}{cap_config['path']}"
    request_body = cap_config["map_request"](query, params or {})

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if cap_config["method"] == "POST":
                resp = await client.post(url, json=request_body)
            else:
                resp = await client.get(url, params=request_body)

            if resp.status_code == 200:
                data = resp.json()
                return cap_config["map_response"](data)
            else:
                return {
                    "result": f"Product returned HTTP {resp.status_code}",
                    "confidence": 0.0,
                }

    except httpx.ConnectError:
        return {
            "result": f"Cannot connect to {product_name} at {product['base_url']}",
            "confidence": 0.0,
        }
    except httpx.TimeoutException:
        return {
            "result": f"Timeout waiting for {product_name}",
            "confidence": 0.0,
        }
    except Exception as e:
        return {"result": f"Error: {e}", "confidence": 0.0}


async def check_product_health(product_name: str) -> bool:
    """Check if a product is reachable."""
    product = PRODUCT_APIS.get(product_name)
    if not product:
        return False

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{product['base_url']}/health")
            return resp.status_code == 200
    except Exception:
        return False


async def check_all_products() -> dict[str, bool]:
    """Check health of all products."""
    results = {}
    for name in PRODUCT_APIS:
        results[name] = await check_product_health(name)
    return results


# ─── CLI ─────────────────────────────────────────────────────────────────

async def main():
    """Check product health and show adapter status."""
    logger.info("Nexus Universal Adapter — checking product connectivity")
    logger.info("=" * 60)

    health = await check_all_products()
    for name, ok in health.items():
        status = "ONLINE" if ok else "OFFLINE"
        product = PRODUCT_APIS[name]
        caps = ", ".join(product["capabilities"].keys())
        logger.info(
            "  %-15s %s  %s  [%s]",
            name, status, product["base_url"], caps,
        )

    online = sum(1 for v in health.values() if v)
    logger.info("=" * 60)
    logger.info("%d/%d products online", online, len(health))

    if online == 0:
        logger.warning(
            "No products are online. Start the products first, "
            "then register them with: python -m agents.register_existing"
        )


if __name__ == "__main__":
    asyncio.run(main())
