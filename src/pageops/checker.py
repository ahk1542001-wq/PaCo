"""Deterministic brand-rule checker.

Pure code, no model calls. Every rule returns pass/fail plus the offending
text quoted as evidence, so a human (or a judge) can verify each verdict
without trusting the model.

The rules themselves live in the brand DATA (the brand voice store):
banned phrases, CTA markers and required hashtags are read from the
brand dict on every call, so editing the brand data changes the
verdicts. The lists below are fallback defaults for stores that
predate those data keys. Platform length caps stay in code: they
are platform facts, not brand rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Fallback defaults, used only when the brand data has no list.
DEFAULT_BANNED_PHRASES: list[str] = [
    "guaranteed income",
    "guarantee income",
    "get rich",
    "get-rich",
    "100% profit",
    "make money fast",
    "risk-free income",
]

# Simple per-platform caption length caps, in characters.
PLATFORM_LIMITS: dict[str, int] = {
    "facebook": 2000,
    "instagram": 2200,
    "tiktok": 2200,
    "linkedin": 3000,
}

# Fallback defaults, used only when the brand data has no list.
DEFAULT_CTA_MARKERS: list[str] = [
    "message us",
    "send us a message",
    "dm us",
    "contact us",
    "get started",
    "book a",
    "book your",
    "learn more",
    "sign up",
    "call us",
    "chat with us",
]


@dataclass
class RuleResult:
    rule: str
    passed: bool
    evidence: str = ""


@dataclass
class CheckResult:
    passed: bool
    results: list[RuleResult] = field(default_factory=list)

    def summary(self) -> str:
        lines = []
        for r in self.results:
            mark = "PASS" if r.passed else "FAIL"
            line = f"[{mark}] {r.rule}"
            if r.evidence:
                line += f" - evidence: {r.evidence}"
            lines.append(line)
        return "\n".join(lines)


def _quote(text: str, limit: int = 120) -> str:
    snippet = " ".join(text.split())
    if len(snippet) > limit:
        snippet = snippet[:limit] + "..."
    return f'"{snippet}"'


def check_draft(text: str, platform: str, brand_voice: dict) -> CheckResult:
    """Run every brand rule against one draft caption."""
    lowered = text.lower()
    results: list[RuleResult] = []

    # Rule 1: no banned phrases (from the brand data). Evidence
    # quotes the exact phrase found.
    # Presence semantics: a brand dict that carries the key (even an
    # empty list) is authoritative; the defaults protect brand dicts
    # that predate the key. get_brand_voice omits blank keys, so a
    # legacy store can never switch protection off by accident.
    banned = (brand_voice or {}).get("banned_phrases")
    if banned is None:
        banned = DEFAULT_BANNED_PHRASES
    found = [p for p in banned if p.lower() in lowered]
    results.append(
        RuleResult(
            rule="banned_phrases",
            passed=not found,
            evidence=f"found banned phrase {_quote(found[0])}" if found else "",
        )
    )

    # Rule 2: a clear CTA must be present (markers from the brand data).
    markers = (brand_voice or {}).get("cta_markers")
    if markers is None:
        markers = DEFAULT_CTA_MARKERS
    cta_found = next((m for m in markers if m.lower() in lowered), None)
    results.append(
        RuleResult(
            rule="cta_present",
            passed=cta_found is not None,
            evidence=(
                f"CTA found: {_quote(cta_found)}"
                if cta_found
                else f"no CTA phrase in draft starting {_quote(text, 60)}"
            ),
        )
    )

    # Rule 3: platform length cap.
    limit = PLATFORM_LIMITS.get(platform.lower())
    if limit is None:
        results.append(
            RuleResult(rule="length_limit", passed=False, evidence=f"unknown platform {_quote(platform)}")
        )
    else:
        over = len(text) - limit
        results.append(
            RuleResult(
                rule="length_limit",
                passed=over <= 0,
                evidence=(
                    f"{len(text)} chars within {limit} cap"
                    if over <= 0
                    else f"{len(text)} chars exceeds {limit} cap by {over}; overflow starts {_quote(text[limit:limit + 60])}"
                ),
            )
        )

    # Rule 4: ALL required brand hashtags must appear; the evidence
    # names the ones that are missing.
    required = brand_voice.get("required_hashtags", []) if brand_voice else []
    if required:
        missing = [h for h in required if h.lower() not in lowered]
        results.append(
            RuleResult(
                rule="required_hashtag",
                passed=not missing,
                evidence=(
                    f"all required hashtags present: {', '.join(required)}"
                    if not missing
                    else f"missing required hashtags: {', '.join(missing)}"
                ),
            )
        )

    return CheckResult(passed=all(r.passed for r in results), results=results)


def check_character(row: dict, manifest: dict, brand_voice: dict) -> CheckResult:
    """Deterministic check for the brand character (mascot) badge.

    A row requests the character with character == "yes". The badge
    counts only when the Designer composited it from the brand's own
    reference image: the manifest must record the use, and the
    recorded reference must equal the brand-assets layer's value.
    Anything else fails with the gap named as evidence, so a missing
    or substituted reference can never slip through silently.
    """
    if str(row.get("character") or "").strip().lower() != "yes":
        return CheckResult(
            passed=True,
            results=[
                RuleResult(
                    rule="character",
                    passed=True,
                    evidence="character not required for this post",
                )
            ],
        )
    expected = (brand_voice or {}).get("character_image", "")
    char = (manifest or {}).get("character") or {}
    if char.get("used") is True and expected and char.get("reference", "") == expected:
        return CheckResult(
            passed=True,
            results=[
                RuleResult(
                    rule="character",
                    passed=True,
                    evidence=f"badge composited from brand reference {_quote(expected)}",
                )
            ],
        )
    if char.get("used") is True:
        evidence = (
            f"character reference mismatch: manifest used "
            f"{_quote(char.get('reference', ''))} but the brand reference is {_quote(expected)}"
        )
    else:
        reason = char.get("reason", "badge not used")
        evidence = (
            f"character requested but not used: {reason}; "
            f"brand reference is {_quote(expected)}"
        )
    return CheckResult(
        passed=False,
        results=[RuleResult(rule="character", passed=False, evidence=evidence)],
    )
