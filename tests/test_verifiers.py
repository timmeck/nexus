"""Tests for capability-specific verifiers."""

from __future__ import annotations

import json

from nexus.models.verification import AgentAnswer, Verdict, VerificationMode
from nexus.verification.verifiers import (
    extract_claims,
    get_verification_mode,
    run_verifier,
    verify_claims,
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


def test_run_verifier_dispatches_claims():
    answers = [
        _answer("a1", "The EU announced 35 million euros penalty on March 15, 2025."),
        _answer("a2", "On March 15, 2025, the EU set a 35 million euro penalty."),
    ]
    verdict, _score, _ = run_verifier(VerificationMode.CLAIM_EXTRACTION, answers)
    assert verdict == Verdict.PASS


# ── Claim Extraction ──────────────────────────────────────────


def test_extract_numbers():
    claims = extract_claims("The text has 72 words and 456 characters.")
    assert "72" in claims["metadata_number"]  # near "words" -> metadata
    assert "456" in claims["metadata_number"]  # near "characters" -> metadata


def test_extract_millions():
    claims = extract_claims("Penalty up to 35 million euros.")
    assert "35000000" in claims["substantive_number"]
    assert "EUR" in claims["currency"]


def test_extract_millions_abbreviated():
    claims = extract_claims("Penalty: EUR 35M.")
    assert "35000000" in claims["substantive_number"]


def test_extract_percentages():
    claims = extract_claims("7% of global turnover.")
    assert "7" in claims["percentage"]


def test_extract_dates():
    claims = extract_claims("Announced on March 15, 2025.")
    assert "2025-03-15" in claims["date"]


def test_extract_dates_european():
    claims = extract_claims("Published on 15 March 2025.")
    assert "2025-03-15" in claims["date"]


def test_extract_jurisdiction_eu():
    claims = extract_claims("The European Union announced new rules.")
    assert "EU" in claims["jurisdiction"]


def test_extract_jurisdiction_no_false_match():
    """'us' inside words like 'discusses' should NOT match US."""
    claims = extract_claims("The committee discusses various proposals.")
    assert "US" not in claims["jurisdiction"]


def test_extract_time_periods():
    claims = extract_claims("Companies have 24 months to comply.")
    assert "24_month" in claims["substantive_number"]


def test_extract_time_periods_hyphenated():
    claims = extract_claims("A 24-month compliance window.")
    assert "24_month" in claims["substantive_number"]


def test_extract_time_periods_abbreviated():
    claims = extract_claims("24mo deadline.")
    assert "24_month" in claims["substantive_number"]


def test_extract_no_double_count_time_periods():
    """24 from '24 months' should not appear as standalone number."""
    claims = extract_claims("Companies have 24 months to comply.")
    sub = claims["substantive_number"]
    meta = claims["metadata_number"]
    assert "24_month" in sub
    assert "24" not in sub and "24" not in meta


def test_extract_word_numbers():
    claims = extract_claims("Penalty up to thirty five million euros.")
    assert "35000000" in claims["substantive_number"]


def test_extract_word_percentages():
    claims = extract_claims("ten percent of global turnover.")
    assert "10" in claims["percentage"]


def test_extract_standalone_multiplier_ignored():
    """'million' alone (without number) should not extract as 1000000."""
    claims = extract_claims("The million dollar question remains.")
    assert "1000000" not in claims["substantive_number"]
    assert "1000000" not in claims["metadata_number"]


def test_extract_number_categorization():
    """Numbers near 'word/character/sentence' are metadata, others substantive."""
    claims = extract_claims(
        "Word count: 72 words. Character count: 456. Penalty: 35 million euros. Deadline: 24 months."
    )
    assert "72" in claims["metadata_number"]
    assert "456" in claims["metadata_number"]
    assert "35000000" in claims["substantive_number"]
    assert "24_month" in claims["substantive_number"]


def test_extract_entities():
    claims = extract_claims("The AI Act requires compliance.")
    assert "ai_act" in claims["entity"]


# ── Claim Verification ────────────────────────────────────────


def test_claims_matching_answers_pass():
    answers = [
        _answer("a1", "The EU announced 35 million euros penalty on March 15, 2025. 7% of turnover."),
        _answer("a2", "On March 15, 2025, the EU set a 35 million euro fine. 7% of revenue."),
    ]
    verdict, score, _contras = verify_claims(answers)
    assert verdict == Verdict.PASS
    assert score >= 0.7


def test_claims_wrong_numbers_fail():
    answers = [
        _answer("a1", "Penalty up to 35 million euros or 7% of turnover."),
        _answer("a2", "Penalty up to 50 million euros or 10% of turnover."),
    ]
    verdict, _score, contras = verify_claims(answers)
    assert verdict == Verdict.FAIL
    assert any("CRITICAL" in c for c in contras)


def test_claims_wrong_jurisdiction_fail():
    answers = [
        _answer("a1", "The European Union announced new rules."),
        _answer("a2", "The United States announced new rules."),
    ]
    verdict, _score, _contras = verify_claims(answers)
    assert verdict == Verdict.FAIL


def test_claims_wrong_currency_fail():
    answers = [
        _answer("a1", "Penalty of 35 million euros."),
        _answer("a2", "Penalty of 35 million dollars."),
    ]
    verdict, _score, _contras = verify_claims(answers)
    assert verdict == Verdict.FAIL


def test_claims_omission_detected():
    answers = [
        _answer(
            "a1", "The EU announced 35 million euros penalty on March 15, 2025. 24 months to comply. 7% of turnover."
        ),
        _answer("a2", "Regulations were announced regarding AI compliance."),
    ]
    verdict, _score, contras = verify_claims(answers)
    assert verdict in (Verdict.FAIL, Verdict.INCONCLUSIVE)  # critical mismatch, not PASS
    assert verdict != Verdict.PASS
    assert any("omission" in c for c in contras)


def test_claims_single_answer_inconclusive():
    answers = [_answer("a1", "The EU set a 35 million euro penalty.")]
    verdict, _score, _contras = verify_claims(answers)
    assert verdict == Verdict.INCONCLUSIVE


def test_claims_shared_hallucination_passes():
    """Known limitation: if all agents agree on the same wrong fact, Nexus says PASS.
    This is by design — Nexus measures consistency, not ground truth."""
    answers = [
        _answer(
            "a1", "The EU announced 50 million euros penalty on June 1, 2025. 12 months to comply. 10% of turnover."
        ),
        _answer("a2", "On June 1, 2025, the EU set a 50 million euro fine. 10% of revenue. 12-month deadline."),
    ]
    verdict, score, _contras = verify_claims(answers)
    # All agents agree on the same (wrong) facts → PASS
    # This is the honest limit of consensus-based verification
    assert verdict == Verdict.PASS
    assert score >= 0.7


def test_claims_metadata_number_mismatch_passes():
    """When agents agree on substantive facts but differ on word counts,
    the metadata mismatch should NOT trigger FAIL (LLMs count poorly)."""
    answers = [
        _answer(
            "a1",
            "The EU announced the AI Act on March 15, 2025. 35 million euros penalty. 7% of turnover. The text has 72 words.",
        ),
        _answer(
            "a2",
            "The EU released the AI Act on March 15, 2025. 35 million euros fine. 7% of turnover. The text has 85 words.",
        ),
    ]
    verdict, _score, _contras = verify_claims(answers)
    # 72 vs 85 words is metadata — substantive claims all match → PASS
    assert verdict == Verdict.PASS


def test_claims_different_style_same_facts_pass():
    answers = [
        _answer(
            "a1",
            "Word count: 72. Character count: 456. The EU announced the AI Act on March 15, 2025. Penalty: 35 million euros, 7% of turnover. 24 months to comply.",
        ),
        _answer(
            "a2",
            "I found 72 words and 456 characters. The European Union released the AI Act (March 15, 2025). Companies face a 24-month deadline with fines up to 35 million euros or 7% of revenue.",
        ),
    ]
    verdict, _score, _contras = verify_claims(answers)
    assert verdict == Verdict.PASS
