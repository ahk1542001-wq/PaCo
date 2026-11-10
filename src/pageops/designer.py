"""Graphic Designer role (Department 1, Visuals stage).

Produces each post's visual two ways. The baseline is the brand
templates: fixed layouts, brand colours, the brand wordmark, the
post's headline, never freestyled. When a director (the planner
model) and an image client are both configured, a still visual is
produced in the plan's visual style instead: the director writes a
concept line and an image prompt, one generated plate (Muse Image)
becomes the full-bleed background, and the Designer composites the
typography in code over it. "scene" style carries the full headline
treatment; "concept" style carries one metaphor, one headline line,
minimal type. Any failure in direction or generation falls back to
the template render and is recorded in the manifest; a plate failure
never fails the row. The Designer checks its own work (template
compliance: file, dimensions, brand colour present) before the row
moves on.

Brand assets: the module-level ASSETS are the interim seed brand
(FYF AI) and remain the fallback. A store's brand voice overrides
them per render — brand_name becomes the wordmark and the hex codes
in brand_colors become the palette (see resolve_assets) — so every
page renders in its own identity.
"""

from __future__ import annotations

import os
import re
from io import BytesIO
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


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))


_HEX_RE = re.compile(r"#([0-9A-Fa-f]{6})\b")


def resolve_assets(brand_voice: dict | None) -> dict:
    """The effective brand assets for one render.

    The module-level ASSETS are the interim seed brand. A store's
    brand voice overrides them: brand_name replaces the wordmark,
    and the hex codes in brand_colors replace the palette. Each
    hex's role comes from the words that follow it in the
    brand_colors text ("(main", "background", "accent") — the same
    annotations the brand guidelines use; an unlabelled palette
    falls back to position (first hex = primary, second = accent).
    A "spark" accent is a sparing highlight, never the main accent.
    When the primary is overridden the ink follows it (guideline:
    body text is the primary colour). Anything the voice does not
    specify keeps the seed value, so a voice with no identity keys
    renders exactly as before.
    """
    assets = dict(ASSETS)
    if not brand_voice:
        return assets
    name = str(brand_voice.get("brand_name") or "").strip()
    if name:
        assets["brand_name"] = name
    text = str(brand_voice.get("brand_colors") or "")
    matches = list(_HEX_RE.finditer(text))
    if not matches:
        return assets
    labelled: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        labelled.append(("#" + match.group(1).upper(), text[match.end() : end].lower()))

    def labelled_hex(word: str, *, skip: str | None = None) -> str | None:
        for hexcode, label in labelled:
            if word in label and (skip is None or skip not in label):
                return hexcode
        return None

    primary = labelled_hex("main") or labelled[0][0]
    background = labelled_hex("background")
    accent = labelled_hex("accent", skip="spark") or labelled_hex("accent")
    if accent is None and len(labelled) > 1:
        accent = labelled[1][0]
    assets["primary"] = primary
    assets["ink"] = primary
    if background:
        assets["background"] = background
    if accent:
        assets["accent"] = accent
    for role in ("primary", "accent", "background", "ink"):
        assets[f"{role}_rgb"] = _hex_to_rgb(assets[role])
    return assets

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
    accent_rgb: tuple[int, int, int] | None = None,
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
        fill=accent_rgb if accent_rgb is not None else ASSETS["accent_rgb"],
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
    accent_rgb = resolve_assets(brand_voice)["accent_rgb"]
    if _composite_character_badge(
        img, resolved, diameter=diameter, x=x, y=y, accent_rgb=accent_rgb
    ):
        return {"used": True, "requested": True, "reference": reference, "reason": ""}
    return {
        "used": False,
        "requested": True,
        "reference": reference,
        "reason": "reference unreadable",
    }


def visual_style_for(row: dict) -> str:
    """The row's visual style: "scene" or "concept".

    Rows planned before the field existed (and rows whose planner
    left it blank) default to "scene", and any unrecognised value
    resolves to "scene" as well: the default is always the safe,
    full-treatment style.
    """
    style = str(row.get("visual_style") or "scene").strip().lower()
    return style if style in ("scene", "concept") else "scene"


def save_plate(raw: bytes, out_dir: Path | str, row: dict) -> Path:
    """Store generated plate bytes as a PNG in the visuals dir.

    The image API's payload may be WebP bytes despite any .png
    naming, so the bytes always go through PIL and come out as a
    real PNG, written atomically (temp file, then replace).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"plate-{row.get('id', 'row')}.png"
    tmp = out / f"plate-{row.get('id', 'row')}.tmp.png"
    with Image.open(BytesIO(raw)) as img:
        img.convert("RGB").save(tmp)
    os.replace(tmp, path)
    return path


def direct_plate(
    row: dict,
    brand_voice: dict | None,
    out_dir: Path | str,
    director,
    image_client,
) -> tuple[dict, dict, Path | None]:
    """Direction + one generated plate for a still visual.

    Returns (concept_record, plate_record, plate_path). Never
    raises: the director writes the concept line and the prompt,
    the image client generates one plate from it, and any failure
    in either step is recorded and returns plate_path None, so the
    caller renders the brand template instead. A plate failure
    never fails the row.
    """
    style = visual_style_for(row)
    concept: dict = {"style": style, "concept": "", "prompt": "", "no_exceptions": ""}
    try:
        directed = director.direct_visual(
            row, row.get("draft", ""), brand_voice or {}, style
        )
        if not isinstance(directed, dict):
            raise ValueError("director returned no direction")
        concept = {
            "style": style,
            "concept": str(directed.get("concept", "")),
            "prompt": str(directed.get("prompt", "")),
            "no_exceptions": str(directed.get("no_exceptions", "")),
        }
    except Exception as exc:
        return concept, {"used": False, "reason": f"direction failed: {exc}"}, None
    try:
        raw = image_client.generate_image_bytes(concept["prompt"])
        plate_path = save_plate(raw, out_dir, row)
    except Exception as exc:
        return concept, {"used": False, "reason": f"plate generation failed: {exc}"}, None
    return concept, {"used": True, "reason": ""}, plate_path


def _plate_base(plate_path: Path | str, size: tuple[int, int]) -> Image.Image:
    """A generated plate as a full-bleed background, cover-cropped."""
    with Image.open(plate_path) as img:
        plate = img.convert("RGB")
    scale = max(size[0] / plate.width, size[1] / plate.height)
    resized = plate.resize(
        (
            max(size[0], round(plate.width * scale)),
            max(size[1], round(plate.height * scale)),
        ),
        Image.LANCZOS,
    )
    x = (resized.width - size[0]) // 2
    y = (resized.height - size[1]) // 2
    return resized.crop((x, y, x + size[0], y + size[1]))


def _scene_treatment(
    img: Image.Image,
    row: dict,
    brand_voice: dict | None = None,
    footer_text: str | None = None,
    text_width: int | None = None,
) -> None:
    """Scene style over a plate: the full headline treatment.

    A primary-colour scrim fades down from the top (fully opaque at
    the first row, so the brand colour anchors the frame), carrying
    the wordmark, the headline (the topic) and the angle subline in
    white; the accent footer band closes the frame. All type is
    rendered here, in code, never by the image model.
    """
    assets = resolve_assets(brand_voice)
    width, height = img.size
    max_width = text_width if text_width is not None else width - 120
    measure = ImageDraw.Draw(img)
    headline_font, headline_lines = _fit(measure, row.get("topic", ""), 72, max_width, 3)
    angle_font, angle_lines = _fit(measure, row.get("angle", ""), 44, max_width, 4)
    # The scrim must cover every line it carries: measure the text
    # block first, then size the scrim to it, so a long angle never
    # runs off the scrim onto the bare photograph (seen in the first
    # real Concept run, where the subline crossed the photo unreadably).
    text_bottom = 240 + 92 * len(headline_lines) + 30
    probe_y = text_bottom
    for _ in angle_lines:
        if probe_y > height - 190:
            break
        probe_y += 60
    text_bottom = max(text_bottom, probe_y)
    scrim_depth = min(height, max(int(height * 0.55), text_bottom + 60))
    mask = Image.new("L", (1, height), 0)
    for y in range(height):
        alpha = int(255 * max(0.0, 1 - y / scrim_depth) ** 0.6) if y < scrim_depth else 0
        mask.putpixel((0, y), alpha)
    img.paste(Image.new("RGB", (width, height), assets["primary_rgb"]), (0, 0), mask.resize((width, height)))
    draw = ImageDraw.Draw(img)
    draw.text((60, 45), assets["brand_name"], font=_font(64), fill=(255, 255, 255))
    y = 240
    for line in headline_lines:
        draw.text((60, y), line, font=headline_font, fill=(255, 255, 255))
        y += 92
    y += 30
    for line in angle_lines:
        if y > height - 190:
            break
        draw.text((60, y), line, font=angle_font, fill=(235, 240, 250))
        y += 60
    draw.rectangle([0, height - 110, width, height], fill=assets["accent_rgb"])
    footer = footer_text or f"{row.get('platform', '')} · {row.get('format', '')}".strip(" ·")
    draw.text((60, height - 82), footer, font=_font(40), fill=assets["ink_rgb"])


def _concept_treatment(
    img: Image.Image,
    row: dict,
    brand_voice: dict | None = None,
    headline: str | None = None,
) -> None:
    """Concept style over a plate: one metaphor, arranged type.

    Only two elements: a small brand wordmark on a primary-colour
    chip in the top-left corner, and the headline. The headline is
    ARRANGED into the frame, never just stamped on it: direction
    reserves the top band of the plate as a dark, empty headline
    zone, a soft gradient scrim in the brand primary grows that
    zone out of the image itself (no hard band, no pasted panel),
    and the headline — the director's short line when one was
    written, else the draft's first point — is fitted into the
    zone over up to two lines.
    """
    assets = resolve_assets(brand_voice)
    draw = ImageDraw.Draw(img)
    text = (headline or "").strip()
    if not text:
        points = split_points(row.get("draft", ""))
        text = points[0] if points else row.get("topic", "")
    headline_font, headline_lines = _fit(draw, text, 80, img.width - 120, 2)
    # The scrim is sized to the block it carries (the scene
    # treatment's rule: type never runs off its ground), then fades
    # out well above the metaphor.
    block_bottom = 150 + 92 * len(headline_lines) + 46
    depth = min(img.height, block_bottom + 90)
    mask = Image.new("L", (1, img.height), 0)
    for y in range(img.height):
        alpha = int(170 * max(0.0, 1 - y / depth) ** 0.7) if y < depth else 0
        mask.putpixel((0, y), alpha)
    img.paste(
        Image.new("RGB", img.size, assets["primary_rgb"]),
        (0, 0),
        mask.resize(img.size),
    )
    draw = ImageDraw.Draw(img)
    wordmark_font = _font(48)
    wordmark_width = draw.textlength(assets["brand_name"], font=wordmark_font)
    # The accent outline keeps the chip readable as a designed
    # element when the plate's own top band is already dark.
    draw.rectangle(
        [44, 38, 44 + wordmark_width + 48, 114],
        fill=assets["primary_rgb"],
        outline=assets["accent_rgb"],
        width=3,
    )
    draw.text(
        (68, 52), assets["brand_name"], font=wordmark_font, fill=(255, 255, 255)
    )
    y = 150
    for line in headline_lines:
        draw.text((63, y + 3), line, font=headline_font, fill=(10, 18, 38))
        draw.text((60, y), line, font=headline_font, fill=(255, 255, 255))
        y += 92


def _render_plate_single(
    row: dict,
    out_dir: Path | str,
    brand_voice: dict | None,
    plate_path: Path,
    style: str,
    template: str,
    headline: str | None = None,
) -> tuple[Path, dict]:
    """One still visual rendered over a generated plate."""
    width, height = TEMPLATES[template]
    img = _plate_base(plate_path, (width, height))
    if style == "concept":
        _concept_treatment(img, row, brand_voice, headline=headline)
        diameter, badge_x, badge_y = _badge_placement(width, height)
    else:
        if template == "banner":
            badge_diameter = round(height * 0.40)
            text_width = width - badge_diameter - 70 - 120
            _scene_treatment(img, row, brand_voice, text_width=text_width)
            diameter, badge_x, badge_y = badge_diameter, width - badge_diameter - 70, 200
        else:
            _scene_treatment(img, row, brand_voice)
            diameter, badge_x, badge_y = _badge_placement(width, height)
    character = _apply_character(
        img, row, brand_voice, diameter=diameter, x=badge_x, y=badge_y
    )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"visual-{row.get('id', 'row')}-{template}.png"
    img.save(path)
    assets = resolve_assets(brand_voice)
    manifest = {
        "template": template,
        "format": template,
        "size": (width, height),
        "wordmark": assets["brand_name"],
        "primary": assets["primary"],
        "headline": row.get("topic", ""),
        "path": str(path),
        "character": character,
        "style": style,
        "plate": {"used": True, "reason": ""},
    }
    return path, manifest


def render_visual(
    row: dict,
    out_dir: Path | str,
    brand_voice: dict | None = None,
    plate_path: Path | str | None = None,
    style: str = "scene",
    headline: str | None = None,
) -> tuple[Path, dict]:
    """Render the row's visual. Deterministic per input.

    Without a plate this is the brand template render. With a
    generated plate (plate_path) the visual renders full-bleed over
    the plate in the given style; for carousels the plate applies
    to slide 1 only and the remaining slides keep the template
    rendering. Carousel rows return slide 1's path; the manifest
    lists every slide.
    """
    template = template_for(row)
    if template == "carousel":
        return _render_carousel(
            row, out_dir, brand_voice, plate_path=plate_path, style=style, headline=headline
        )
    if plate_path is not None:
        return _render_plate_single(
            row, out_dir, brand_voice, Path(plate_path), style, template, headline=headline
        )
    if template == "banner":
        return _render_banner(row, out_dir, brand_voice)
    assets = resolve_assets(brand_voice)
    width, height = TEMPLATES[template]
    img = Image.new("RGB", (width, height), assets["background_rgb"])
    draw = ImageDraw.Draw(img)
    # Top band in the brand primary colour, with the wordmark.
    draw.rectangle([0, 0, width, 150], fill=assets["primary_rgb"])
    draw.text(
        (60, 45),
        assets["brand_name"],
        font=_font(64),
        fill=(255, 255, 255),
    )
    # Headline: the post's topic, in the ink colour.
    headline_font, headline_lines = _fit(draw, row.get("topic", ""), 72, width - 120, 3)
    y = 240
    for line in headline_lines:
        draw.text((60, y), line, font=headline_font, fill=assets["ink_rgb"])
        y += 92
    # Angle as the subline, fitted above the footer band.
    angle_font, angle_lines = _fit(draw, row.get("angle", ""), 44, width - 120, 6)
    y += 30
    for line in angle_lines:
        if y > height - 190:
            break
        draw.text((60, y), line, font=angle_font, fill=assets["primary_rgb"])
        y += 60
    # Footer band in the accent colour: platform + format.
    draw.rectangle([0, height - 110, width, height], fill=assets["accent_rgb"])
    footer = f"{row.get('platform', '')} · {row.get('format', '')}".strip(" ·")
    draw.text((60, height - 82), footer, font=_font(40), fill=assets["ink_rgb"])

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
        "wordmark": assets["brand_name"],
        "primary": assets["primary"],
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
    assets = resolve_assets(brand_voice)
    width, height = TEMPLATES["banner"]
    img = Image.new("RGB", (width, height), assets["background_rgb"])
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 150], fill=assets["primary_rgb"])
    draw.text(
        (60, 45),
        assets["brand_name"],
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
        draw.text((60, y), line, font=headline_font, fill=assets["ink_rgb"])
        y += 104
    angle_font, angle_lines = _fit(draw, row.get("angle", ""), 44, text_width, 5)
    y += 24
    for line in angle_lines:
        if y > height - 190:
            break
        draw.text((60, y), line, font=angle_font, fill=assets["primary_rgb"])
        y += 60
    draw.rectangle([0, height - 110, width, height], fill=assets["accent_rgb"])
    footer = f"{row.get('platform', '')} · {row.get('format', '')}".strip(" ·")
    draw.text((60, height - 82), footer, font=_font(40), fill=assets["ink_rgb"])

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
        "wordmark": assets["brand_name"],
        "primary": assets["primary"],
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
    row: dict,
    out_dir: Path | str,
    brand_voice: dict | None = None,
    plate_path: Path | None = None,
    style: str = "scene",
    headline: str | None = None,
) -> tuple[Path, dict]:
    """Render a carousel slide set (1080x1080 per slide).

    Returns slide 1's path; the manifest lists every slide path
    and the character record for the set (the badge is composited
    on the first and final slides when the row calls for it). When
    a generated plate is supplied it applies to slide 1 only, in
    the row's style; the remaining slides keep the template
    rendering.
    """
    assets = resolve_assets(brand_voice)
    width, height = TEMPLATES["carousel"]
    plan = carousel_slides(row, brand_voice)
    total = len(plan)
    all_points, _cta = _carousel_points(row, brand_voice)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    character: dict = {"used": False, "requested": False, "reference": "", "reason": ""}
    for index, slide in enumerate(plan, start=1):
        footer = (
            f"{row.get('platform', '')} · {row.get('format', '')} · {index} / {total}"
        ).strip(" ·")
        if index == 1 and plate_path is not None:
            img = _plate_base(plate_path, (width, height))
            if style == "concept":
                _concept_treatment(img, row, brand_voice, headline=headline)
            else:
                _scene_treatment(img, row, brand_voice, footer_text=footer)
        else:
            img = Image.new("RGB", (width, height), assets["background_rgb"])
            draw = ImageDraw.Draw(img)
            draw.rectangle([0, 0, width, 150], fill=assets["primary_rgb"])
            draw.text(
                (60, 45),
                assets["brand_name"],
                font=_font(64),
                fill=(255, 255, 255),
            )
            body_font, body_lines = _fit(draw, slide["text"], 64, width - 120, 8)
            y = 230
            for line in body_lines:
                draw.text((60, y), line, font=body_font, fill=assets["ink_rgb"])
                y += 84
            if slide["kind"] == "hook" and row.get("angle"):
                angle_font, angle_lines = _fit(draw, row["angle"], 44, width - 120, 4)
                y += 24
                for line in angle_lines:
                    if y > height - 420:
                        break
                    draw.text((60, y), line, font=angle_font, fill=assets["primary_rgb"])
                    y += 60
            draw.rectangle([0, height - 110, width, height], fill=assets["accent_rgb"])
            draw.text((60, height - 82), footer, font=_font(40), fill=assets["ink_rgb"])
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
        "wordmark": assets["brand_name"],
        "primary": assets["primary"],
        "headline": row.get("topic", ""),
        "path": str(paths[0]),
        "slides": [str(p) for p in paths],
        "slides_truncated": len(all_points) > CAROUSEL_POINT_LIMIT,
        "points_total": len(all_points),
        "character": character,
    }
    if plate_path is not None:
        manifest["style"] = style
        manifest["plate"] = {"used": True, "reason": ""}
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

    assets = resolve_assets(brand_voice)
    width, height = CHARACTER_SHEET_SIZE
    sheet = Image.new("RGB", (width, height), assets["background_rgb"])
    draw = ImageDraw.Draw(sheet)
    draw.rectangle([0, 0, width, 150], fill=assets["primary_rgb"])
    name = (brand_voice or {}).get("character_name", "") or "PaCo"
    draw.text(
        (60, 45),
        f"{assets['brand_name']} · {name} character sheet",
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
    badge_panel = Image.new("RGB", (panel_size, panel_size), assets["background_rgb"])
    _composite_character_badge(
        badge_panel, resolved, diameter=440, x=40, y=40, accent_rgb=assets["accent_rgb"]
    )
    panels.append(("Badge", badge_panel))
    for i, (label, panel) in enumerate(panels):
        px = 60 + i * (panel_size + 60)
        draw.rectangle(
            [px - 3, panel_y - 3, px + panel_size + 3, panel_y + panel_size + 3],
            outline=assets["primary_rgb"],
            width=3,
        )
        sheet.paste(panel, (px, panel_y))
        draw.text(
            (px, panel_y + panel_size + 28),
            label,
            font=_font(44),
            fill=assets["ink_rgb"],
        )

    rules = (brand_voice or {}).get("character_rules", "")
    if rules:
        rules_font, rules_lines = _fit(draw, rules, 36, width - 120, 3)
        y = 950
        for line in rules_lines:
            draw.text((60, y), line, font=rules_font, fill=assets["primary_rgb"])
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
        primary_hex = manifest.get("primary")
        primary_rgb = _hex_to_rgb(primary_hex) if primary_hex else ASSETS["primary_rgb"]
        found = any(
            rgb.getpixel((x, y)) == primary_rgb
            for x in range(0, img.size[0], 60)
            for y in range(0, 120, 10)
        )
        if not found:
            return False, "brand primary colour absent from the top band"
    return True, (
        f"template={manifest['template']} size={manifest['size']} "
        f"wordmark={manifest['wordmark']} primary-colour=present"
    )


def produce_visual(store, row: dict, image_client=None, director=None) -> dict:
    """Produce + self-check the visual for a drafted row; store its path.

    Refuses rows without a final draft: visuals are built from the
    Copywriter's finished text, never before it exists.

    When a director and an image client are both supplied, the
    visual is directed and generated in the row's visual style
    (see direct_plate): the manifest records the concept (style,
    concept line, prompt, and for concept style the no-exceptions
    line) and the plate outcome. Any failure in direction,
    generation or plate rendering falls back to the brand template
    render, recorded in the manifest's plate dict; a plate failure
    never fails the row. Without both clients (mock mode) the
    template render runs exactly as before.
    """
    if not (row.get("draft") or "").strip():
        raise ValueError("no draft on the row: visuals follow the final draft")
    brand_voice = store.get_brand_voice()
    out_dir = store.data_dir / "visuals"
    out_dir.mkdir(parents=True, exist_ok=True)
    concept: dict | None = None
    plate: dict = {"used": False, "reason": "no image client or director configured"}
    plate_path: Path | None = None
    if image_client is not None and director is not None:
        concept, plate, plate_path = direct_plate(
            row, brand_voice, out_dir, director, image_client
        )
    style = visual_style_for(row)
    headline = (concept or {}).get("headline") or None
    if plate_path is None:
        # The plain template call, exactly the shape it has always
        # had: the plate kwargs only enter the call when a plate
        # actually exists.
        path, manifest = render_visual(row, out_dir, brand_voice=brand_voice)
    else:
        try:
            path, manifest = render_visual(
                row,
                out_dir,
                brand_voice=brand_voice,
                plate_path=plate_path,
                style=style,
                headline=headline,
            )
        except Exception as exc:
            plate = {"used": False, "reason": f"plate rendering failed: {exc}"}
            path, manifest = render_visual(row, out_dir, brand_voice=brand_voice)
    if concept is not None:
        manifest["concept"] = concept
    manifest["plate"] = plate
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
