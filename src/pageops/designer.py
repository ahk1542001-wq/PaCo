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

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .checker import check_character

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
}

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
    return "thumb" if "thumb" in fmt else "poster"


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


def _composite_character_badge(img: Image.Image, reference_path: Path) -> bool:
    """Composite the reference image as a circular badge, in place.

    The reference is only ever cropped to a circle and ringed with
    the brand accent colour; it is never redrawn or restyled.
    Placed bottom-right, just above the footer band, at about 22%
    of the poster width.

    Returns True when the badge was composited. A reference that
    exists but cannot be read as an image (truncated, not an image
    at all) returns False instead of raising: the caller records
    "reference unreadable" and the checker fails the row cleanly,
    exactly like the missing-reference path.
    """
    width, height = img.size
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
    x = width - diameter - 48
    y = height - 110 - diameter - 36
    draw = ImageDraw.Draw(img)
    draw.ellipse(
        [x - ring, y - ring, x + diameter + ring, y + diameter + ring],
        fill=ASSETS["accent_rgb"],
    )
    img.paste(badge, (x, y), mask)
    return True


def render_visual(
    row: dict, out_dir: Path | str, brand_voice: dict | None = None
) -> tuple[Path, dict]:
    """Render the row's visual from its template. Deterministic."""
    template = template_for(row)
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

    # Brand character badge, only when the row calls for it and the
    # brand's reference image actually exists. A missing or
    # unreadable reference is recorded in the manifest, never
    # fabricated or silently dropped. The manifest character dict
    # always carries the same four keys.
    character: dict = {"used": False, "requested": False, "reference": "", "reason": ""}
    if str(row.get("character") or "").strip().lower() == "yes":
        reference = (brand_voice or {}).get("character_image", "")
        resolved = _resolve_character_reference(reference)
        if resolved is None:
            character = {
                "used": False,
                "requested": True,
                "reference": reference,
                "reason": "reference missing",
            }
        elif _composite_character_badge(img, resolved):
            character = {
                "used": True,
                "requested": True,
                "reference": reference,
                "reason": "",
            }
        else:
            character = {
                "used": False,
                "requested": True,
                "reference": reference,
                "reason": "reference unreadable",
            }

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = f"visual-{row.get('id', 'row')}-{template}.png"
    path = out / name
    img.save(path)
    manifest = {
        "template": template,
        "size": (width, height),
        "wordmark": ASSETS["brand_name"],
        "headline": row.get("topic", ""),
        "path": str(path),
        "character": character,
    }
    return path, manifest


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
