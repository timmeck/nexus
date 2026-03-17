"""Multi-Agent Verification — Send same query to N agents, compare responses."""

from __future__ import annotations

import asyncio
import logging
import time
from difflib import SequenceMatcher

import httpx

from nexus.auth import sign_request
from nexus.models.protocol import NexusRequest
from nexus.models.verification import (
    AgentAnswer,
    VerificationRequest,
    VerificationResult,
)
from nexus.registry import service as registry
from nexus.trust import service as trust

log = logging.getLogger("nexus.verification")


async def verify(request: VerificationRequest) -> VerificationResult:
    """Send a query to multiple agents and compare their responses.

    1. Find agents with the requested capability
    2. Send the same query to all of them in parallel
    3. Compare responses and detect contradictions
    4. Return consensus score and best answer
    """
    # Find capable agents
    candidates = await registry.find_by_capability(
        capability=request.capability,
        language=request.language,
    )

    if len(candidates) < request.min_agents:
        return VerificationResult(
            query=request.query,
            capability=request.capability,
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
            agents_queried=len(candidates),
            agents_responded=len(successful),
            consensus=False,
            consensus_score=0.0,
            best_answer=successful[0].answer if successful else "No agents responded successfully",
            answers=answers,
            contradictions=["Not enough successful responses for verification"],
        )

    # Compare responses
    consensus_score, contradictions = _analyze_consensus(successful)
    consensus = consensus_score >= 0.6

    # Pick best answer: highest confidence among consensus-supporting answers
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
        "Verification complete: %d/%d responded, consensus=%.2f, contradictions=%d",
        len(successful),
        len(candidates),
        consensus_score,
        len(contradictions),
    )

    return VerificationResult(
        query=request.query,
        capability=request.capability,
        agents_queried=len(candidates),
        agents_responded=len(successful),
        consensus=consensus,
        consensus_score=round(consensus_score, 4),
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

        async with httpx.AsyncClient(timeout=30.0) as client:
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


def _analyze_consensus(answers: list[AgentAnswer]) -> tuple[float, list[str]]:
    """Analyze agreement between agent answers.

    Returns (consensus_score, contradictions).
    consensus_score: 0.0 = total disagreement, 1.0 = perfect agreement.
    """
    if len(answers) < 2:
        return 1.0, []

    texts = [a.answer.strip().lower() for a in answers]
    contradictions = []

    # Pairwise similarity using SequenceMatcher
    total_similarity = 0.0
    pairs = 0

    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            sim = SequenceMatcher(None, texts[i], texts[j]).ratio()
            total_similarity += sim
            pairs += 1

            if sim < 0.3:
                contradictions.append(f"{answers[i].agent_name} vs {answers[j].agent_name}: low similarity ({sim:.1%})")

    avg_similarity = total_similarity / pairs if pairs > 0 else 0.0

    # Weight by confidence
    total_confidence = sum(a.confidence for a in answers)
    if total_confidence > 0:
        weighted_score = sum(a.confidence / total_confidence * avg_similarity for a in answers)
    else:
        weighted_score = avg_similarity

    return weighted_score, contradictions
