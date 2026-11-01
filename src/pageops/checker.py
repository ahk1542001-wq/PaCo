"""Deterministic brand-rule checker.

Pure code, no model calls. Every rule returns pass/fail plus the offending
text quoted as evidence, so a human (or a judge) can verify each verdict
without trusting the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Claims we never publish, in any wording close to these.
BANNED_PHRASES: list[str] = [
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

# Phrases that count as a clear call to action.
CTA_MARKERS: list[str] = [
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

    # Rule 1: no banned phrases. Evidence quotes the exact phrase found.
    found = [p for p in BANNED_PHRASES if p in lowered]
    results.append(
        RuleResult(
            rule="banned_phrases",
            passed=not found,
            evidence=f"found banned phrase {_quote(found[0])}" if found else "",
        )
    )

    # Rule 2: a clear CTA must be present.
    cta_found = next((m for m in CTA_MARKERS if m in lowered), None)
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

    # Rule 4: at least one required brand hashtag must appear.
    required = brand_voice.get("required_hashtags", []) if brand_voice else []
    if required:
        tag_found = next((h for h in required if h.lower() in lowered), None)
        results.append(
            RuleResult(
                rule="required_hashtag",
                passed=tag_found is not None,
                evidence=(
                    f"required hashtag present: {tag_found}"
                    if tag_found
                    else f"none of the required hashtags {required} in draft starting {_quote(text, 60)}"
                ),
            )
        )

    return CheckResult(passed=all(r.passed for r in results), results=results)
