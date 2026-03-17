"""Multi-Agent Verification — Send same query to N agents, compare responses.

Verification is now capability-aware: structured outputs use field-level
comparison, open-ended outputs use text similarity. The verifier is selected
based on the capability name or an explicit override.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from nexus.auth import sign_request
from nexus.models.protocol import NexusRequest
from nexus.models.verification import (
    AgentAnswer,
    Verdict,
    VerificationRequest,
    VerificationResult,
)
from nexus.registry import service as registry
from nexus.trust import service as trust
from nexus.verification.verifiers import get_verification_mode, run_verifier

log = logging.getLogger("nexus.verification")


async def verify(request: VerificationRequest) -> VerificationResult:
    """Send a query to multiple agents and compare their responses.

    1. Determine verification mode from capability (or override)
    2. Find agents with the requested capability
    3. Send the same query to all of them in parallel
    4. Run the appropriate verifier
    5. Return verdict + consensus score + best answer
    """
    # Determine verification mode
    mode = get_verification_mode(request.capability, request.verification_mode)

    # Find capable agents
    candidates = await registry.find_by_capability(
        capability=request.capability,
        language=request.language,
    )

    if len(candidates) < request.min_agents:
        return VerificationResult(
            query=request.query,
            capability=request.capability,
            verification_mode=mode,
            verdict=Verdict.INCONCLUSIVE,
            agents_queried=len(candidates),
            agents_responded=0,
            consensus=False,
            consensus_score=0.0,
            best_answer=f"Not enough agents: found {len(candidates)}, need {request.min_agents}",
            contradictions=[f"Only {len(candidates)} agents available, minimum {request.min_agents} required"],
        )

    # Send query to all agents in parallel
    answers = await _query_all_agents(candidates, request)

    successful = [a for a in answers if a.status == "completed"]

    if len(successful) < 2:
        return VerificationResult(
            query=request.query,
            capability=request.capability,
            verification_mode=mode,
            verdict=Verdict.INCONCLUSIVE,
            agents_queried=len(candidates),
            agents_responded=len(successful),
            consensus=False,
            consensus_score=0.0,
            best_answer=successful[0].answer if successful else "No agents responded successfully",
            answers=answers,
            contradictions=["Not enough successful responses for verification"],
        )

    # Run the capability-appropriate verifier
    verdict, consensus_score, contradictions = run_verifier(
        mode=mode,
        answers=successful,
        expected_schema=request.expected_schema,
    )
    consensus = verdict == Verdict.PASS

    # Pick best answer: highest confidence among successful
    best = max(successful, key=lambda a: a.confidence)

    # Record verified interactions
    for answer in successful:
        await trust.record_interaction(
            request_id=f"verify-{answer.agent_id}",
            consumer_id=request.from_agent,
            provider_id=answer.agent_id,
            success=True,
            confidence=answer.confidence,
            verified=consensus,
            response_ms=answer.processing_ms,
        )

    log.info(
        "Verification [%s/%s]: %d/%d responded, verdict=%s, score=%.2f, contradictions=%d",
        mode,
        request.capability,
        len(successful),
        len(candidates),
        verdict,
        consensus_score,
        len(contradictions),
    )

    return VerificationResult(
        query=request.query,
        capability=request.capability,
        verification_mode=mode,
        verdict=verdict,
        agents_queried=len(candidates),
        agents_responded=len(successful),
        consensus=consensus,
        consensus_score=consensus_score,
        best_answer=best.answer,
        answers=answers,
        contradictions=contradictions,
    )


async def _query_all_agents(
    agents: list,
    request: VerificationRequest,
) -> list[AgentAnswer]:
    """Send the same NexusRequest to all agents in parallel."""
    tasks = [_query_single_agent(agent, request) for agent in agents]
    return await asyncio.gather(*tasks)


async def _query_single_agent(agent, request: VerificationRequest) -> AgentAnswer:
    """Send query to a single agent and return its answer."""
    nexus_req = NexusRequest(
        from_agent=request.from_agent,
        to_agent=agent.id,
        query=request.query,
        capability=request.capability,
        language=request.language,
    )

    url = f"{agent.endpoint.rstrip('/')}/nexus/handle"
    start = time.time()

    try:
        payload_json = nexus_req.model_dump_json()

        # Sign request if agent has an API key
        headers = {"Content-Type": "application/json"}
        if hasattr(agent, "api_key") and agent.api_key:
            auth_headers = sign_request(payload_json, agent.api_key)
            headers.update(auth_headers)

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                url,
                content=payload_json,
                headers=headers,
            )

            elapsed_ms = int((time.time() - start) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                return AgentAnswer(
                    agent_id=agent.id,
                    agent_name=agent.name,
                    answer=data.get("answer", ""),
                    confidence=data.get("confidence", 0.0),
                    processing_ms=elapsed_ms,
                    status="completed",
                )
            else:
                return AgentAnswer(
                    agent_id=agent.id,
                    agent_name=agent.name,
                    answer="",
                    confidence=0.0,
                    processing_ms=elapsed_ms,
                    status="failed",
                    error=f"HTTP {resp.status_code}",
                )

    except httpx.ConnectError:
        return AgentAnswer(
            agent_id=agent.id,
            agent_name=agent.name,
            answer="",
            confidence=0.0,
            processing_ms=int((time.time() - start) * 1000),
            status="failed",
            error=f"Connection refused at {agent.endpoint}",
        )
    except httpx.TimeoutException:
        return AgentAnswer(
            agent_id=agent.id,
            agent_name=agent.name,
            answer="",
            confidence=0.0,
            processing_ms=int((time.time() - start) * 1000),
            status="timeout",
            error="Agent timed out",
        )
    except Exception as e:
        return AgentAnswer(
            agent_id=agent.id,
            agent_name=agent.name,
            answer="",
            confidence=0.0,
            processing_ms=int((time.time() - start) * 1000),
            status="failed",
            error=str(e),
        )
