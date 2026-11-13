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


def _emphasis_words(text: str, emphasis: str) -> set[int]:
    """Indices of the words of `text` covered by the emphasis phrase.

    The director copies the emphasis phrase exactly from the
    headline, so a contiguous run of words matches; anything else
    (missing phrase, reordered words) marks nothing rather than
    guessing.
    """
    words = text.split()
    target = (emphasis or "").split()
    if not target or len(target) > len(words):
        return set()
    for start in range(len(words) - len(target) + 1):
        if words[start : start + len(target)] == target:
            return set(range(start, start + len(target)))
    return set()


def _rich_lines(draw, text: str, emphasis: str, font, max_width: int):
    """Wrap a headline into lines of (word, is_emphasis) segments."""
    words = text.split()
    marked = _emphasis_words(text, emphasis)
    lines: list[list[tuple[str, bool]]] = []
    current: list[tuple[str, bool]] = []
    current_width = 0.0
    space = draw.textlength(" ", font=font)
    for i, word in enumerate(words):
        w = draw.textlength(word, font=font)
        trial = current_width + (space if current else 0) + w
        if current and trial > max_width:
            lines.append(current)
            current, current_width = [], 0.0
            trial = w
        current.append((word, i in marked))
        current_width = trial
    if current:
        lines.append(current)
    return lines


def _fit_rich(draw, text: str, emphasis: str, start: int, max_width: int, max_lines: int):
    """Largest font (from `start` down) whose rich wrap fits max_lines."""
    size = start
    while size > 30:
        font = _font(size)
        lines = _rich_lines(draw, text, emphasis, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
        size -= 6
    font = _font(30)
    return font, _rich_lines(draw, text, emphasis, font, max_width)[:max_lines]


def _draw_rich_headline(
    draw, lines, x: int, y: int, font, base_fill, chip_fill, chip_text_fill,
    *, shadow: bool = False,
) -> int:
    """Draw wrapped headline lines with emphasis words on highlight
    chips. Returns the y below the block. Type is designed here:
    the key phrase sits on a solid accent chip, never just typed.
    """
    space = draw.textlength(" ", font=font)
    step = font.size + int(font.size * 0.35)
    for line in lines:
        cx = x
        for word, hot in line:
            w = draw.textlength(word, font=font)
            if hot:
                draw.rounded_rectangle(
                    [cx - 9, y - 5, cx + w + 9, y + font.size + 9],
                    radius=12,
                    fill=chip_fill,
                )
                if shadow:
                    draw.text((cx + 2, y + 2), word, font=font, fill=(10, 18, 38))
                draw.text((cx, y), word, font=font, fill=chip_text_fill)
            else:
                if shadow:
                    draw.text((cx + 3, y + 3), word, font=font, fill=(10, 18, 38))
                draw.text((cx, y), word, font=font, fill=base_fill)
            cx += w + space
        y += step
    return y


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
    """The row's visual style: "scene", "concept", "promo" or "showcase".

    Rows planned before the field existed (and rows whose planner
    left it blank) default to "scene", and any unrecognised value
    resolves to "scene" as well: the default is always the safe,
    full-treatment style.
    """
    style = str(row.get("visual_style") or "scene").strip().lower()
    return style if style in ("scene", "concept", "promo", "showcase") else "scene"


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
    concept: dict = {
        "style": style,
        "concept": "",
        "prompt": "",
        "no_exceptions": "",
        "headline": "",
        "emphasis": "",
    }
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
            "headline": str(directed.get("headline", "")),
            "emphasis": str(directed.get("emphasis", "")),
            "features": _clean_features(directed.get("features")),
            "price_line": str(directed.get("price_line") or "").strip(),
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


def product_logos_for(row: dict, brand_voice: dict | None) -> list[tuple[str, str]]:
    """Every product a row sells whose logo the brand supplied.

    The brand key ``product_logos`` holds "slug: relative/path.png"
    pairs (';'-separated, paths relative to the store's visuals
    folder). A row matches a product when the slug appears in its
    topic or angle — the plan's subject fields. The draft is NOT
    matched: a passing mention in a caption (an intro post listing
    what the shop sells) is not the post's product, and badging it
    would mislabel the post. Returns (slug, relative path) pairs
    in brand-key order — a post selling two products is badged
    with BOTH logos, because viewers identify a product by its
    real logo, never by typed text alone (owner rule, 2026-11-13).
    """
    raw = str((brand_voice or {}).get("product_logos") or "").strip()
    if not raw:
        return []
    haystack = f"{row.get('topic', '')} {row.get('angle', '')}".lower()
    found = []
    for pair in raw.split(";"):
        slug, sep, rel = pair.partition(":")
        slug, rel = slug.strip().lower(), rel.strip()
        if sep and slug and rel and slug in haystack:
            found.append((slug, rel))
    return found


def product_logo_for(row: dict, brand_voice: dict | None) -> tuple[str, str] | None:
    """The first product a row sells (see product_logos_for)."""
    found = product_logos_for(row, brand_voice)
    return found[0] if found else None


def _product_badge(logo_path: Path) -> Image.Image | None:
    """A white rounded badge carrying a product logo, or None.

    The badge is a designed element (soft shadow, generous
    padding), sized to the logo's own aspect: selling visuals show
    WHICH product they sell, integrated with the composition
    rather than stamped on it.
    """
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except OSError:
        return None
    badge_h = 84
    inner_h = badge_h - 24
    scale = inner_h / max(1, logo.height)
    logo_w = max(1, int(logo.width * scale))
    logo = logo.resize((logo_w, inner_h))
    badge_w = logo_w + 32
    badge = Image.new("RGBA", (badge_w + 16, badge_h + 16), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    bd.rounded_rectangle([8, 11, badge_w + 8, badge_h + 11], radius=20, fill=(0, 0, 0, 90))
    bd.rounded_rectangle([4, 4, badge_w + 4, badge_h + 4], radius=20, fill=(255, 255, 255, 255))
    badge.alpha_composite(logo, (20, 16))
    return badge


def _product_badge_row(logo_paths) -> Image.Image | None:
    """One badge strip carrying every product logo, or None.

    A single logo keeps the plain badge; several are joined
    side by side with a small gap, each visual box starting
    where the previous one ended, so the strip's width minus
    its padding equals the joined visual width — the same
    geometry contract the treatments already use for one badge.
    Missing or unreadable files are skipped; no readable logo
    at all returns None.
    """
    badges = []
    for path in logo_paths or []:
        badge = _product_badge(Path(path))
        if badge is not None:
            badges.append(badge)
    if not badges:
        return None
    if len(badges) == 1:
        return badges[0]
    gap = 12
    visuals = [b.width - 16 for b in badges]
    strip = Image.new(
        "RGBA", (sum(visuals) + gap * (len(badges) - 1) + 16, badges[0].height),
        (0, 0, 0, 0),
    )
    x = 0
    for badge, visual in zip(badges, visuals):
        strip.alpha_composite(badge, (x, 0))
        x += visual + gap
    return strip


def _badges_for(product_logo) -> Image.Image | None:
    """Badge image for a Path, a list of Paths, or None."""
    if product_logo is None:
        return None
    if isinstance(product_logo, (list, tuple)):
        return _product_badge_row(list(product_logo))
    return _product_badge(Path(product_logo))


def _concept_treatment(
    img: Image.Image,
    row: dict,
    brand_voice: dict | None = None,
    headline: str | None = None,
    product_logo: Path | None = None,
    emphasis: str | None = None,
) -> None:
    """Concept style over a plate: one metaphor, arranged type.

    Elements: the brand wordmark chip (top-left), the headline,
    and — on a selling post — the product's logo on a white badge
    (top-right). The headline is ARRANGED into the frame, never
    just stamped on it: direction reserves the top band of the
    plate as a dark, empty headline zone, a soft gradient scrim in
    the brand primary grows that zone out of the image itself (no
    hard band, no pasted panel), and the director's short headline
    is fitted into the zone over up to two lines. There is NO
    fallback to the draft's sentences: a concept poster either
    carries the director's designed line or carries no headline at
    all — a stamped caption sentence is exactly what this style
    exists to avoid.
    """
    assets = resolve_assets(brand_voice)
    badge = _badges_for(product_logo)
    badge_w = badge.width - 16 if badge is not None else 0
    text = (headline or "").strip()
    headline_lines: list[str] = []
    headline_font = None
    if text:
        draw = ImageDraw.Draw(img)
        reserve = badge_w + 24 if badge is not None else 0
        headline_font, headline_lines = _fit_rich(
            draw, text, emphasis or "", 84, img.width - 120 - reserve, 2
        )
        # The scrim is sized to the block it carries (the scene
        # treatment's rule: type never runs off its ground), then
        # fades out well above the metaphor.
        step = headline_font.size + int(headline_font.size * 0.35)
        block_bottom = 150 + step * len(headline_lines) + 46
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
    if headline_lines:
        _draw_rich_headline(
            draw, headline_lines, 60, 150, headline_font,
            (255, 255, 255), assets["accent_rgb"], assets["primary_rgb"],
            shadow=True,
        )
    if badge is not None:
        img.paste(badge, (img.width - 44 - badge_w - 4, 34), badge)


def _clean_features(raw) -> list[str]:
    """Feature labels as the poster can carry them: at most three,
    at most 24 characters, no trailing ellipses or dangling
    connectors — a truncated label on a poster is a defect, so the
    label is cut at a word boundary instead of mid-thought."""
    out: list[str] = []
    for item in raw or []:
        text = str(item).strip().rstrip(".…").strip().rstrip("+·,-").strip()
        if not text:
            continue
        if len(text) > 24:
            cut = text[:24].rsplit(" ", 1)[0].rstrip("+·,-").strip()
            text = cut or text[:24]
        if text:
            out.append(text)
    return out[:3]


def _feature_icon(draw, cx: int, cy: int, index: int, colour) -> None:
    """One small feature glyph in a ring: star, play, envelope —
    the quiet icon row of a designed product poster, drawn in code
    so it stays crisp at any size."""
    r = 26
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=3)
    if index % 3 == 0:
        # star
        import math

        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rad = 13 if i % 2 == 0 else 6
            pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
        draw.polygon(pts, fill=colour)
    elif index % 3 == 1:
        # play triangle
        draw.polygon(
            [(cx - 7, cy - 10), (cx - 7, cy + 10), (cx + 11, cy)], fill=colour
        )
    else:
        # envelope
        draw.rectangle([cx - 13, cy - 9, cx + 13, cy + 9], outline=colour, width=3)
        draw.line([(cx - 13, cy - 9), (cx, cy + 2), (cx + 13, cy - 9)], fill=colour, width=3)


def _showcase_treatment(
    img: Image.Image,
    row: dict,
    brand_voice: dict | None = None,
    headline: str | None = None,
    emphasis: str | None = None,
    features: list | None = None,
    price_line: str | None = None,
    product_logo: Path | None = None,
) -> None:
    """Showcase style over a plate: the product hero floating over
    a split brand-colour field, with the selling information set
    into a designed podium at the foot.

    The plate (directed, generated) carries the product as one
    huge floating object in the upper frame over a diagonal
    two-tone split in the brand colours; its lower third stays
    empty. The treatment adds: the brand wordmark chip (top-left),
    the product's real logo badge (top-right), the stacked rich
    headline over a soft local scrim, and a solid podium — a
    primary-colour plinth with a lighter elliptical top surface
    and an accent rim — carrying the price set large, one quiet
    icon row of up to three selling features, and the brand name
    as its signature. Facts come only from the director's read of
    the finished draft. It is neither an abstract metaphor (the
    product IS the picture) nor a product card (no checklist, no
    spec sheet: three features, subordinate, in one row).
    """
    assets = resolve_assets(brand_voice)
    badge = _badges_for(product_logo)
    badge_w = badge.width - 16 if badge is not None else 0
    width, height = img.width, img.height
    # Soft local scrim behind the headline only: the headline zone
    # darkens, the hero above it stays clean.
    head_top = int(height * 0.44)
    plinth_top = int(height * 0.70)
    mask = Image.new("L", (1, height), 0)
    for y in range(height):
        if y < head_top:
            alpha = 0
        elif y < plinth_top:
            alpha = int(150 * ((y - head_top) / max(1, plinth_top - head_top)) ** 0.7)
        else:
            alpha = 0
        mask.putpixel((0, y), alpha)
    img.paste(
        Image.new("RGB", img.size, assets["primary_rgb"]), (0, 0), mask.resize(img.size)
    )
    draw = ImageDraw.Draw(img)
    wordmark_font = _font(48)
    wordmark_width = draw.textlength(assets["brand_name"], font=wordmark_font)
    draw.rectangle(
        [44, 38, 44 + wordmark_width + 48, 114],
        fill=assets["primary_rgb"],
        outline=assets["accent_rgb"],
        width=3,
    )
    draw.text(
        (68, 52), assets["brand_name"], font=wordmark_font, fill=(255, 255, 255)
    )
    if badge is not None:
        img.paste(badge, (img.width - 44 - badge_w - 4, 34), badge)
        draw = ImageDraw.Draw(img)
    text = (headline or "").strip()
    if text:
        font, lines = _fit_rich(draw, text, emphasis or "", 88, width - 120, 2)
        # The headline block must END above the podium: measure it
        # (line step + glyph depth + Burmese below-marks) and pull
        # the whole block up until it clears the plinth, instead of
        # letting the podium's rim cut the last line.
        step = font.size + int(font.size * 0.35)
        block_depth = (
            (len(lines) - 1) * step + font.size + int(font.size * 0.30) + 12
        )
        y = min(int(height * 0.50), plinth_top - block_depth - 56)
        _draw_rich_headline(
            draw, lines, 60, y, font,
            (255, 255, 255), assets["accent_rgb"], assets["primary_rgb"],
            shadow=True,
        )
    # The podium: a solid plinth whose top surface catches the
    # light. Body first, then the elliptical top, then its rim.
    primary = assets["primary_rgb"]
    top_fill = tuple(min(255, int(c + (255 - c) * 0.30)) for c in primary)
    ry = int(height * 0.030)
    draw.rectangle([0, plinth_top, width, height], fill=primary)
    # The top surface sits INSIDE the frame with visible side
    # margins, so the plinth reads as an object, not a lid.
    ex0, ex1 = int(width * 0.03), width - int(width * 0.03)
    draw.ellipse([ex0, plinth_top - ry, ex1, plinth_top + ry], fill=top_fill)
    draw.arc(
        [ex0, plinth_top - ry, ex1, plinth_top + ry],
        start=0, end=180, fill=assets["accent_rgb"], width=4,
    )
    # Selling block ON the podium: price large, features one row.
    py = plinth_top + int(height * 0.030)
    price = (price_line or "").strip()
    if price:
        pfont, plines = _fit(draw, price, 76, width - 160, 1)
        plabel = plines[0] if plines else price
        pw = draw.textlength(plabel, font=pfont)
        draw.text(
            ((width - pw) / 2, py), plabel,
            font=pfont, fill=(255, 255, 255),
        )
        py += pfont.size + int(height * 0.036)
    feats = _clean_features(features)
    if feats:
        col_w = (width - 80) // len(feats)
        for i, feat in enumerate(feats):
            cx = 40 + col_w * i + col_w // 2
            _feature_icon(draw, cx, py, i, assets["accent_rgb"])
            lfont, llines = _fit(draw, feat, 31, col_w - 24, 1)
            label = llines[0] if llines else feat
            lw = draw.textlength(label, font=lfont)
            draw.text(
                (cx - lw / 2, py + 42), label,
                font=lfont, fill=(255, 255, 255),
            )
    # Signature on the podium's face.
    foot_font = _font(36)
    foot = assets["brand_name"]
    fw = draw.textlength(foot, font=foot_font)
    draw.text(
        ((width - fw) / 2, height - 58), foot,
        font=foot_font, fill=(215, 228, 216),
    )


def _render_plate_single(
    row: dict,
    out_dir: Path | str,
    brand_voice: dict | None,
    plate_path: Path,
    style: str,
    template: str,
    headline: str | None = None,
    emphasis: str | None = None,
    features: list | None = None,
    price_line: str | None = None,
) -> tuple[Path, dict]:
    """One still visual rendered over a generated plate."""
    width, height = TEMPLATES[template]
    img = _plate_base(plate_path, (width, height))
    slugs, paths = [], []
    for slug, rel in product_logos_for(row, brand_voice):
        candidate = Path(out_dir) / rel
        if candidate.exists():
            slugs.append(slug)
            paths.append(candidate)
    product_slug = ",".join(slugs)
    product_path = paths or None
    if style == "concept":
        _concept_treatment(
            img, row, brand_voice, headline=headline,
            product_logo=product_path, emphasis=emphasis,
        )
        diameter, badge_x, badge_y = _badge_placement(width, height)
    elif style == "showcase":
        _showcase_treatment(
            img, row, brand_voice, headline=headline, emphasis=emphasis,
            features=features, price_line=price_line,
            product_logo=product_path,
        )
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
        "product_logo": product_slug,
    }
    return path, manifest


def _render_promo(
    row: dict,
    out_dir: Path | str,
    brand_voice: dict | None,
    direction: dict,
) -> tuple[Path, dict]:
    """Promo style: a bright direct-response poster composed from
    brand assets. No generated plate: the light brand background,
    the offer as the headline, the product's real logo large on a
    white tile, short benefit lines with ticks, the price set big,
    and a primary brand band at the foot. Every fact on the poster
    comes from the director's read of the finished draft; the
    composition is deterministic code, so the words are exactly the
    approved ones. The tick green is a functional colour, the same
    in every brand's promo posters.
    """
    from PIL import ImageFilter

    assets = resolve_assets(brand_voice)
    width, height = TEMPLATES["poster"]
    img = Image.new("RGB", (width, height), assets["background_rgb"])
    draw = ImageDraw.Draw(img)
    draw.polygon([(-40, -40), (320, -40), (-40, 250)], fill=assets["primary_rgb"])
    draw.ellipse(
        [width - 240, height - 430, width + 90, height - 100],
        fill=assets["accent_rgb"],
    )
    # Wordmark chip, the same designed element as the concept style.
    wordmark_font = _font(48)
    wordmark_width = draw.textlength(assets["brand_name"], font=wordmark_font)
    draw.rectangle(
        [44, 38, 44 + wordmark_width + 48, 114],
        fill=assets["primary_rgb"],
        outline=assets["accent_rgb"],
        width=3,
    )
    draw.text(
        (68, 52), assets["brand_name"], font=wordmark_font, fill=(255, 255, 255)
    )
    y = 156
    headline = str(direction.get("headline") or "").strip()
    if headline:
        font, lines = _fit_rich(
            draw, headline, str(direction.get("emphasis") or ""), 104,
            width - 120, 2,
        )
        y = _draw_rich_headline(
            draw, lines, 60, y, font,
            assets["primary_rgb"], assets["accent_rgb"], assets["primary_rgb"],
        ) + 22
    product_slug = ""
    found = product_logo_for(row, brand_voice)
    if found:
        candidate = Path(out_dir) / found[1]
        if candidate.exists():
            product_slug = found[0]
            tile = 430
            tx, ty = (width - tile) // 2, y
            shadow = Image.new("RGBA", (tile, tile), (0, 0, 0, 0))
            ImageDraw.Draw(shadow).rounded_rectangle(
                [6, 14, tile - 6, tile - 2], radius=52, fill=(20, 35, 25, 90)
            )
            shadow = shadow.filter(ImageFilter.GaussianBlur(10))
            img.paste(shadow, (tx, ty), shadow)
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle(
                [tx, ty, tx + tile, ty + tile], radius=52, fill=(255, 255, 255)
            )
            logo = Image.open(candidate).convert("RGBA")
            logo.thumbnail((tile - 70, tile - 70))
            img.paste(
                logo,
                (tx + (tile - logo.width) // 2, ty + (tile - logo.height) // 2),
                logo,
            )
            draw = ImageDraw.Draw(img)
            y += tile + 46
    for raw in (direction.get("benefits") or [])[:4]:
        benefit = str(raw).strip()
        if not benefit:
            continue
        cx, cy = 88, y + 22
        draw.ellipse([cx - 19, cy - 19, cx + 19, cy + 19], fill=(0, 177, 64))
        draw.line(
            [(cx - 8, cy), (cx - 2, cy + 7), (cx + 10, cy - 8)],
            fill=(255, 255, 255),
            width=5,
            joint="curve",
        )
        bfont, blines = _fit(draw, benefit, 41, width - 200, 1)
        draw.text(
            (128, y), blines[0] if blines else benefit,
            font=bfont, fill=assets["primary_rgb"],
        )
        y += 62
    price = str(direction.get("price_line") or "").strip()
    if price:
        y += 8
        pfont, plines = _fit(draw, price, 92, width - 120, 1)
        draw.text(
            (60, y), plines[0] if plines else price,
            font=pfont, fill=assets["primary_rgb"],
        )
        y += pfont.size + 16
    draw.rectangle([0, height - 110, width, height], fill=assets["primary_rgb"])
    draw.text(
        (60, height - 78), assets["brand_name"],
        font=_font(44), fill=(255, 255, 255),
    )
    diameter, badge_x, badge_y = _badge_placement(width, height)
    character = _apply_character(
        img, row, brand_voice, diameter=diameter, x=badge_x, y=badge_y
    )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"visual-{row.get('id', 'row')}-poster.png"
    img.save(path)
    manifest = {
        "template": "poster",
        "format": "poster",
        "size": (width, height),
        "wordmark": assets["brand_name"],
        "primary": assets["primary"],
        "headline": row.get("topic", ""),
        "path": str(path),
        "character": character,
        "style": "promo",
        "plate": {"used": False, "reason": "promo style composes from brand assets"},
        "product_logo": product_slug,
    }
    return path, manifest


def render_visual(
    row: dict,
    out_dir: Path | str,
    brand_voice: dict | None = None,
    plate_path: Path | str | None = None,
    style: str = "scene",
    headline: str | None = None,
    emphasis: str | None = None,
    features: list | None = None,
    price_line: str | None = None,
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
            row, out_dir, brand_voice, Path(plate_path), style, template,
            headline=headline, emphasis=emphasis,
            features=features, price_line=price_line,
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
    product_slug = ""
    character: dict = {"used": False, "requested": False, "reference": "", "reason": ""}
    for index, slide in enumerate(plan, start=1):
        footer = (
            f"{row.get('platform', '')} · {row.get('format', '')} · {index} / {total}"
        ).strip(" ·")
        if index == 1 and plate_path is not None:
            img = _plate_base(plate_path, (width, height))
            if style == "concept":
                logo_paths = []
                for slug, rel in product_logos_for(row, brand_voice):
                    candidate = out / rel
                    if candidate.exists():
                        product_slug = ",".join(
                            [product_slug, slug]) if product_slug else slug
                        logo_paths.append(candidate)
                _concept_treatment(
                    img, row, brand_voice, headline=headline,
                    product_logo=logo_paths or None,
                )
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
        manifest["product_logo"] = product_slug
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
    style = visual_style_for(row)
    concept: dict | None = None
    plate: dict = {"used": False, "reason": "no image client or director configured"}
    plate_path: Path | None = None
    promo_path: Path | None = None
    promo_manifest: dict | None = None
    if style == "promo" and director is not None:
        # Promo composes from brand assets: direction only, never a
        # generated plate. Any failure falls through to the normal
        # directed/template flow below, recorded as before.
        try:
            direction = director.direct_visual(
                row, row.get("draft", ""), brand_voice or {}, "promo"
            )
            if not isinstance(direction, dict) or not str(
                direction.get("headline") or ""
            ).strip():
                raise ValueError("promo direction missing headline")
            promo_path, promo_manifest = _render_promo(
                row, out_dir, brand_voice, direction
            )
            concept = {
                "style": "promo",
                "concept": str(direction.get("concept", "")),
                "prompt": "",
                "no_exceptions": "",
                "headline": str(direction.get("headline", "")),
                "emphasis": str(direction.get("emphasis", "")),
            }
            plate = {
                "used": False,
                "reason": "promo style composes from brand assets; no generated plate",
            }
        except Exception:
            promo_path, promo_manifest = None, None
    if promo_path is not None and promo_manifest is not None:
        path, manifest = promo_path, promo_manifest
    else:
        if image_client is not None and director is not None:
            concept, plate, plate_path = direct_plate(
                row, brand_voice, out_dir, director, image_client
            )
        headline = (concept or {}).get("headline") or None
        if plate_path is None:
            # The plain template call, exactly the shape it has
            # always had: the plate kwargs only enter the call when
            # a plate actually exists.
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
                    emphasis=(concept or {}).get("emphasis") or None,
                    features=(concept or {}).get("features") or None,
                    price_line=(concept or {}).get("price_line") or None,
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
