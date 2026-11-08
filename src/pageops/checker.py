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
import unicodedata

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

# Scripts recognised by the first word of a character's Unicode
# name (unicodedata.name). Only letter and mark characters carry
# a script at all; digits, punctuation, symbols, emoji and
# whitespace never do, so they can never fail the script rule.
_KNOWN_SCRIPTS: set[str] = {
    "ADLAM", "ARABIC", "ARMENIAN", "AVESTAN", "BALINESE", "BAMUM",
    "BASSA", "BATAK", "BENGALI", "BOPOMOFO", "BRAHMI", "BUHID",
    "CANADIAN", "CARIAN", "CHAM", "CHEROKEE", "CHORASMIAN", "CJK",
    "COPTIC", "CUNEIFORM", "CYPRIOT", "CYRILLIC", "DESERET",
    "DEVANAGARI", "EGYPTIAN", "ELBASAN", "ETHIOPIC", "GEORGIAN",
    "GLAGOLITIC", "GOTHIC", "GRANTHA", "GREEK", "GUJARATI",
    "GUNJALA", "GURMUKHI", "HAN", "HANGUL", "HANIFI", "HANUNOO",
    "HATRAN", "HEBREW", "HIRAGANA", "IMPERIAL", "INDUS", "JAVANESE",
    "KAITHI", "KANNADA", "KATAKANA", "KAWI", "KAYAH", "KHAROSHTHI",
    "KHITAN", "KHMER", "KHOJKI", "KHUDAWADI", "LAO", "LATIN",
    "LEPCHA", "LIMBU", "LINEAR", "LISU", "LYCIAN", "LYDIAN",
    "MAHAJANI", "MAKASAR", "MALAYALAM", "MANDAIC", "MANICHAEAN",
    "MARCHEN", "MASARAM", "MAYAN", "MEDEFAIDRIN", "MEETEI",
    "MENDE", "MEROITIC", "MIAO", "MODI", "MONGOLIAN", "MRO",
    "MULTANI", "MYANMAR", "NABATAEAN", "NANDINAGARI",
    "NEWA", "NKO", "NUSHU", "OGHAM", "ORIYA",
    "OSAGE", "OSMANYA", "PAHLAVI", "PALMYRENE", "PAU", "PHAGS",
    "PHAISTOS", "PHOENICIAN", "PSALTER", "REJANG", "RUNIC",
    "SAMARITAN", "SAURASHTRA", "SHARADA", "SHAVIAN", "SIDDHAM",
    "SIGNWRITING", "SINHALA", "SOGDIAN", "SORA", "SOYOMBO",
    "SUNDANESE", "SYLOTI", "SYRIAC", "TAGALOG", "TAGBANWA",
    "TAI", "TAKRI", "TAMIL", "TANGSA", "TANGUT",
    "TELUGU", "THAANA", "THAI", "TIBETAN", "TIFINAGH",
    "TIRHUTA", "TOTO", "UGARITIC", "VAI", "VITHKUQI", "WANCHO",
    "WARANG", "YI", "YIDDISH", "ZANABAZAR",
}
# Brand-facing aliases for script names a brand would write.
_SCRIPT_ALIASES: dict[str, str] = {
    "CHINESE": "CJK",
    "JAPANESE": "CJK",
    "KOREAN": "HANGUL",
    "BURMESE": "MYANMAR",
}
# Scripts every brand may use without opting in: the caption
# language (Myanmar) and Latin (brand names, hashtags, URLs).
_DEFAULT_ALLOWED_SCRIPTS: set[str] = {"LATIN", "MYANMAR"}


def _char_script(ch: str) -> str | None:
    """The script of one character, or None when it has none.

    Only letters and marks carry a script; a combining mark named
    for its shape rather than a script (COMBINING GRAVE ACCENT)
    resolves to None and is allowed.
    """
    if unicodedata.category(ch)[0] not in ("L", "M"):
        return None
    name = unicodedata.name(ch, "")
    if not name:
        return None
    first = name.split(" ", 1)[0]
    return first if first in _KNOWN_SCRIPTS else None


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


def _split_units(text: str) -> list[list[str]]:
    """Split a caption into [body, separator_after] sentence units.

    The same split drives the sentence trim and the protected-
    overflow analysis, so both always agree on what a sentence is.
    """
    parts = re.split(r"([။၊]\s*|\.\s+|!\s+|\?\s+|\n+)", text)
    units = []
    for i in range(0, len(parts), 2):
        body = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        if body or sep:
            units.append([body, sep])
    return units


def trim_to_cap(text: str, cap: int, protected_markers=(), protected_tokens=()) -> str:
    """Deterministically trim a caption to the cap, in code.

    Model shortening cannot be trusted to converge: Muse Wonder
    under-counts Burmese codepoints and trims only a few percent
    per pass (measured live 2026-11-04: 2,490 -> 2,380 -> 2,387).
    This fallback drops whole middle sentences, longest first,
    until the text is under the cap. The opening unit (the hook),
    any unit carrying a protected marker (the CTA) and any unit
    with a hashtag are never dropped. A unit carrying a protected
    token (the brand name, a required hashtag as a whole string)
    is dropped only when every token it carries still appears in
    another remaining unit, so the trim can never remove the
    brand name or a required hashtag from the text -- the failure
    where trimming to length silently broke brand_named. A
    sentence is never cut in half, so what remains is complete,
    connected sentences. Returns the text unchanged when no safe
    trim exists.
    """
    if len(text) <= cap:
        return text
    units = _split_units(text)
    if len(units) <= 1:
        return text
    markers = [str(m).lower() for m in (protected_markers or ())]
    tokens = [str(t).lower() for t in (protected_tokens or ()) if str(t).strip()]

    def token_guarded(idx):
        body = units[idx][0].lower()
        carried = [t for t in tokens if t in body]
        if not carried:
            return False
        others = " ".join(u[0].lower() for j, u in enumerate(units) if j != idx)
        return not all(t in others for t in carried)

    def protected(idx):
        body = units[idx][0].lower()
        return (
            idx == 0
            or "#" in body
            or any(m in body for m in markers if m)
            or token_guarded(idx)
        )

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


def _protected_overflow_note(text: str, cap: int, brand_voice: dict) -> str:
    """Name the protected elements that make an over-cap draft
    untrimmable, or "" when a sentence trim could fit it.

    Builds the protected core the trim cannot go below: the
    opening sentence and every sentence carrying a hashtag or a
    CTA marker are always kept, and any protected token (the
    brand name, each required hashtag) not already in that set
    adds its SHORTEST carrier -- redundant carriers can be
    dropped, so they do not count. When that core alone exceeds
    the cap, no trim can save the draft, and the length evidence
    names the blocking elements instead of failing unexplained
    (the archived X-variant shape: hook + brand sentence + CTA
    and hashtag sentence, all protected, total over the 280 cap).
    """
    brand = brand_voice or {}
    brand_name = str(brand.get("brand_name") or "").strip()
    hashtags = [str(h) for h in (brand.get("required_hashtags") or [])]
    markers = brand.get("cta_markers")
    if markers is None:
        markers = DEFAULT_CTA_MARKERS
    units = _split_units(text)
    if len(units) <= 1:
        return ""

    def carries(idx: int, needle: str) -> bool:
        return needle.lower() in units[idx][0].lower()

    core: set[int] = {0}
    for i, (body, _sep) in enumerate(units):
        low = body.lower()
        if "#" in body or any(
            str(m).lower() in low for m in markers if str(m).strip()
        ):
            core.add(i)
    tokens = ([brand_name] if brand_name else []) + hashtags
    for token in tokens:
        if token and not any(carries(i, token) for i in core):
            hits = [i for i in range(len(units)) if carries(i, token)]
            if hits:
                core.add(
                    min(hits, key=lambda i: len(units[i][0]) + len(units[i][1]))
                )
    total = sum(len(units[i][0]) + len(units[i][1]) for i in core)
    if total <= cap:
        return ""
    blockers = ["the opening sentence"]
    if brand_name and any(carries(i, brand_name) for i in core):
        blockers.append(f"the brand name {_quote(brand_name)}")
    if hashtags and any(carries(i, tag) for i in core for tag in hashtags):
        blockers.append(f"required hashtags {', '.join(hashtags)}")
    cta_found = next(
        (str(m) for m in markers if str(m).strip() and str(m).lower() in text.lower()),
        None,
    )
    if cta_found and any(carries(i, cta_found) for i in core):
        blockers.append(f"the CTA {_quote(cta_found)}")
    return (
        f"; cannot be trimmed to fit: {' and '.join(blockers)} "
        f"are protected and total {total} chars over the {cap} cap"
    )


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

    # Rule 3: platform length cap. When the draft is over, the
    # evidence also names any protected elements (brand name,
    # required hashtags, CTA, opening sentence) whose combined
    # length alone exceeds the cap, so an untrimmable draft says
    # which element could not fit instead of failing silently.
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
                    + _protected_overflow_note(text, limit, brand_voice)
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
        cap = PLATFORM_LIMITS.get(platform.lower())
        if cap is not None and cap <= floor:
            # The platform cannot hold more than the floor (X's
            # 280, or Threads' 500 against a 500 floor): the depth
            # standard was written for long-form platforms, so on
            # this platform depth is judged against the cap itself
            # -- a draft that fills at least half the cap carries
            # the substance; a stub still fails. (Generalises the
            # PR #50 stand-down, which passed every short-platform
            # draft unconditionally.) The reason is quoted either
            # way, never silently skipped.
            needed = (cap + 1) // 2
            results.append(
                RuleResult(
                    rule="caption_depth",
                    passed=len(text) >= needed,
                    evidence=(
                        f"depth floor {floor} meets or exceeds the {platform} cap "
                        f"{cap}; judged against the cap instead: {len(text)} chars "
                        f"reaches at least half the cap ({needed})"
                        if len(text) >= needed
                        else f"depth floor {floor} meets or exceeds the {platform} cap "
                        f"{cap}; judged against the cap instead: {len(text)} chars "
                        f"is below half the cap ({needed})"
                    ),
                )
            )
        else:
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

    # Rule 7: no unexpected scripts. A Burmese caption legitimately
    # mixes Myanmar and Latin (brand names, hashtags, URLs); any
    # other letter script is a paste accident or injected text
    # (the 2026-11-05 incident: the Arabic word "شکایت" inside a
    # Day-7 draft, caught by no rule). The brand data may extend
    # the allowed set with the allowed_scripts key (e.g. "Thai"
    # for a brand that posts bilingually). Evidence quotes the
    # offending characters and a snippet around the first one.
    allowed = set(_DEFAULT_ALLOWED_SCRIPTS)
    extra = (brand_voice or {}).get("allowed_scripts") or []
    if isinstance(extra, str):
        extra = [extra]
    for name in extra:
        key = str(name).strip().upper()
        if key:
            allowed.add(_SCRIPT_ALIASES.get(key, key))
    offenders: list[tuple[str, str]] = []
    seen_chars: set[str] = set()
    first_at: int | None = None
    for i, ch in enumerate(text):
        script = _char_script(ch)
        if script and script not in allowed and ch not in seen_chars:
            seen_chars.add(ch)
            offenders.append((ch, script))
            if first_at is None:
                first_at = i
    if offenders:
        chars = "".join(c for c, _ in offenders[:16])
        scripts = ", ".join(sorted({s.title() for _, s in offenders}))
        start = max(0, (first_at or 0) - 24)
        results.append(
            RuleResult(
                rule="unexpected_script",
                passed=False,
                evidence=(
                    f"unexpected {scripts} characters {_quote(chars)} "
                    f"in {_quote(text[start:start + 72])}; allowed scripts: "
                    f"{', '.join(sorted(s.title() for s in allowed))}"
                ),
            )
        )
    else:
        results.append(
            RuleResult(
                rule="unexpected_script",
                passed=True,
                evidence=(
                    "no characters outside the allowed scripts "
                    f"({', '.join(sorted(s.title() for s in allowed))})"
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
