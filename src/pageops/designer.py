"""Graphic Designer role (Department 1, Visuals stage).

Produces each post's visual from brand templates only: fixed layouts,
brand colours, the brand wordmark, the post's headline. Never
freestyled. The Designer checks its own work (template compliance:
file, dimensions, brand colour present) before the row moves on.

Brand assets are interim seed values from the brand-assets layer;
when the owner's official FYF AI brand files land, they replace
these in one swap (same keys, same consumers).
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .checker import DEFAULT_CTA_MARKERS, check_character

# The brand character reference in the brand-assets layer is a
# repo-root-relative path (assets/paco-character.png). Relative
# values resolve against the repo root only, never the caller's
# cwd, and the resolved path must stay contained under the repo
# root: absolute paths elsewhere and ".." traversal are treated
# as a missing reference (see _resolve_character_reference).
REPO_ROOT = Path(__file__).resolve().parents[2]

ASSETS: dict = {
    "brand_name": "FYF AI",
    "primary": "#123B8F",
    "accent": "#F5B301",
    "background": "#F7F5F0",
    "ink": "#14213D",
}

ASSETS["primary_rgb"] = tuple(
    int(ASSETS["primary"][i : i + 2], 16) for i in (1, 3, 5)
)
ASSETS["accent_rgb"] = tuple(int(ASSETS["accent"][i : i + 2], 16) for i in (1, 3, 5))
ASSETS["background_rgb"] = tuple(
    int(ASSETS["background"][i : i + 2], 16) for i in (1, 3, 5)
)
ASSETS["ink_rgb"] = tuple(int(ASSETS["ink"][i : i + 2], 16) for i in (1, 3, 5))

TEMPLATES: dict[str, tuple[int, int]] = {
    "poster": (1080, 1350),
    "thumb": (1080, 1080),
    "banner": (1640, 924),
    "carousel": (1080, 1080),
}

# The character sheet is a brand-assets artefact, not a post visual:
# one fixed size, composed from the reference image only.
CHARACTER_SHEET_SIZE: tuple[int, int] = (1800, 1200)

_FONT_CANDIDATES = [
    Path.home() / "workspace" / "reels" / "fonts" / "Padauk-Bold.ttf",
    Path.home() / "workspace" / "reels" / "fonts" / "Padauk-Regular.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit(
    draw: ImageDraw.ImageDraw,
    text: str,
    start_size: int,
    max_width: int,
    max_lines: int,
    min_size: int = 28,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, list[str]]:
    """Fit text into max_lines by stepping the font size down.

    Never silently truncates: if the text still overflows at the
    minimum size, the last line ends with an ellipsis, visibly.
    """
    size = start_size
    while size > min_size:
        font = _font(size)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
        size -= 6
    font = _font(min_size)
    lines = _wrap(draw, text, font, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,") + "…"
    return font, lines


def template_for(row: dict) -> str:
    fmt = (row.get("format") or "").lower()
    if "carousel" in fmt:
        return "carousel"
    if "banner" in fmt:
        return "banner"
    if "thumb" in fmt:
        return "thumb"
    return "poster"


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def split_points(text: str) -> list[str]:
    """Split a draft into its points, deterministically.

    Lines first, then sentences. No model, no randomness: the same
    draft always yields the same points, in the same order. Shared
    by the carousel slides and the video storyboard.
    """
    points: list[str] = []
    for line in (text or "").splitlines():
        for chunk in _SENTENCE_SPLIT.split(line.strip()):
            chunk = chunk.strip()
            if chunk:
                points.append(chunk)
    return points


def cta_sentence(text: str, brand_voice: dict | None = None) -> str:
    """The draft's call-to-action sentence, or "" when it has none.

    Markers come from the brand data when the brand carries them,
    else the checker's defaults (the same lists the checker uses).
    """
    markers = (brand_voice or {}).get("cta_markers") or DEFAULT_CTA_MARKERS
    for point in split_points(text):
        lowered = point.lower()
        if any(marker.lower() in lowered for marker in markers):
            return point
    return ""


def _resolve_character_reference(reference: str) -> Path | None:
    """Resolve the brand character reference to an existing file.

    Relative values resolve against the repo root only, so the
    outcome never depends on the caller's cwd. The resolved path
    must stay contained under the repo root (the same structural
    containment the dashboard applies to /visual/ files): absolute
    paths elsewhere and ".." traversal are treated as a missing
    reference. A missing reference is a normal outcome (returns
    None): the character is simply unavailable, and the caller
    records that honestly.
    """
    if not reference:
        return None
    path = Path(str(reference))
    candidate = path if path.is_absolute() else REPO_ROOT / path
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if not resolved.is_relative_to(REPO_ROOT.resolve()):
        return None
    return resolved if resolved.exists() else None


def _badge_placement(width: int, height: int, footer: int = 110) -> tuple[int, int, int]:
    """Standard badge geometry: (diameter, x, y).

    Bottom-right, just above the footer band, at about 22% of the
    canvas width. Every format that uses the standard placement
    shares this, so the badge sits consistently across formats.
    """
    diameter = max(48, round(width * 0.22))
    return diameter, width - diameter - 48, height - footer - diameter - 36


def _composite_character_badge(
    img: Image.Image,
    reference_path: Path,
    *,
    diameter: int | None = None,
    x: int | None = None,
    y: int | None = None,
) -> bool:
    """Composite the reference image as a circular badge, in place.

    The reference is only ever cropped to a circle and ringed with
    the brand accent colour; it is never redrawn or restyled. With
    no geometry arguments the badge takes the standard placement
    (_badge_placement); banner, carousel and video callers pass
    their own size and position for the same construction.

    Returns True when the badge was composited. A reference that
    exists but cannot be read as an image (truncated, not an image
    at all) returns False instead of raising: the caller records
    "reference unreadable" and the checker fails the row cleanly,
    exactly like the missing-reference path.
    """
    width, height = img.size
    if diameter is None:
        diameter = max(48, round(width * 0.22))
    ring = max(6, diameter // 18)
    try:
        with Image.open(reference_path) as ref:
            ref = ref.convert("RGBA")
            side = min(ref.size)
            left = (ref.width - side) // 2
            top = (ref.height - side) // 2
            badge = ref.crop((left, top, left + side, top + side)).resize(
                (diameter, diameter), Image.LANCZOS
            )
    except OSError:
        return False
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, diameter, diameter], fill=255)
    if x is None:
        x = width - diameter - 48
    if y is None:
        y = height - 110 - diameter - 36
    draw = ImageDraw.Draw(img)
    draw.ellipse(
        [x - ring, y - ring, x + diameter + ring, y + diameter + ring],
        fill=ASSETS["accent_rgb"],
    )
    img.paste(badge, (x, y), mask)
    return True


def _apply_character(
    img: Image.Image,
    row: dict,
    brand_voice: dict | None,
    *,
    diameter: int,
    x: int,
    y: int,
) -> dict:
    """Composite the badge when the row calls for it; report honestly.

    Returns the manifest character dict, always with the same four
    keys. A missing or unreadable reference is recorded, never
    fabricated or silently dropped.
    """
    character: dict = {"used": False, "requested": False, "reference": "", "reason": ""}
    if str(row.get("character") or "").strip().lower() != "yes":
        return character
    reference = (brand_voice or {}).get("character_image", "")
    resolved = _resolve_character_reference(reference)
    if resolved is None:
        return {
            "used": False,
            "requested": True,
            "reference": reference,
            "reason": "reference missing",
        }
    if _composite_character_badge(img, resolved, diameter=diameter, x=x, y=y):
        return {"used": True, "requested": True, "reference": reference, "reason": ""}
    return {
        "used": False,
        "requested": True,
        "reference": reference,
        "reason": "reference unreadable",
    }


def render_visual(
    row: dict, out_dir: Path | str, brand_voice: dict | None = None
) -> tuple[Path, dict]:
    """Render the row's visual from its template. Deterministic.

    Carousel rows return slide 1's path; the manifest lists every
    slide. Banner rows render the wide banner template. All other
    formats render the single-image templates as before.
    """
    template = template_for(row)
    if template == "carousel":
        return _render_carousel(row, out_dir, brand_voice)
    if template == "banner":
        return _render_banner(row, out_dir, brand_voice)
    width, height = TEMPLATES[template]
    img = Image.new("RGB", (width, height), ASSETS["background_rgb"])
    draw = ImageDraw.Draw(img)
    # Top band in the brand primary colour, with the wordmark.
    draw.rectangle([0, 0, width, 150], fill=ASSETS["primary_rgb"])
    draw.text(
        (60, 45),
        ASSETS["brand_name"],
        font=_font(64),
        fill=(255, 255, 255),
    )
    # Headline: the post's topic, in the ink colour.
    headline_font, headline_lines = _fit(draw, row.get("topic", ""), 72, width - 120, 3)
    y = 240
    for line in headline_lines:
        draw.text((60, y), line, font=headline_font, fill=ASSETS["ink_rgb"])
        y += 92
    # Angle as the subline, fitted above the footer band.
    angle_font, angle_lines = _fit(draw, row.get("angle", ""), 44, width - 120, 6)
    y += 30
    for line in angle_lines:
        if y > height - 190:
            break
        draw.text((60, y), line, font=angle_font, fill=ASSETS["primary_rgb"])
        y += 60
    # Footer band in the accent colour: platform + format.
    draw.rectangle([0, height - 110, width, height], fill=ASSETS["accent_rgb"])
    footer = f"{row.get('platform', '')} · {row.get('format', '')}".strip(" ·")
    draw.text((60, height - 82), footer, font=_font(40), fill=ASSETS["ink_rgb"])

    # Brand character badge in the standard placement, only when
    # the row calls for it (see _apply_character).
    diameter, badge_x, badge_y = _badge_placement(width, height)
    character = _apply_character(
        img, row, brand_voice, diameter=diameter, x=badge_x, y=badge_y
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = f"visual-{row.get('id', 'row')}-{template}.png"
    path = out / name
    img.save(path)
    manifest = {
        "template": template,
        "format": template,
        "size": (width, height),
        "wordmark": ASSETS["brand_name"],
        "headline": row.get("topic", ""),
        "path": str(path),
        "character": character,
    }
    return path, manifest


def _render_banner(
    row: dict, out_dir: Path | str, brand_voice: dict | None = None
) -> tuple[Path, dict]:
    """The wide banner template (1640x924): page and campaign use.

    Same fixed layout family as the other templates: primary top
    band with the wordmark, headline and supporting line on the
    left, accent footer band. The character badge, when the row
    calls for it, sits larger on the right.
    """
    width, height = TEMPLATES["banner"]
    img = Image.new("RGB", (width, height), ASSETS["background_rgb"])
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 150], fill=ASSETS["primary_rgb"])
    draw.text(
        (60, 45),
        ASSETS["brand_name"],
        font=_font(64),
        fill=(255, 255, 255),
    )
    # The badge zone is reserved on the right whether or not this
    # row uses it, so the text block never moves between banners.
    diameter = round(height * 0.40)
    badge_x = width - diameter - 70
    badge_y = 200
    text_width = badge_x - 120
    headline_font, headline_lines = _fit(draw, row.get("topic", ""), 84, text_width, 3)
    y = 230
    for line in headline_lines:
        draw.text((60, y), line, font=headline_font, fill=ASSETS["ink_rgb"])
        y += 104
    angle_font, angle_lines = _fit(draw, row.get("angle", ""), 44, text_width, 5)
    y += 24
    for line in angle_lines:
        if y > height - 190:
            break
        draw.text((60, y), line, font=angle_font, fill=ASSETS["primary_rgb"])
        y += 60
    draw.rectangle([0, height - 110, width, height], fill=ASSETS["accent_rgb"])
    footer = f"{row.get('platform', '')} · {row.get('format', '')}".strip(" ·")
    draw.text((60, height - 82), footer, font=_font(40), fill=ASSETS["ink_rgb"])

    character = _apply_character(
        img, row, brand_voice, diameter=diameter, x=badge_x, y=badge_y
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"visual-{row.get('id', 'row')}-banner.png"
    img.save(path)
    manifest = {
        "template": "banner",
        "format": "banner",
        "size": (width, height),
        "wordmark": ASSETS["brand_name"],
        "headline": row.get("topic", ""),
        "path": str(path),
        "character": character,
    }
    return path, manifest


# A carousel carries at most this many middle point slides
# (plus the hook and the closing CTA slide), mirroring the video
# storyboard's capped shape: a long draft must not produce an
# unbounded slide set.
CAROUSEL_POINT_LIMIT = 6


def _carousel_points(row: dict, brand_voice: dict | None = None) -> tuple[list[str], str]:
    """The draft's middle points and CTA sentence for a carousel."""
    draft = row.get("draft", "")
    cta = cta_sentence(draft, brand_voice)
    points = [p for p in split_points(draft) if p != cta]
    return points, cta


def carousel_slides(row: dict, brand_voice: dict | None = None) -> list[dict]:
    """The deterministic slide plan for a carousel row.

    Slide 1 is the hook (the topic, with the angle as its subline);
    the middle slides are the draft's points (see split_points),
    capped at CAROUSEL_POINT_LIMIT; the final slide is the call to
    action: the draft's own CTA sentence when it has one, else the
    standing brand CTA line. The character badge rides on the
    first and final slides.
    """
    points, cta = _carousel_points(row, brand_voice)
    slides: list[dict] = [
        {"kind": "hook", "text": row.get("topic", ""), "badge": True}
    ]
    slides += [
        {"kind": "point", "text": p, "badge": False}
        for p in points[:CAROUSEL_POINT_LIMIT]
    ]
    slides.append(
        {"kind": "cta", "text": cta or "Message us to get started.", "badge": True}
    )
    return slides


def _render_carousel(
    row: dict, out_dir: Path | str, brand_voice: dict | None = None
) -> tuple[Path, dict]:
    """Render a carousel slide set (1080x1080 per slide).

    Returns slide 1's path; the manifest lists every slide path
    and the character record for the set (the badge is composited
    on the first and final slides when the row calls for it).
    """
    width, height = TEMPLATES["carousel"]
    plan = carousel_slides(row, brand_voice)
    total = len(plan)
    all_points, _cta = _carousel_points(row, brand_voice)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    character: dict = {"used": False, "requested": False, "reference": "", "reason": ""}
    for index, slide in enumerate(plan, start=1):
        img = Image.new("RGB", (width, height), ASSETS["background_rgb"])
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, width, 150], fill=ASSETS["primary_rgb"])
        draw.text(
            (60, 45),
            ASSETS["brand_name"],
            font=_font(64),
            fill=(255, 255, 255),
        )
        body_font, body_lines = _fit(draw, slide["text"], 64, width - 120, 8)
        y = 230
        for line in body_lines:
            draw.text((60, y), line, font=body_font, fill=ASSETS["ink_rgb"])
            y += 84
        if slide["kind"] == "hook" and row.get("angle"):
            angle_font, angle_lines = _fit(draw, row["angle"], 44, width - 120, 4)
            y += 24
            for line in angle_lines:
                if y > height - 420:
                    break
                draw.text((60, y), line, font=angle_font, fill=ASSETS["primary_rgb"])
                y += 60
        draw.rectangle([0, height - 110, width, height], fill=ASSETS["accent_rgb"])
        footer = (
            f"{row.get('platform', '')} · {row.get('format', '')} · {index} / {total}"
        ).strip(" ·")
        draw.text((60, height - 82), footer, font=_font(40), fill=ASSETS["ink_rgb"])
        if slide["badge"]:
            diameter, badge_x, badge_y = _badge_placement(width, height)
            result = _apply_character(
                img, row, brand_voice, diameter=diameter, x=badge_x, y=badge_y
            )
            if index == 1:
                character = result
        path = out / f"visual-{row.get('id', 'row')}-slide-{index}.png"
        img.save(path)
        paths.append(path)
    manifest = {
        "template": "carousel",
        "format": "carousel",
        "size": (width, height),
        "wordmark": ASSETS["brand_name"],
        "headline": row.get("topic", ""),
        "path": str(paths[0]),
        "slides": [str(p) for p in paths],
        "slides_truncated": len(all_points) > CAROUSEL_POINT_LIMIT,
        "points_total": len(all_points),
        "character": character,
    }
    return paths[0], manifest


def build_character_sheet(brand_voice: dict | None, out_path: Path | str) -> Path:
    """Compose the brand character sheet from the stored reference only.

    One labelled sheet (1800x1200): the full reference view, a face
    zoom crop and the badge crop, on the brand colours, with Padauk
    labels. Every panel is a crop or resize of the reference image
    itself; nothing is redrawn or restyled, so the sheet is the
    consistency source for character placements in every format.
    """
    reference = (brand_voice or {}).get("character_image", "")
    resolved = _resolve_character_reference(reference)
    if resolved is None:
        raise RuntimeError(
            f"character sheet: reference missing ({reference or 'no character_image'})"
        )
    try:
        with Image.open(resolved) as ref:
            full = ref.convert("RGBA").copy()
    except OSError as exc:
        raise RuntimeError(f"character sheet: reference unreadable ({exc})") from exc

    width, height = CHARACTER_SHEET_SIZE
    sheet = Image.new("RGB", (width, height), ASSETS["background_rgb"])
    draw = ImageDraw.Draw(sheet)
    draw.rectangle([0, 0, width, 150], fill=ASSETS["primary_rgb"])
    name = (brand_voice or {}).get("character_name", "") or "PaCo"
    draw.text(
        (60, 45),
        f"{ASSETS['brand_name']} · {name} character sheet",
        font=_font(56),
        fill=(255, 255, 255),
    )

    panel_y, panel_size = 210, 520
    panels: list[tuple[str, Image.Image]] = []
    full_view = ImageOps.fit(full.convert("RGB"), (panel_size, panel_size))
    panels.append(("Full view", full_view))
    ref_w, ref_h = full.size
    face = full.crop(
        (
            int(ref_w * 0.25),
            int(ref_h * 0.03),
            int(ref_w * 0.75),
            int(ref_h * 0.53),
        )
    )
    panels.append(("Face zoom", ImageOps.fit(face.convert("RGB"), (panel_size, panel_size))))
    badge_panel = Image.new("RGB", (panel_size, panel_size), ASSETS["background_rgb"])
    _composite_character_badge(
        badge_panel, resolved, diameter=440, x=40, y=40
    )
    panels.append(("Badge", badge_panel))
    for i, (label, panel) in enumerate(panels):
        px = 60 + i * (panel_size + 60)
        draw.rectangle(
            [px - 3, panel_y - 3, px + panel_size + 3, panel_y + panel_size + 3],
            outline=ASSETS["primary_rgb"],
            width=3,
        )
        sheet.paste(panel, (px, panel_y))
        draw.text(
            (px, panel_y + panel_size + 28),
            label,
            font=_font(44),
            fill=ASSETS["ink_rgb"],
        )

    rules = (brand_voice or {}).get("character_rules", "")
    if rules:
        rules_font, rules_lines = _fit(draw, rules, 36, width - 120, 3)
        y = 950
        for line in rules_lines:
            draw.text((60, y), line, font=rules_font, fill=ASSETS["primary_rgb"])
            y += 50

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def verify_visual(path: Path | str, manifest: dict) -> tuple[bool, str]:
    """The Designer's self-check: template compliance, with evidence."""
    path = Path(path)
    if not path.exists():
        return False, f"visual file missing: {path}"
    with Image.open(path) as img:
        if img.size != tuple(manifest["size"]):
            return False, f"size mismatch: got {img.size}, template {manifest['size']}"
        if path.stat().st_size < 5_000:
            return False, f"visual file suspiciously small: {path.stat().st_size} bytes"
        rgb = img.convert("RGB")
        found = any(
            rgb.getpixel((x, y)) == ASSETS["primary_rgb"]
            for x in range(0, img.size[0], 60)
            for y in range(0, 120, 10)
        )
        if not found:
            return False, "brand primary colour absent from the top band"
    return True, (
        f"template={manifest['template']} size={manifest['size']} "
        f"wordmark={manifest['wordmark']} primary-colour=present"
    )


def produce_visual(store, row: dict) -> dict:
    """Produce + self-check the visual for a drafted row; store its path.

    Refuses rows without a final draft: visuals are built from the
    Copywriter's finished text, never before it exists.
    """
    if not (row.get("draft") or "").strip():
        raise ValueError("no draft on the row: visuals follow the final draft")
    brand_voice = store.get_brand_voice()
    out_dir = store.data_dir / "visuals"
    path, manifest = render_visual(row, out_dir, brand_voice=brand_voice)
    if manifest.get("slides"):
        # A carousel is accepted only when EVERY slide verifies,
        # exactly as a single image verifies against its template.
        for slide_path in manifest["slides"]:
            ok, evidence = verify_visual(slide_path, manifest)
            if not ok:
                raise RuntimeError(f"visual self-check failed: {evidence}")
    else:
        ok, evidence = verify_visual(path, manifest)
        if not ok:
            raise RuntimeError(f"visual self-check failed: {evidence}")
    # The Brand Checker's character rule, applied to this visual's
    # manifest: a requested badge that is missing or composited from
    # the wrong reference fails exactly like a failed visual check.
    character_result = check_character(row, manifest, brand_voice)
    if not character_result.passed:
        raise RuntimeError(f"character check failed: {character_result.summary()}")
    relative = path.relative_to(store.data_dir)
    return store.update_row("plan", row["id"], {"visual": str(relative)})
