"""Capability-specific verifiers.

Each verifier takes a list of successful AgentAnswers and returns
(verdict, consensus_score, contradictions).

Not one heuristic for everything. Different capabilities need different truth signals.
"""

from __future__ import annotations

import json
import logging
import re
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
    # Claim-level verification (text analysis, summarization, factual tasks)
    "text_analysis": VerificationMode.CLAIM_EXTRACTION,
    "summarization": VerificationMode.CLAIM_EXTRACTION,
    "fact_check": VerificationMode.CLAIM_EXTRACTION,
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
    if mode == VerificationMode.CLAIM_EXTRACTION:
        return verify_claims(answers)
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


# ── Claim Extraction Verifier ────────────────────────────────────
#
# Extracts factual claims from agent answers and compares them.
# Catches near-match failures that string similarity misses:
#   - wrong numbers (50M vs 35M)
#   - wrong entities (US vs EU)
#   - wrong currencies (dollars vs euros)
#   - wrong dates (June 2025 vs March 2025)


# Critical claim types — mismatch on any of these vetoes PASS
# "metadata_number" (word count, char count, etc.) is NOT critical —
# LLMs are notoriously bad at counting, so disagreement is expected noise.
CRITICAL_CLAIM_TYPES = {"substantive_number", "currency", "percentage", "date", "jurisdiction"}

# Weights for scoring: critical claims matter more, metadata less
CLAIM_WEIGHTS = {
    "substantive_number": 3.0,
    "metadata_number": 0.5,  # low weight — counting disagreements are noise
    "currency": 3.0,
    "percentage": 3.0,
    "date": 2.0,
    "jurisdiction": 2.0,
    "entity": 1.5,
    "general": 1.0,
}

# Keywords near a number that indicate it's metadata (not a substantive claim)
METADATA_NUMBER_CONTEXT = {
    "word",
    "words",
    "character",
    "characters",
    "char",
    "chars",
    "sentence",
    "sentences",
    "paragraph",
    "paragraphs",
    "page",
    "pages",
    "token",
    "tokens",
    "line",
    "lines",
    "syllable",
    "syllables",
    "reading",
}


# Word-to-number mapping for adversarial formatting defense
WORD_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

WORD_MULTIPLIERS = {
    "hundred": 100,
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}

# Minimum number of critical claims expected from a real analysis
MIN_CRITICAL_CLAIMS = 2


def _words_to_number(text: str) -> list[tuple[str, int]]:
    """Convert word numbers to integers. Returns list of (matched_span, value).

    Handles: "thirty five million", "twenty four", "eighty one", "five".
    """
    results = []
    words = re.findall(r"[a-z]+", text.lower())
    i = 0
    while i < len(words):
        w = words[i]
        if w not in WORD_NUMBERS and w not in WORD_MULTIPLIERS:
            i += 1
            continue

        # Start accumulating a number — require at least one number word
        # before accepting multipliers (prevents "million" alone -> 1000000)
        current = 0
        total = 0
        has_number_word = False
        while i < len(words):
            w = words[i]
            if w in WORD_NUMBERS:
                current += WORD_NUMBERS[w]
                has_number_word = True
                i += 1
            elif w in WORD_MULTIPLIERS and (has_number_word or current > 0):
                current *= WORD_MULTIPLIERS[w]
                if WORD_MULTIPLIERS[w] >= 1000:
                    total += current
                    current = 0
                i += 1
            elif w in WORD_MULTIPLIERS:
                # Standalone multiplier without number word — skip
                i += 1
                break
            else:
                break

        total += current
        if total > 0:
            results.append((str(total), total))

    return results


def _classify_number(text: str, match_start: int, match_end: int) -> str:
    """Classify a number as 'substantive_number' or 'metadata_number'.

    Looks at nearby words (window of ~30 chars) for metadata indicators
    like 'word', 'character', 'sentence', 'page', 'token'.
    """
    # Check window around the number match
    window_start = max(0, match_start - 30)
    window_end = min(len(text), match_end + 30)
    window = text[window_start:window_end].lower()

    # If any metadata keyword is near this number, it's metadata
    nearby_words = set(re.findall(r"[a-z]+", window))
    if nearby_words & METADATA_NUMBER_CONTEXT:
        return "metadata_number"
    return "substantive_number"


def extract_claims(text: str) -> dict[str, list[str]]:
    """Extract factual claims from text into categorized buckets.

    Returns dict of claim_type -> list of normalized values.
    """
    claims: dict[str, list[str]] = {
        "substantive_number": [],
        "metadata_number": [],
        "currency": [],
        "percentage": [],
        "date": [],
        "jurisdiction": [],
        "entity": [],
    }

    lower = text.lower()

    # Word numbers: convert "thirty five million" -> 35000000
    # Word-spelled numbers are almost always substantive (nobody writes "sixty one words")
    for _num_str, num_val in _words_to_number(lower):
        claims["substantive_number"].append(str(num_val))

    # Also extract word-based percentages: "ten percent"
    for m in re.finditer(
        r"(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)\s*(?:\s+(?:one|two|three|four|five|six|seven|eight|nine))?\s*percent",
        lower,
    ):
        word_nums = re.findall(r"[a-z]+", m.group(0).replace("percent", "").strip())
        val = sum(WORD_NUMBERS.get(w, 0) for w in word_nums)
        if val > 0:
            claims["percentage"].append(str(val))

    # Word-based dates: "march fifteenth" or ordinals
    ordinals = {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
        "sixth": 6,
        "seventh": 7,
        "eighth": 8,
        "ninth": 9,
        "tenth": 10,
        "eleventh": 11,
        "twelfth": 12,
        "thirteenth": 13,
        "fourteenth": 14,
        "fifteenth": 15,
        "sixteenth": 16,
        "seventeenth": 17,
        "eighteenth": 18,
        "nineteenth": 19,
        "twentieth": 20,
        "twenty first": 21,
        "twenty second": 22,
        "twenty third": 23,
        "twenty fourth": 24,
        "twenty fifth": 25,
        "twenty sixth": 26,
        "twenty seventh": 27,
        "twenty eighth": 28,
        "twenty ninth": 29,
        "thirtieth": 30,
        "thirty first": 31,
    }

    months_map = {
        "january": "01",
        "february": "02",
        "march": "03",
        "april": "04",
        "may": "05",
        "june": "06",
        "july": "07",
        "august": "08",
        "september": "09",
        "october": "10",
        "november": "11",
        "december": "12",
    }

    for month_name, month_num in months_map.items():
        for ord_name, ord_val in ordinals.items():
            pattern = rf"{month_name}\s+{ord_name}"
            if re.search(pattern, lower):
                # Try to find a year nearby
                year_match = re.search(rf"{pattern},?\s+(twenty\s+twenty\s+\w+|\d{{4}})", lower)
                if year_match:
                    year_text = year_match.group(1)
                    # Convert word year: "twenty twenty five" -> 2025
                    if year_text.isdigit():
                        year = year_text
                    else:
                        year_words = _words_to_number(year_text)
                        year = str(year_words[0][1]) if year_words else ""
                    if year:
                        claims["date"].append(f"{year}-{month_num}-{str(ord_val).zfill(2)}")

    # Numbers: extract quantities with context (e.g. "35 million", "35M", "81")
    # Use word boundary at start to avoid partial matches inside compounds like "24mo"
    abbreviations = {"m": "million", "b": "billion", "k": "thousand", "bn": "billion"}
    multipliers = {"million": 1_000_000, "billion": 1_000_000_000, "thousand": 1_000, "hundred": 100}

    # First handle time periods: "24 months", "24-month", "24mo"
    # Time periods are always substantive claims
    time_period_numbers: set[str] = set()  # track to avoid double-extraction
    for m in re.finditer(r"(\d+)\s*mo\b", lower):
        claims["substantive_number"].append(f"{m.group(1)}_month")
        time_period_numbers.add(m.group(1))
    for m in re.finditer(r"(\d+)[\s-]+(months?|years?|weeks?|days?)", lower):
        claims["substantive_number"].append(f"{m.group(1)}_{m.group(2).rstrip('s')}")
        time_period_numbers.add(m.group(1))

    for m in re.finditer(
        r"(?<![a-z])(\d+(?:\.\d+)?)\s*(million|billion|thousand|hundred|m|b|k|bn)?(?![a-z0-9])", lower
    ):
        value = float(m.group(1))
        raw_num = m.group(1).split(".")[0]
        unit = m.group(2) or ""
        unit = abbreviations.get(unit, unit)  # normalize abbreviations
        if unit in multipliers:
            # Numbers with multipliers (35 million, 50M) are always substantive
            value *= multipliers[unit]
            claims["substantive_number"].append(str(int(value)))
        else:
            # Skip numbers already captured as time periods
            if raw_num in time_period_numbers:
                continue
            # Classify based on nearby context
            num_type = _classify_number(lower, m.start(), m.end())
            claims[num_type].append(str(int(value)))

    # Currencies
    for m in re.finditer(r"(euros?|eur|dollars?|usd|gbp|pounds?|¥|yen|yuan)", lower):
        normalized = m.group(1)
        if normalized.startswith("euro") or normalized == "eur":
            claims["currency"].append("EUR")
        elif normalized.startswith("dollar") or normalized == "usd":
            claims["currency"].append("USD")
        elif normalized.startswith("pound") or normalized == "gbp":
            claims["currency"].append("GBP")
        else:
            claims["currency"].append(normalized.upper())

    # Percentages
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(%|percent)", lower):
        claims["percentage"].append(m.group(1))

    # Dates (various formats)
    months = {
        "january": "01",
        "february": "02",
        "march": "03",
        "april": "04",
        "may": "05",
        "june": "06",
        "july": "07",
        "august": "08",
        "september": "09",
        "october": "10",
        "november": "11",
        "december": "12",
    }
    # "March 15, 2025" or "March 15 2025"
    for m in re.finditer(
        r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})",
        lower,
    ):
        month = months[m.group(1)]
        day = m.group(2).zfill(2)
        year = m.group(3)
        claims["date"].append(f"{year}-{month}-{day}")

    # "15 March 2025" (European-style: day month year)
    for m in re.finditer(
        r"(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})",
        lower,
    ):
        day = m.group(1).zfill(2)
        month = months[m.group(2)]
        year = m.group(3)
        claims["date"].append(f"{year}-{month}-{day}")

    # Also catch "month year" without day
    for m in re.finditer(
        r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})", lower
    ):
        month = months[m.group(1)]
        year = m.group(2)
        claims["date"].append(f"{year}-{month}")

    # Time periods already extracted above (before number extraction)

    # Jurisdictions / entities — use word boundaries to avoid false matches
    # ("us" in "discusses", "eu" in "evaluated", etc.)
    jurisdiction_patterns = {
        r"\beuropean\s+union\b": "EU",
        r"\bthe\s+eu\b|\beu\s+": "EU",  # "the EU" or "EU " (with space after)
        r"\bunited\s+states\b": "US",
        r"\bthe\s+us\b|\bus\s+government\b|\bus\s+announced\b": "US",
        r"\busa\b": "US",
        r"\bunited\s+kingdom\b": "UK",
        r"\bthe\s+uk\b|\buk\s+": "UK",
        r"\beuropean\s+commission\b": "EU_COMMISSION",
    }
    for pattern, normalized in jurisdiction_patterns.items():
        if re.search(pattern, lower):
            claims["jurisdiction"].append(normalized)

    # Named entities (organizations, acts) — only extract high-level entities,
    # not minor phrasing variations that differ between honest agents
    entity_patterns = [
        (r"ai\s+act", "ai_act"),
        (r"ai\s+safety\s+act", "ai_safety_act"),
        (r"ai\s+governance", "ai_governance"),
    ]
    for pattern, label in entity_patterns:
        if re.search(pattern, lower):
            claims["entity"].append(label)

    # Deduplicate within each category
    for key in claims:
        claims[key] = sorted(set(claims[key]))

    return claims


def verify_claims(
    answers: list[AgentAnswer],
) -> tuple[Verdict, float, list[str]]:
    """Verify agent answers by extracting and comparing factual claims.

    Process:
    1. Extract claims from each answer
    2. Compare claims across agents per category
    3. Critical claim mismatches (numbers, currencies, dates) veto PASS
    4. Score based on weighted agreement across all claim types

    Verdict:
      pass:          weighted agreement >= 0.7 AND no critical mismatches
      fail:          weighted agreement < 0.3 OR critical mismatches with strong disagreement
      inconclusive:  everything else
    """
    if len(answers) < 2:
        return Verdict.INCONCLUSIVE, 1.0, ["Only one response -- cannot verify"]

    # Extract claims from all answers
    agent_claims: list[tuple[AgentAnswer, dict[str, list[str]]]] = []
    for a in answers:
        claims = extract_claims(a.answer)
        agent_claims.append((a, claims))

    contradictions: list[str] = []
    category_scores: dict[str, float] = {}
    critical_mismatch = False

    # ── Missing-claim detection ──────────────────────────────────
    # If an agent has significantly fewer critical claims than others,
    # it's likely omitting facts (Omission Attack).
    critical_counts = []
    for agent, claims in agent_claims:
        count = sum(len(claims.get(cat, [])) for cat in CRITICAL_CLAIM_TYPES)
        critical_counts.append((agent.agent_name, count))

    if critical_counts:
        max_claims = max(c for _, c in critical_counts)
        for name, count in critical_counts:
            if max_claims >= MIN_CRITICAL_CLAIMS and count < max_claims * 0.3:
                contradictions.append(
                    f"[omission] {name}: only {count} critical claims vs {max_claims} from other agents"
                )
                critical_mismatch = True

    # Compare each claim category
    all_categories = set()
    for _, claims in agent_claims:
        for cat, values in claims.items():
            if values:
                all_categories.add(cat)

    for category in all_categories:
        # Collect all values for this category across agents
        agent_values: list[tuple[str, set[str]]] = []
        for agent, claims in agent_claims:
            values = set(claims.get(category, []))
            if values:
                agent_values.append((agent.agent_name, values))

        if len(agent_values) < 2:
            # Only one agent has claims in this category -- can't compare
            continue

        # Calculate pairwise agreement (Jaccard similarity)
        total_jaccard = 0.0
        pairs = 0
        mismatched_agents: list[tuple[str, str, set[str], set[str]]] = []

        for i in range(len(agent_values)):
            for j in range(i + 1, len(agent_values)):
                name_i, vals_i = agent_values[i]
                name_j, vals_j = agent_values[j]

                intersection = vals_i & vals_j
                union = vals_i | vals_j

                jaccard = len(intersection) / len(union) if union else 1.0
                total_jaccard += jaccard
                pairs += 1

                # Track mismatches
                if jaccard < 1.0:
                    diff_i = vals_i - vals_j
                    diff_j = vals_j - vals_i
                    if diff_i or diff_j:
                        mismatched_agents.append((name_i, name_j, diff_i, diff_j))

        avg_jaccard = total_jaccard / pairs if pairs > 0 else 1.0
        category_scores[category] = avg_jaccard

        # Report mismatches
        for name_i, name_j, diff_i, diff_j in mismatched_agents:
            if diff_i or diff_j:
                details = []
                if diff_i:
                    details.append(f"{name_i} has {diff_i}")
                if diff_j:
                    details.append(f"{name_j} has {diff_j}")
                contradictions.append(f"[{category}] {name_i} vs {name_j}: {', '.join(details)}")

                # Mark critical mismatches — but only if agents actively
                # CONTRADICT each other (both have values, values differ),
                # not just if one has extra detail the other omits.
                if category in CRITICAL_CLAIM_TYPES and diff_i and diff_j:
                    # Both agents have values the other doesn't — real conflict
                    critical_mismatch = True

    # Calculate weighted score
    if not category_scores:
        if critical_mismatch:
            # Omission detected but no shared categories to compare --
            # one agent has claims, the other has none. This is a clear fail.
            contradictions.insert(0, "CRITICAL: factual claims disagree on key fields")
            return Verdict.FAIL, 0.0, contradictions
        # No extractable claims from anyone -- fall back to text similarity
        return verify_text_similarity(answers)

    total_weight = 0.0
    weighted_sum = 0.0
    for category, score in category_scores.items():
        weight = CLAIM_WEIGHTS.get(category, 1.0)
        weighted_sum += score * weight
        total_weight += weight

    final_score = weighted_sum / total_weight if total_weight > 0 else 0.0

    # Determine verdict
    if critical_mismatch:
        # Critical facts disagree -- cannot pass
        if final_score < 0.3:
            verdict = Verdict.FAIL
        else:
            verdict = Verdict.FAIL  # Critical mismatch forces FAIL even with decent score
            contradictions.insert(0, "CRITICAL: factual claims disagree on key fields")
    elif final_score >= 0.7:
        verdict = Verdict.PASS
    elif final_score < 0.3:
        verdict = Verdict.FAIL
    else:
        verdict = Verdict.INCONCLUSIVE

    # ── Semantic Tension Detection ───────────────────────────────
    # If claims match (PASS) but semantic signals diverge, downgrade to SUSPICIOUS.
    # This catches meaning swap, negation, and context shift attacks.
    if verdict == Verdict.PASS:
        tension_flags = detect_semantic_tension(answers)
        if tension_flags:
            verdict = Verdict.SUSPICIOUS
            for flag in tension_flags:
                contradictions.append(f"[semantic] {flag}")

    return verdict, round(final_score, 4), contradictions


# ── Semantic Tension Detection ────────────────────────────────────
#
# Lightweight heuristics that detect when claims match numerically
# but the surrounding language suggests different meaning.
# No LLM needed — just keyword class comparison and negation scanning.


# Semantic role classes — words that indicate fundamentally different meaning
ROLE_CLASSES: dict[str, list[str]] = {
    "penalty": ["penalty", "fine", "sanction", "punishment", "forfeiture"],
    "incentive": ["subsidy", "incentive", "grant", "reward", "bonus", "tax reduction", "tax credit"],
    "obligation": ["requirement", "obligation", "mandate", "must", "shall", "required"],
    "prohibition": ["ban", "prohibition", "forbidden", "prohibited", "excluded"],
    "limit": ["cap", "limit", "maximum", "ceiling", "threshold", "cannot exceed", "not exceed"],
}

# Negation markers
NEGATION_MARKERS = [
    r"\bnot\b",
    r"\bno\b",
    r"\bnever\b",
    r"\bcannot\b",
    r"\bcan't\b",
    r"\bwill not\b",
    r"\bwon't\b",
    r"\bdoes not\b",
    r"\bdo not\b",
    r"\bexcluded\s+from\b",
    r"\bunless\b",
    r"\bexempt\b",
]

# Key regulation/framework entities for context anchoring
REGULATION_ENTITIES = [
    (r"\bai\s+act\b", "AI_Act"),
    (r"\bai\s+safety\s+act\b", "AI_Safety_Act"),
    (r"\bdigital\s+markets?\s+act\b", "Digital_Markets_Act"),
    (r"\bdigital\s+services?\s+act\b", "Digital_Services_Act"),
    (r"\bgdpr\b", "GDPR"),
    (r"\bsoc\s*2\b", "SOC2"),
    (r"\bhipaa\b", "HIPAA"),
    (r"\bnist\b", "NIST"),
]


def detect_semantic_tension(answers: list[AgentAnswer]) -> list[str]:
    """Detect semantic tension between answers that have matching claims.

    Returns list of tension flags. Empty list = no tension detected.
    """
    if len(answers) < 2:
        return []

    texts = [a.answer.lower() for a in answers]
    names = [a.agent_name for a in answers]
    flags: list[str] = []

    # ── Heuristic 1: Trigger Word Divergence ─────────────────────
    # Check if agents use words from conflicting semantic classes
    agent_roles: list[tuple[str, set[str]]] = []
    for name, text in zip(names, texts, strict=True):
        found_roles: set[str] = set()
        for role_class, keywords in ROLE_CLASSES.items():
            for kw in keywords:
                if kw in text:
                    found_roles.add(role_class)
                    break
        agent_roles.append((name, found_roles))

    # Check for conflicting role classes between agents
    for i in range(len(agent_roles)):
        for j in range(i + 1, len(agent_roles)):
            name_i, roles_i = agent_roles[i]
            name_j, roles_j = agent_roles[j]
            # Conflicting pairs
            conflicts = [
                ("penalty", "incentive"),
                ("obligation", "prohibition"),
            ]
            for a_role, b_role in conflicts:
                if (a_role in roles_i and b_role in roles_j) or (b_role in roles_i and a_role in roles_j):
                    flags.append(f"role conflict: {name_i} uses '{a_role}' language, {name_j} uses '{b_role}' language")

    # ── Heuristic 2: Negation Surface Check ──────────────────────
    # Count negation markers per agent; significant difference = tension
    negation_counts: list[tuple[str, int]] = []
    for name, text in zip(names, texts, strict=True):
        count = sum(1 for pattern in NEGATION_MARKERS if re.search(pattern, text))
        negation_counts.append((name, count))

    if len(negation_counts) >= 2:
        counts = [c for _, c in negation_counts]
        max_neg = max(counts)
        min_neg = min(counts)
        if max_neg >= 2 and min_neg == 0:
            # One agent has significant negation, another has none
            high_neg = [n for n, c in negation_counts if c == max_neg]
            low_neg = [n for n, c in negation_counts if c == min_neg]
            flags.append(f"negation divergence: {high_neg[0]} has {max_neg} negation markers, {low_neg[0]} has none")

    # ── Heuristic 3: Entity/Regulation Anchoring ─────────────────
    # Check if agents reference different regulations/frameworks
    agent_regs: list[tuple[str, set[str]]] = []
    for name, text in zip(names, texts, strict=True):
        found_regs: set[str] = set()
        for pattern, label in REGULATION_ENTITIES:
            if re.search(pattern, text):
                found_regs.add(label)
        agent_regs.append((name, found_regs))

    # Compare: if agents reference different specific regulations
    for i in range(len(agent_regs)):
        for j in range(i + 1, len(agent_regs)):
            name_i, regs_i = agent_regs[i]
            name_j, regs_j = agent_regs[j]
            if regs_i and regs_j and regs_i != regs_j:
                flags.append(f"regulation mismatch: {name_i} references {regs_i}, {name_j} references {regs_j}")

    return flags
