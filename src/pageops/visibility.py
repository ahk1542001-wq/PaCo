"""Visibility audit (SEO / GEO / AEO) for PaCo Agent.

The Analyst's second instrument: how findable the brand's
content is. Deterministic checks over the drafted content and
the brand data, each with quoted counts as evidence and a fix
attached to every warning, in the same discipline as the
checker and the performance report. The model's interpretation
is optional, humanised like every writer output, and
figure-checked against the findings before it is kept.

This module is the product form of the manual page audit the
operator ran on FYF AI (2026-11-04): openings that start with
scenarios instead of searchable terms, no question-and-answer
shape for answer engines to lift, no consistent keyword spine,
and a page name with no descriptor. What was done by hand there
is a stage here.
"""

from __future__ import annotations

import re

from .checker import DEFAULT_CTA_MARKERS
from .model_client import humanize_text
from .store import Store

PASS_AT = 70  # percent of posts that must satisfy a check


def _pct(part: int, total: int) -> int:
    return round(100 * part / total) if total else 0


def _status(pct: int) -> str:
    return "pass" if pct >= PASS_AT else "warn"


def _search_terms(brand: dict) -> list[str]:
    """Searchable terms from the brand data: full service phrases
    plus the Latin-script words inside services, audience and the
    brand name (buyers mix English terms into Burmese searches)."""
    terms = [s.strip() for s in brand.get("services", []) if s.strip()]
    haystack = " ".join(
        terms
        + [brand.get("audience", ""), brand.get("brand_name", "")]
    )
    terms += [w for w in re.findall(r"[A-Za-z][A-Za-z0-9+#]{2,}", haystack)]
    seen, out = set(), []
    for term in terms:
        if term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return out


def _has_question(text: str) -> bool:
    return "?" in text or "လား" in text or "မလဲ" in text


def _has_answer_shape(text: str) -> bool:
    if "ဆိုတာ" in text:  # a definition: "X ဆိုတာ ..."
        return True
    if "အရင်" in text and "ပြီးရင်" in text:  # sequenced steps
        return True
    return bool(re.search(r"(?m)^\s*1[\.\)、]", text))  # a numbered list


def _numbers(text: str) -> set[int]:
    return {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text)}


def build_visibility_audit(store: Store, client=None) -> dict:
    """Return {findings, text} for the store's drafted content.

    Pure: no writes. Recording the audit (notes, history) is
    pipeline.run_visibility_audit, the Analyst's stage act.
    """
    brand = store.get_brand_voice()
    rows = [
        r for r in store.read_dataset("plan") if (r.get("draft") or "").strip()
    ]
    brand_name = (brand.get("brand_name") or "").strip()
    services = [s for s in brand.get("services", []) if s.strip()]
    markers = brand.get("cta_markers") or DEFAULT_CTA_MARKERS
    findings: list[dict] = []

    def add(check, status, evidence, fix=""):
        findings.append(
            {"check": check, "status": status, "evidence": evidence, "fix": fix}
        )

    total = len(rows)
    if total:
        terms = _search_terms(brand)
        openings = [r["draft"][:160] for r in rows]
        hits = [i for i, o in enumerate(openings) if any(t in o for t in terms)]
        add(
            "seo_opening_terms",
            _status(_pct(len(hits), total)),
            f"{len(hits)}/{total} posts ({_pct(len(hits), total)}%) open with a "
            f"searchable service or audience term",
            "Open with the term buyers search for, then the scene; "
            "a scene alone cannot be found.",
        )
        qa = [
            r for r in rows if _has_question(r["draft"]) and _has_answer_shape(r["draft"])
        ]
        add(
            "aeo_question_answer",
            _status(_pct(len(qa), total)),
            f"{len(qa)}/{total} posts ({_pct(len(qa), total)}%) pair a real "
            f"question with a definition or steps an answer engine can lift",
            "Shape education posts as a buyer question plus a direct, "
            "stepped answer.",
        )
        if brand_name:
            named = [r for r in rows if brand_name in r["draft"][:200]]
            add(
                "geo_brand_entity",
                _status(_pct(len(named), total)),
                f"{len(named)}/{total} posts ({_pct(len(named), total)}%) name "
                f"{brand_name} in the first 200 characters",
                "Name the brand early in every post so AI engines can "
                "identify the entity behind the content.",
            )
        else:
            add(
                "geo_brand_entity", "warn",
                "the brand data carries no brand name",
                "Set the brand name in the brand data first.",
            )
        if services:
            used, unused = [], []
            for svc in services:
                tokens = [
                    w
                    for w in re.findall(r"[A-Za-z][A-Za-z0-9+#]{2,}", svc)
                    if w.lower() not in ("from", "pack", "with", "your", "for", "the")
                ]
                if tokens:
                    hit = any(
                        t.lower() in r["draft"].lower()
                        for t in tokens
                        for r in rows
                    )
                else:
                    hit = any(svc in r["draft"] for r in rows)
                (used if hit else unused).append(svc)
            add(
                "geo_keyword_spine",
                _status(_pct(len(used), len(services))),
                f"{len(used)}/{len(services)} declared services are "
                f"represented in the content by their key terms"
                + (f"; not represented: {', '.join(unused)}" if unused else ""),
                "Weave every declared service's key terms through the "
                "week's content, spelled the same way every time, so "
                "engines learn one consistent spine.",
            )
        else:
            add(
                "geo_keyword_spine", "warn",
                "the brand data declares no services, so there is no "
                "keyword spine to be consistent with",
                "Declare the services in the brand data; they are the spine.",
            )
        cta = [r for r in rows if any(m.lower() in r["draft"].lower() for m in markers)]
        add(
            "cta_funnel_start",
            _status(_pct(len(cta), total)),
            f"{len(cta)}/{total} posts ({_pct(len(cta), total)}%) carry the "
            f"brand's call to action",
            "End every post with the call to action; a findable post "
            "with no CTA starts no conversation.",
        )
    parts = {
        "brand name": bool(brand_name),
        "services": bool(services),
        "audience": bool((brand.get("audience") or "").strip()),
    }
    missing = [k for k, ok in parts.items() if not ok]
    add(
        "page_descriptor",
        "pass" if not missing else "warn",
        "brand data carries "
        + (", ".join(k for k, ok in parts.items() if ok) or "nothing")
        + (f"; missing: {', '.join(missing)}" if missing else ""),
        "Complete the brand data; page discovery (name, descriptor, "
        "services) is what search and AI engines read first.",
    )

    header = (
        f"Visibility audit (SEO/GEO/AEO) over {total} drafted post(s):"
        if total
        else "Visibility audit (SEO/GEO/AEO): no drafted content to audit yet."
    )
    lines = [header]
    for f in findings:
        mark = "PASS" if f["status"] == "pass" else "WARN"
        line = f"[{mark}] {f['check']} - evidence: {f['evidence']}"
        if f["status"] == "warn" and f["fix"]:
            line += f" Fix: {f['fix']}"
        lines.append(line)
    text = "\n".join(lines)

    if client is not None and total:
        read = client.visibility_read(text, brand)
        read, humanize_error = humanize_text(client, read, brand)
        if humanize_error:
            text += f"\n[HUMANIZER FALLBACK] visibility read unedited ({humanize_error})"
        if _numbers(read) <= _numbers(text):
            text += f"\nRead: {read}"
        else:
            text += (
                "\n[READ DROPPED] the model's visibility read cited "
                "figures outside the audit findings."
            )
    return {"findings": findings, "text": text}
