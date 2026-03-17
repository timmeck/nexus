"""Capability-specific verifiers.

Each verifier takes a list of successful AgentAnswers and returns
(verdict, consensus_score, contradictions).

Not one heuristic for everything. Different capabilities need different truth signals.
"""

from __future__ import annotations

import json
import logging
from difflib import SequenceMatcher

from nexus.models.verification import AgentAnswer, Verdict, VerificationMode

log = logging.getLogger("nexus.verification")

# ── Verifier Registry ───────────────────────────────────────────

# Maps capability names to their verification mode.
# Capabilities not listed here default to TEXT_SIMILARITY.
CAPABILITY_MODES: dict[str, VerificationMode] = {
    # Structured output capabilities
    "json_transform": VerificationMode.STRUCTURED,
    "data_extraction": VerificationMode.STRUCTURED,
    "schema_generation": VerificationMode.STRUCTURED,
    "classification": VerificationMode.STRUCTURED,
    "entity_extraction": VerificationMode.STRUCTURED,
}


def get_verification_mode(
    capability: str,
    override: VerificationMode | None = None,
) -> VerificationMode:
    """Determine verification mode for a capability.

    Priority: explicit override > capability registry > default (text_similarity).
    """
    if override is not None:
        return override
    return CAPABILITY_MODES.get(capability, VerificationMode.TEXT_SIMILARITY)


def run_verifier(
    mode: VerificationMode,
    answers: list[AgentAnswer],
    expected_schema: dict | None = None,
) -> tuple[Verdict, float, list[str]]:
    """Dispatch to the right verifier based on mode.

    Returns (verdict, consensus_score, contradictions).
    """
    if mode == VerificationMode.STRUCTURED:
        return verify_structured(answers, expected_schema)
    return verify_text_similarity(answers)


# ── Text Similarity Verifier ───────────────────────────────────


def verify_text_similarity(
    answers: list[AgentAnswer],
) -> tuple[Verdict, float, list[str]]:
    """Generic verification via pairwise text similarity.

    Uses SequenceMatcher. Consensus at >= 0.6, contradiction at < 0.3.
    Verdict:
      pass:          consensus_score >= 0.6
      fail:          consensus_score < 0.3 (strong disagreement)
      inconclusive:  0.3 <= consensus_score < 0.6
    """
    if len(answers) < 2:
        return Verdict.INCONCLUSIVE, 1.0, ["Only one response — cannot verify"]

    texts = [a.answer.strip().lower() for a in answers]
    contradictions: list[str] = []

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

    # Determine verdict
    if weighted_score >= 0.6:
        verdict = Verdict.PASS
    elif weighted_score < 0.3:
        verdict = Verdict.FAIL
    else:
        verdict = Verdict.INCONCLUSIVE

    return verdict, round(weighted_score, 4), contradictions


# ── Structured Output Verifier ─────────────────────────────────


def verify_structured(
    answers: list[AgentAnswer],
    expected_schema: dict | None = None,
) -> tuple[Verdict, float, list[str]]:
    """Verify structured (JSON) outputs by comparing parsed fields.

    Checks:
    1. All answers parse as valid JSON
    2. If expected_schema provided, all required keys are present
    3. Key-value agreement across agents (exact match on primitive values)

    Verdict:
      pass:          >= 70% field agreement across agents
      fail:          < 30% field agreement or most answers not valid JSON
      inconclusive:  30-70% agreement
    """
    if len(answers) < 2:
        return Verdict.INCONCLUSIVE, 1.0, ["Only one response — cannot verify"]

    parsed: list[tuple[AgentAnswer, dict]] = []
    contradictions: list[str] = []

    for a in answers:
        try:
            data = json.loads(a.answer)
            if isinstance(data, dict):
                parsed.append((a, data))
            else:
                contradictions.append(f"{a.agent_name}: response is not a JSON object")
        except (json.JSONDecodeError, TypeError):
            contradictions.append(f"{a.agent_name}: response is not valid JSON")

    # If most answers aren't valid JSON, fail
    if len(parsed) < 2:
        return Verdict.FAIL, 0.0, contradictions

    # Check required keys from schema
    if expected_schema and "required" in expected_schema:
        required_keys = set(expected_schema["required"])
        for agent, data in parsed:
            missing = required_keys - set(data.keys())
            if missing:
                contradictions.append(f"{agent.agent_name}: missing required keys {missing}")

    # Compare field values across all parsed answers
    all_keys: set[str] = set()
    for _, data in parsed:
        all_keys.update(data.keys())

    if not all_keys:
        return Verdict.INCONCLUSIVE, 0.5, contradictions

    agreed_keys = 0
    total_keys = len(all_keys)

    for key in all_keys:
        values = []
        for _, data in parsed:
            if key in data:
                values.append(_normalize_value(data[key]))

        if len(values) >= 2:
            # Check if majority agrees
            from collections import Counter

            counts = Counter(values)
            most_common_count = counts.most_common(1)[0][1]
            if most_common_count >= len(values) * 0.5:
                agreed_keys += 1
            else:
                # Find disagreeing agents
                for agent, data in parsed:
                    if key in data:
                        v = _normalize_value(data[key])
                        if v != counts.most_common(1)[0][0]:
                            contradictions.append(f"{agent.agent_name}: '{key}' disagrees with majority")
                            break

    agreement_ratio = agreed_keys / total_keys if total_keys > 0 else 0.0

    if agreement_ratio >= 0.7:
        verdict = Verdict.PASS
    elif agreement_ratio < 0.3:
        verdict = Verdict.FAIL
    else:
        verdict = Verdict.INCONCLUSIVE

    return verdict, round(agreement_ratio, 4), contradictions


def _normalize_value(v: object) -> str:
    """Normalize a value for comparison."""
    if isinstance(v, str):
        return v.strip().lower()
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(v, sort_keys=True, default=str)
