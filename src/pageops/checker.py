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

import re

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
    "threads": 500,
    "x": 280,
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


def trim_to_cap(text: str, cap: int, protected_markers=()) -> str:
    """Deterministically trim a caption to the cap, in code.

    Model shortening cannot be trusted to converge: Muse Wonder
    under-counts Burmese codepoints and trims only a few percent
    per pass (measured live 2026-11-04: 2,490 -> 2,380 -> 2,387).
    This fallback drops whole middle sentences, longest first,
    until the text is under the cap. The opening unit (the hook),
    any unit carrying a protected marker (the CTA) and any unit
    with a hashtag are never dropped, and a sentence is never cut
    in half, so what remains is complete, connected sentences.
    Returns the text unchanged when no safe trim exists.
    """
    if len(text) <= cap:
        return text
    parts = re.split(r"([။၊]\s*|\.\s+|!\s+|\?\s+|\n+)", text)
    units = []  # (body, separator_after)
    for i in range(0, len(parts), 2):
        body = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        if body or sep:
            units.append([body, sep])
    if len(units) <= 1:
        return text
    markers = [str(m).lower() for m in (protected_markers or ())]

    def protected(idx):
        body = units[idx][0].lower()
        return idx == 0 or "#" in body or any(m in body for m in markers if m)

    def total():
        return sum(len(b) + len(sep) for b, sep in units)

    while total() > cap:
        droppable = [i for i in range(len(units)) if not protected(i)]
        if not droppable:
            break
        victim = max(droppable, key=lambda i: len(units[i][0]) + len(units[i][1]))
        units.pop(victim)
    out = "".join(b + sep for b, sep in units).strip()
    return out if len(out) < len(text) else text


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

    # Rule 5: caption depth, only when the brand data opts in by
    # setting min_caption_chars. A caption below the floor is an
    # information stub: it cannot carry who the brand is, the
    # pain, how it works and what the CTA gives. The floor lives
    # in the brand data so short-form brands are never forced.
    floor = 0
    raw_floor = (brand_voice or {}).get("min_caption_chars")
    if raw_floor is not None:
        try:
            floor = int(raw_floor)
        except (TypeError, ValueError):
            floor = 0
    if floor > 0:
        results.append(
            RuleResult(
                rule="caption_depth",
                passed=len(text) >= floor,
                evidence=(
                    f"{len(text)} chars meets the {floor} char depth floor"
                    if len(text) >= floor
                    else f"{len(text)} chars is below the {floor} char depth floor; "
                    f"draft starts {_quote(text, 60)}"
                ),
            )
        )
        # Rule 6 (under the same opt-in): the brand must be named,
        # so a first-time reader knows whose post this is.
        brand_name = str((brand_voice or {}).get("brand_name") or "").strip()
        if brand_name:
            results.append(
                RuleResult(
                    rule="brand_named",
                    passed=brand_name.lower() in lowered,
                    evidence=(
                        f"brand named: {_quote(brand_name)}"
                        if brand_name.lower() in lowered
                        else f"brand name {_quote(brand_name)} never appears in the draft"
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
