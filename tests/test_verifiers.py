"""Tests for capability-specific verifiers."""

from __future__ import annotations

import json

from nexus.models.verification import AgentAnswer, Verdict, VerificationMode
from nexus.verification.verifiers import (
    get_verification_mode,
    run_verifier,
    verify_structured,
    verify_text_similarity,
)


def _answer(name: str, text: str, confidence: float = 0.8) -> AgentAnswer:
    return AgentAnswer(
        agent_id=f"id-{name}",
        agent_name=name,
        answer=text,
        confidence=confidence,
        processing_ms=100,
        status="completed",
    )


# ── Verification Mode Registry ──────────────────────────────


def test_mode_default_is_text_similarity():
    assert get_verification_mode("general_chat") == VerificationMode.TEXT_SIMILARITY


def test_mode_structured_capability():
    assert get_verification_mode("json_transform") == VerificationMode.STRUCTURED
    assert get_verification_mode("classification") == VerificationMode.STRUCTURED


def test_mode_override():
    assert get_verification_mode("general_chat", VerificationMode.STRUCTURED) == VerificationMode.STRUCTURED


# ── Text Similarity Verifier ────────────────────────────────


def test_text_similar_answers_pass():
    answers = [
        _answer("a1", "The capital of France is Paris."),
        _answer("a2", "Paris is the capital of France."),
        _answer("a3", "France's capital city is Paris."),
    ]
    verdict, score, contras = verify_text_similarity(answers)
    assert verdict == Verdict.PASS
    assert score >= 0.5
    assert len(contras) == 0


def test_text_contradicting_answers():
    answers = [
        _answer("a1", "The answer is definitely yes, absolutely correct."),
        _answer("a2", "No, that is completely wrong and false."),
    ]
    verdict, _score, _contras = verify_text_similarity(answers)
    assert verdict in (Verdict.FAIL, Verdict.INCONCLUSIVE)


def test_text_single_answer_inconclusive():
    answers = [_answer("a1", "Only one answer")]
    verdict, _score, _contras = verify_text_similarity(answers)
    assert verdict == Verdict.INCONCLUSIVE


# ── Structured Verifier ─────────────────────────────────────


def test_structured_matching_json():
    data = json.dumps({"name": "Paris", "country": "France", "population": 2161000})
    answers = [
        _answer("a1", data),
        _answer("a2", data),
        _answer("a3", data),
    ]
    verdict, score, _contras = verify_structured(answers)
    assert verdict == Verdict.PASS
    assert score >= 0.7


def test_structured_disagreeing_json():
    answers = [
        _answer("a1", json.dumps({"name": "Paris", "country": "France"})),
        _answer("a2", json.dumps({"name": "London", "country": "UK"})),
        _answer("a3", json.dumps({"name": "Berlin", "country": "Germany"})),
    ]
    verdict, score, _contras = verify_structured(answers)
    assert verdict in (Verdict.FAIL, Verdict.INCONCLUSIVE)
    assert score < 0.7


def test_structured_invalid_json_fails():
    answers = [
        _answer("a1", "not json at all"),
        _answer("a2", "also not json"),
        _answer("a3", "nope"),
    ]
    verdict, _score, contras = verify_structured(answers)
    assert verdict == Verdict.FAIL
    assert any("not valid JSON" in c for c in contras)


def test_structured_with_schema_checks_required_keys():
    schema = {"required": ["name", "country"]}
    answers = [
        _answer("a1", json.dumps({"name": "Paris"})),  # missing country
        _answer("a2", json.dumps({"name": "Paris", "country": "France"})),
    ]
    _verdict, _score, contras = verify_structured(answers, expected_schema=schema)
    assert any("missing required keys" in c for c in contras)


def test_structured_partial_agreement():
    answers = [
        _answer("a1", json.dumps({"name": "Paris", "country": "France", "type": "city"})),
        _answer("a2", json.dumps({"name": "Paris", "country": "France", "type": "capital"})),
    ]
    _verdict, score, _contras = verify_structured(answers)
    # name + country agree (2/3), type disagrees (1/3)
    assert score > 0.5


# ── Dispatcher ──────────────────────────────────────────────


def test_run_verifier_dispatches_text():
    answers = [
        _answer("a1", "Same answer"),
        _answer("a2", "Same answer"),
    ]
    verdict, _score, _ = run_verifier(VerificationMode.TEXT_SIMILARITY, answers)
    assert verdict == Verdict.PASS


def test_run_verifier_dispatches_structured():
    data = json.dumps({"x": 1})
    answers = [
        _answer("a1", data),
        _answer("a2", data),
    ]
    verdict, _score, _ = run_verifier(VerificationMode.STRUCTURED, answers)
    assert verdict == Verdict.PASS
