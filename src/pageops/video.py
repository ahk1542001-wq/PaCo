"""Video production (Department 1, Visuals stage): short videos.

The production pattern is script, storyboard, frames, assembly,
then QA. The Copywriter's draft is the script. The storyboard is
split deterministically from it. Scene frames are rendered with
PIL in the brand style: all text is rendered in post by this code,
never by a generation model. Assembly is FFmpeg (a gentle zoompan
over the frames, the final scene as the end card). QA is ffprobe:
duration and dimensions are verified before the video is stored.

The video never replaces the poster: the row's visual stays the
poster, and the mp4 path is recorded on the row's video field.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from .checker import check_character
from .designer import (
    ASSETS,
    _apply_character,
    _badge_placement,
    _fit,
    _font,
    cta_sentence,
    split_points,
)

VIDEO_SIZE: tuple[int, int] = (1080, 1920)
FPS = 30


def seconds_per_scene() -> float:
    """Scene length from the environment knob, default 2.0 seconds.

    PAGEOPS_VIDEO_SECONDS_PER_SCENE lets tests and proof runs keep
    assembly fast without changing the production default.
    """
    try:
        value = float(os.environ.get("PAGEOPS_VIDEO_SECONDS_PER_SCENE", "2.0"))
    except ValueError:
        value = 2.0
    if not math.isfinite(value):
        value = 2.0
    return min(30.0, max(0.2, value))


def storyboard_for(row: dict, brand_voice: dict | None = None) -> list[dict]:
    """Split the row's draft into a storyboard of up to 4 scenes.

    Scene 1 is the hook (the topic). The middle scenes are the
    draft's points (see designer.split_points). The final scene is
    the call to action and serves as the end card: the draft's own
    CTA sentence when it has one, else the standing brand CTA line.
    Deterministic: the same draft always yields the same storyboard.
    """
    draft = row.get("draft", "")
    cta = cta_sentence(draft, brand_voice)
    points = [p for p in split_points(draft) if p != cta]
    scenes: list[dict] = [{"index": 1, "kind": "hook", "text": row.get("topic", "")}]
    for point in points[:2]:
        scenes.append({"index": len(scenes) + 1, "kind": "point", "text": point})
    scenes.append(
        {
            "index": len(scenes) + 1,
            "kind": "cta",
            "text": cta or "Message us to get started.",
        }
    )
    return scenes


def render_scene_frame(
    scene: dict, row: dict, out_dir: Path | str, brand_voice: dict | None = None
) -> tuple[Path, dict]:
    """Render one vertical scene frame (1080x1920) in the brand style.

    Returns the frame path and the manifest character dict for the
    frame. The character badge rides on the hook and end-card
    scenes when the row calls for it (the same placement family as
    the other formats). The end card is set on the primary colour.
    """
    width, height = VIDEO_SIZE
    is_end_card = scene.get("kind") == "cta"
    background = ASSETS["primary_rgb"] if is_end_card else ASSETS["background_rgb"]
    img = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(img)
    if is_end_card:
        draw.text(
            (60, 120),
            ASSETS["brand_name"],
            font=_font(88),
            fill=(255, 255, 255),
        )
        text_fill = (255, 255, 255)
        y = 420
    else:
        draw.rectangle([0, 0, width, 200], fill=ASSETS["primary_rgb"])
        draw.text(
            (60, 62),
            ASSETS["brand_name"],
            font=_font(72),
            fill=(255, 255, 255),
        )
        text_fill = ASSETS["ink_rgb"]
        y = 340
    body_font, body_lines = _fit(draw, scene.get("text", ""), 84, width - 120, 10)
    for line in body_lines:
        draw.text((60, y), line, font=body_font, fill=text_fill)
        y += 108
    draw.rectangle([0, height - 140, width, height], fill=ASSETS["accent_rgb"])
    footer = f"{row.get('platform', '')} · {row.get('format', '')}".strip(" ·")
    draw.text((60, height - 102), footer, font=_font(44), fill=ASSETS["ink_rgb"])

    character: dict = {"used": False, "requested": False, "reference": "", "reason": ""}
    if scene.get("kind") in ("hook", "cta"):
        diameter, badge_x, badge_y = _badge_placement(width, height, footer=140)
        character = _apply_character(
            img, row, brand_voice, diameter=diameter, x=badge_x, y=badge_y
        )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"video-{row.get('id', 'row')}-frame-{scene.get('index', 0)}.png"
    img.save(path)
    return path, character


def assemble_video(
    frames: list[Path | str], out_path: Path | str, seconds: float
) -> Path:
    """Assemble scene frames into an mp4 with FFmpeg.

    Each frame gets a gentle zoompan for the scene's length at
    30fps; scenes are joined with simple cuts. The final frame is
    the storyboard's end card, so it closes the video.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("video assembly failed: ffmpeg not available")
    frames = [Path(f) for f in frames]
    if not frames:
        raise RuntimeError("video assembly failed: no scene frames")
    for frame in frames:
        if not frame.exists():
            raise RuntimeError(f"video assembly failed: frame missing: {frame}")
    per_scene = max(1, round(seconds * FPS))
    inputs: list[str] = []
    for frame in frames:
        inputs += ["-i", str(frame)]
    filters = []
    for i in range(len(frames)):
        filters.append(
            f"[{i}:v]scale={VIDEO_SIZE[0]}:{VIDEO_SIZE[1]},"
            f"zoompan=z='min(zoom+0.0012,1.10)':x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':d={per_scene}:s={VIDEO_SIZE[0]}x{VIDEO_SIZE[1]}"
            f":fps={FPS}[v{i}]"
        )
    concat = "".join(f"[v{i}]" for i in range(len(frames))) + (
        f"concat=n={len(frames)}:v=1:a=0[out]"
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", *inputs,
        "-filter_complex", ";".join(filters + [concat]),
        "-map", "[out]",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        str(out),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"video assembly failed: {exc}") from exc
    if result.returncode != 0:
        tail = (result.stderr or "").strip()[-300:]
        raise RuntimeError(f"video assembly failed: ffmpeg exited {result.returncode}: {tail}")
    return out


def _as_int(value) -> int:
    """Coerce an ffprobe dimension to int; non-numeric becomes 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def qc_video(path: Path | str) -> dict:
    """Verify an assembled video with ffprobe.

    Returns {duration, width, height, has_video, valid}. A video is
    valid only with a real video stream, a positive duration and
    exactly the vertical scene dimensions (1080x1920).
    """
    result = {"duration": 0.0, "width": 0, "height": 0, "has_video": False, "valid": False}
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("video QC failed: ffprobe not available")
    path = Path(path)
    if not path.exists():
        return result
    try:
        proc = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-show_entries", "format=duration",
                "-of", "json",
                str(path),
            ],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"video QC failed: {exc}") from exc
    if proc.returncode != 0:
        return result
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return result
    streams = payload.get("streams") or []
    if streams:
        result["has_video"] = True
        result["width"] = _as_int(streams[0].get("width"))
        result["height"] = _as_int(streams[0].get("height"))
    try:
        result["duration"] = float((payload.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        result["duration"] = 0.0
    result["valid"] = bool(
        result["has_video"]
        and result["duration"] > 0
        and (result["width"], result["height"]) == VIDEO_SIZE
    )
    return result


def produce_video(store, row: dict) -> tuple[Path, dict]:
    """Produce + QC the short video for a drafted row; store its path.

    Mirrors designer.produce_visual: refuses rows without a final
    draft, and every failure raises with a clear reason (ValueError
    for the missing draft, RuntimeError for production failures),
    so the pipeline flags the row exactly like a visual failure.
    Returns (mp4 path, manifest) with scenes, frames and the QC
    record.
    """
    if not (row.get("draft") or "").strip():
        raise ValueError("no draft on the row: videos follow the final draft")
    brand_voice = store.get_brand_voice()
    out_dir = store.data_dir / "visuals"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Prune this row's stale scene frames, so a shorter re-run
    # leaves no orphan frames from an earlier, longer storyboard.
    for stale in out_dir.glob(f"video-{row.get('id', 'row')}-frame-*.png"):
        stale.unlink(missing_ok=True)
    scenes = storyboard_for(row, brand_voice)
    frames: list[Path] = []
    character: dict = {"used": False, "requested": False, "reference": "", "reason": ""}
    for scene in scenes:
        frame, frame_character = render_scene_frame(scene, row, out_dir, brand_voice)
        frames.append(frame)
        if scene["index"] == 1:
            character = frame_character
    # The Brand Checker's character rule, applied to the storyboard
    # exactly as produce_visual applies it to the poster manifest.
    character_result = check_character(row, {"character": character}, brand_voice)
    if not character_result.passed:
        raise RuntimeError(f"character check failed: {character_result.summary()}")
    seconds = seconds_per_scene()
    out_path = out_dir / f"video-{row.get('id', 'row')}.mp4"
    # Non-atomic output guard: assemble and QC a temp file in the
    # same directory, and only replace the final mp4 on success,
    # so a failed re-run never destroys a previously good video.
    tmp_path = out_dir / f"video-{row.get('id', 'row')}.tmp.mp4"
    try:
        assemble_video(frames, tmp_path, seconds)
        qc = qc_video(tmp_path)
        if not qc["valid"]:
            raise RuntimeError(
                "video QC failed: "
                f"duration={qc['duration']} size={qc['width']}x{qc['height']} "
                f"has_video={qc['has_video']}"
            )
        os.replace(tmp_path, out_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    manifest = {
        "scenes": scenes,
        "frames": [str(f) for f in frames],
        "qc": qc,
        "path": str(out_path),
        "seconds_per_scene": seconds,
        "character": character,
    }
    relative = out_path.relative_to(store.data_dir)
    store.update_row("plan", row["id"], {"video": str(relative)})
    return out_path, manifest
