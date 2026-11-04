"""Model clients for PageOps Agent.

MetaModelClient talks to the Meta Model API at api.meta.ai using the
OpenAI-compatible chat completions surface, with a Bearer key taken from
the environment. Every call is counted in a JSON-lines usage log. The
same client, pointed at Baseten's base URL, serves the open-weights
route (Muse Spark Open) used for the hackathon's open-weight angle.

MockClient returns canned structured outputs for plan / draft / verdict
so the whole pipeline runs and tests pass with no key and no network.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import DEFAULT_DATA_DIR
from .skills import load_skills, with_skills

def humanize_text(client, text: str, brand_voice: dict) -> tuple[str, str]:
    """Run a client's humanising pass, with visible degradation.

    Returns (text, error): error is "" when the pass ran (or the
    client has no pass, like a small test double) and a short
    reason when it fell back to the unedited text. Shared by the
    pipeline (drafts) and the report (the Analyst's Read) so the
    two paths can never drift apart.
    """
    fn = getattr(client, "humanize", None)
    if fn is None:
        return text, ""
    try:
        out = fn(text, brand_voice)
    except Exception as exc:
        return text, str(exc)
    if not out or not str(out).strip():
        return text, "humaniser returned an empty rewrite"
    return str(out).strip(), ""


BASE_URL = "https://api.meta.ai/v1"
BASETEN_BASE_URL = "https://inference.baseten.co/v1"
MODEL_SPARK = "muse-spark-1.3"
MODEL_WONDER = "muse-wonder-1.0"
MODEL_SPARK_OPEN = "meta-models/muse-spark-open-1026"
MODEL_IMAGE = "muse-image-1.0"

# Muse Wonder is the product's decision model (owner's decisions,
# 2026-11-01 and 2026-11-03): plan, drafts and the report narrative
# run on Wonder, and brand verdicts run on Wonder too, in a
# dedicated judge pass (get_judge_client below). The deterministic
# checker in checker.py is the independent, model-free layer under
# the verdict. Muse Spark Open via Baseten stays in the code as an
# optional alternate route; it is not the configured judge. Muse
# Spark stays available for light utility calls where its lower
# cost matters.


def voice_instruction(brand_voice: dict) -> str:
    """The tone-of-voice block for writer prompts, or "".

    When the client has sent paragraphs they wrote themselves
    (brand data key `voice_samples`, owner's requirement
    2026-11-04), those samples are the authority on the brand's
    tone of voice: every writer is told to match them. Brands
    without samples get no block at all.
    """
    samples = str((brand_voice or {}).get("voice_samples") or "").strip()
    if not samples:
        return ""
    return (
        "The client wrote the following paragraphs themselves. They are "
        "the authority on this brand's tone of voice: match their "
        "sentence rhythm, warmth, level of formality and word choices "
        "in everything you write.\n\nVoice samples:\n" + samples
    )


class UsageLogger:
    """Appends one JSON line per API call to the usage log file."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else DEFAULT_DATA_DIR / "usage_log.jsonl"

    def record(self, model: str, usage: dict | None) -> dict:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "usage": usage or {},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return entry


class MetaModelClient:
    """Real client for the Meta Model API. No call is made unless chat()
    or one of the structured helpers is invoked explicitly."""

    def __init__(
        self,
        api_key: str | None = None,
        usage_log: Path | str | None = None,
        base_url: str = BASE_URL,
    ):
        self.api_key = api_key or os.environ.get("MODEL_API_KEY") or None
        self.usage = UsageLogger(usage_log)
        self.base_url = base_url
        # Main LLM for plan/drafts. Default Wonder; set PAGEOPS_MAIN_MODEL
        # to muse-spark-1.3 for cheap development iterations.
        self.main_model = os.environ.get("PAGEOPS_MAIN_MODEL") or MODEL_WONDER
        self.verdict_model = MODEL_WONDER
        # Verdict-style calls measure best at LOW reasoning effort,
        # and the 2026-11-04 caption runs proved the hard way that
        # an unset effort can spend the whole token budget on
        # hidden reasoning and return empty content. Default LOW;
        # the Baseten factory sets the same value explicitly, and
        # PAGEOPS_REASONING_EFFORT overrides it.
        self.reasoning_effort: str | None = (
            os.environ.get("PAGEOPS_REASONING_EFFORT") or "low"
        )

    def chat(self, messages: list[dict], model: str = MODEL_WONDER, **kwargs) -> dict:
        if not self.api_key:
            raise RuntimeError("MODEL_API_KEY is not set; cannot call the Meta Model API.")
        import httpx  # imported lazily so mock mode never needs the package

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                **({"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}),
                **kwargs,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        payload = response.json()
        self.usage.record(model, payload.get("usage"))
        return payload

    def _structured(self, instruction: str, payload: dict, model: str) -> dict:
        messages = [
            {"role": "system", "content": "You are PageOps Agent. Reply with JSON only."},
            {"role": "user", "content": f"{instruction}\n\nInput:\n{json.dumps(payload)}"},
        ]
        result = self.chat(messages, model=model)
        text = result["choices"][0]["message"]["content"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}

    def generate_plan(
        self, brief: str, brand_voice: dict, context: str = "", trends: list | None = None
    ) -> dict:
        payload = {"brief": brief, "brand_voice": brand_voice}
        if context:
            payload["previous_period"] = context
        if trends:
            payload["trends"] = trends
        return self._structured(
            with_skills("Create a 7-day content plan as JSON: {posts: [{day, platform, topic, angle, format, character, visual_style}]}. "
            "Set character to \"yes\" only for announcement or engagement posts where a mascot presenter fits; otherwise leave it empty. "
            "Set visual_style to \"scene\" for announcements, education and brand posts, and to \"concept\" when the post "
            "carries a single sharp benefit or pain message; leave it empty for text-only posts.", "strategist"),
            payload,
            self.main_model,
        )

    def direct_visual(
        self, plan_item: dict, draft_text: str, brand_voice: dict, style: str
    ) -> dict:
        """Art-direct one still visual: a concept line + an image prompt.

        Wonder decides, others execute: this method only directs.
        The Designer generates one plate from the prompt (Muse
        Image) and renders every word in code. The reply is parsed
        defensively: anything but a JSON object with a non-empty
        concept and prompt raises, and the caller falls back to the
        brand template.
        """
        colours = brand_voice.get("brand_colors") or "the brand colours in the brand data"
        character = ""
        if str(plan_item.get("character") or "").strip().lower() == "yes":
            character = (
                f" The plan item is character-marked: include the brand character "
                f"({brand_voice.get('character_name') or 'the brand mascot'}) in the scene."
            )
        if style == "concept":
            instruction = (
                "Direct one still visual in the concept style (conceptual advertising). "
                "Reply with JSON only: {concept, prompt, no_exceptions}. "
                "concept: one line naming the single visual metaphor that carries the "
                "post's one benefit or pain message. Metaphor first: one object, one "
                "scene, one idea. "
                "Legibility: a stranger must get the metaphor in one second, so every "
                "element of the metaphor must be drawn as the literal, instantly "
                "recognisable thing it represents: customer messages as envelopes or "
                "chat bubbles with tails, never as abstract orbs, blobs or generic "
                "glowing shapes. If an element could be mistaken for something else, "
                "choose a more literal form. "
                "no_exceptions: one line, written in the metaphor's own terms, stating "
                "that the metaphor is airtight: every instance of the metaphor element "
                "is handled by the protective action, none appears outside it, and the "
                "protected subject sits fully inside the safe zone. "
                "prompt: write the image prompt as a professional conceptual-ad prompt "
                "in exactly these sections, each labelled on its own line: Concept / "
                "Composition / Subject / Setting / Camera and style / Constraints. "
                "The Constraints section must include: no text, no letters, no logos, "
                "no watermark, clean negative space for a headline, and a No exceptions "
                "clause that repeats the no_exceptions line: if any element escapes "
                "the protective action, the image contradicts the claim. "
                f"Brand colours: {colours}.{character}"
            )
        else:
            instruction = (
                "Direct one still visual in the scene style. "
                "Reply with JSON only: {concept, prompt}. "
                "concept: one line naming the scene idea. "
                "prompt: describe a rich, warm scene set in the brand's world, drawn "
                "from the post topic and draft: name the brand colours "
                f"({colours}) in the prompt, set the mood from the message, and "
                "reserve clean, calm space in the top third of the frame for a "
                "headline. The prompt must forbid text and logos: include the words "
                f"\"no text\" and \"no logos\" in the prompt.{character}"
            )
        instruction = with_skills(instruction, "designer")
        messages = [
            {
                "role": "system",
                "content": (
                    "You are PageOps Agent's art director for the Graphic "
                    "Designer. Reply with JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{instruction}\n\nInput:\n"
                    + json.dumps(
                        {
                            "plan_item": plan_item,
                            "draft_text": draft_text,
                            "brand_voice": brand_voice,
                            "style": style,
                        }
                    )
                ),
            },
        ]
        result = self.chat(messages, model=self.main_model)
        text = result["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            lines = text.splitlines()[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"direct_visual: reply is not JSON ({exc})") from exc
        if not isinstance(data, dict):
            raise ValueError("direct_visual: reply is not a JSON object")
        concept = str(data.get("concept") or "").strip()
        prompt = str(data.get("prompt") or "").strip()
        no_exceptions = str(data.get("no_exceptions") or "").strip()
        if not concept or not prompt:
            raise ValueError("direct_visual: reply missing concept or prompt")
        lowered = prompt.lower()
        if "no text" not in lowered or "no logo" not in lowered:
            raise ValueError("direct_visual: prompt does not forbid text and logos")
        if style == "concept":
            for header in (
                "concept",
                "composition",
                "subject",
                "setting",
                "camera and style",
                "constraints",
            ):
                if header not in lowered:
                    raise ValueError(
                        f"direct_visual: concept prompt missing section: {header}"
                    )
            if "no letters" not in lowered or "no watermark" not in lowered:
                raise ValueError(
                    "direct_visual: concept prompt must forbid letters and watermarks"
                )
            if not no_exceptions:
                raise ValueError(
                    "direct_visual: concept reply missing the no-exceptions line"
                )
            if "no exception" not in lowered:
                raise ValueError(
                    "direct_visual: concept prompt missing the No exceptions clause"
                )
        return {"concept": concept, "prompt": prompt, "no_exceptions": no_exceptions}

    def generate_draft(self, plan_item: dict, brand_voice: dict) -> dict:
        instruction = (
            "Write one post caption as JSON: {platform, text, hashtags: []}. "
            "Follow the brand rules."
        )
        # The length window, stated up front: the brand's depth
        # floor (when it sets one) and the platform's cap. The
        # 2026-11-04 skills run drafted deep captions that then
        # failed the cap after their one revision; a drafter who
        # knows the window writes inside it the first time.
        from .checker import PLATFORM_LIMITS

        cap = PLATFORM_LIMITS.get(str(plan_item.get("platform") or "").lower())
        floor = (brand_voice or {}).get("min_caption_chars")
        window = []
        if floor:
            window.append(f"at least {floor} characters")
        if cap:
            window.append(f"at most {cap} characters")
        if window:
            instruction += (
                " The caption text must be " + " and ".join(window) + " long."
            )
        if "video" in (plan_item.get("format") or "").lower():
            # Wonder directs the video: the draft text IS the
            # storyboard script, one caption line per beat in the
            # owner's UGC order (the storyboard adds the hook from
            # the topic in front of these lines).
            instruction = (
                "Write one short-video caption as JSON: {platform, text, hashtags: []}. "
                "Follow the brand rules. The text is the video script: write it as "
                "short caption lines, one line per beat, in this exact order: "
                "line 1 the audience pain point, line 2 the product reveal, "
                "line 3 a demo of what it does, line 4 honest social proof "
                "(only claims the brand data supports; never invent results, "
                "customers or testimonials), and a final call-to-action line."
            )
        block = voice_instruction(brand_voice)
        if block:
            instruction += "\n\n" + block
        return self._structured(
            with_skills(instruction, "copywriter"),
            {"plan_item": plan_item, "brand_voice": brand_voice},
            self.main_model,
        )

    def verdict(self, draft: dict, check_summary: str) -> dict:
        return self._structured(
            with_skills("Give a final verdict as JSON: {verdict: pass|revise, reasons: []} using the rule-check summary.", "brand-checker"),
            {"draft": draft, "check_summary": check_summary},
            self.verdict_model,
        )

    def narrate(self, stats: dict, brand_voice: dict) -> str:
        """Interpret computed stats in prose. Figures come from stats only."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are PageOps Agent's performance analyst. Write two or "
                    "three plain sentences interpreting the numbers you are "
                    "given. Never invent a figure that is not in the input."
                    + ("\n\n" + load_skills("analyst") if load_skills("analyst") else "")
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"stats": stats, "brand": brand_voice.get("brand_name", "")}
                ),
            },
        ]
        result = self.chat(messages, model=self.main_model)
        return result["choices"][0]["message"]["content"].strip()

    def humanize(self, text: str, brand_voice: dict) -> str:
        """The humanising pass every writer output goes through.

        One rewrite in the brand's own voice (the blader/humanizer
        skill is the named method behind this step): natural, plain,
        warm, no AI cliches. Facts, figures, names, calls to action
        and hashtags are preserved exactly, and the line structure
        is kept, so a video script stays one line per beat.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the brand's humanising editor. Rewrite the text "
                    "so it reads like a real person from this brand wrote it: "
                    "natural, plain and warm, with no corporate stiffness and "
                    "no AI cliches. Preserve every fact, figure, name, call "
                    "to action and hashtag EXACTLY as written. Keep the same "
                    "line breaks and the same number of lines. Never add "
                    "claims, results, customers or testimonials that are not "
                    "in the text. Return only the rewritten text."
                    + ("\n\n" + load_skills("copywriter") if load_skills("copywriter") else "")
                    + ("\n\n" + voice_instruction(brand_voice) if voice_instruction(brand_voice) else "")
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"text": text, "brand_voice": brand_voice}),
            },
        ]
        result = self.chat(messages, model=self.main_model)
        return result["choices"][0]["message"]["content"].strip()


class MetaImageClient:
    """Image generation on the Meta Model API (Muse Image).

    Used for exactly one thing: the optional scene plate under a
    short video's reveal scene. Kept separate from MetaModelClient
    because the images surface is not chat-shaped.
    """

    def __init__(
        self,
        api_key: str | None = None,
        usage_log: Path | str | None = None,
        base_url: str = BASE_URL,
    ):
        self.api_key = api_key or os.environ.get("MODEL_API_KEY") or None
        self.usage = UsageLogger(usage_log)
        self.base_url = base_url

    def generate_image_bytes(self, prompt: str) -> bytes:
        """Generate one image and return its raw bytes.

        The payload's b64_json is decoded here; the bytes may be
        WebP despite any .png naming, so callers convert through
        PIL before saving. Any failure raises RuntimeError with a
        clear message.
        """
        if not self.api_key:
            raise RuntimeError("MODEL_API_KEY is not set; cannot call the Meta Model API.")
        import base64

        import httpx  # imported lazily so mock mode never needs the package

        try:
            response = httpx.post(
                f"{self.base_url}/images/generations",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": MODEL_IMAGE, "prompt": prompt},
                timeout=120.0,
            )
            response.raise_for_status()
            payload = response.json()
            raw = base64.b64decode(payload["data"][0]["b64_json"])
        except Exception as exc:
            raise RuntimeError(f"Muse Image generation failed: {exc}") from exc
        self.usage.record(MODEL_IMAGE, payload.get("usage"))
        return raw


class MockClient:
    """Canned structured outputs. Deterministic, offline, free."""

    def generate_plan(
        self, brief: str, brand_voice: dict, context: str = "", trends: list | None = None
    ) -> dict:
        brand = brand_voice.get("brand_name", "the brand")
        return {
            "brief": brief,
            "context": context,
            "trends": trends or [],
            "posts": [
                {
                    "day": "Mon",
                    "platform": "facebook",
                    "topic": f"How {brand} answers page messages while the owner is busy",
                    "angle": "Relatable problem, then the fix",
                    "format": "Short video",
                    "character": "yes",
                    "visual_style": "scene",
                },
                {
                    "day": "Wed",
                    "platform": "facebook",
                    "topic": "Three follow-ups that rescue a lost lead",
                    "angle": "Practical tips from the CRM & Lead Follow-Up Pack",
                    "format": "Carousel",
                    "visual_style": "scene",
                },
                {
                    "day": "Tue",
                    "platform": "facebook",
                    "topic": "Before and after: one inbox, zero missed price questions",
                    "angle": "Show the saved replies, then the offer",
                    "format": "Poster",
                    "visual_style": "concept",
                },
                {
                    "day": "Thu",
                    "platform": "facebook",
                    "topic": "Five questions your page should answer without you",
                    "angle": "Checklist the owner can test tonight",
                    "format": "Carousel",
                    "character": "yes",
                    "visual_style": "scene",
                },
                {
                    "day": "Fri",
                    "platform": "linkedin",
                    "topic": "What a content pipeline does for a small team",
                    "angle": "Trust and process, with a soft offer",
                    "format": "Text post",
                },
                {
                    "day": "Sat",
                    "platform": "facebook",
                    "topic": "Weekend orders while the shop is closed",
                    "angle": "The bot takes the order, the owner confirms later",
                    "format": "Short video",
                    "visual_style": "scene",
                },
                {
                    "day": "Sun",
                    "platform": "facebook",
                    "topic": "This week in your page inbox, in one report",
                    "angle": "Tease the weekly performance report",
                    "format": "Poster",
                    "visual_style": "concept",
                },
            ],
        }

    def generate_draft(self, plan_item: dict, brand_voice: dict) -> dict:
        topic = plan_item.get("topic", "our latest service")
        if "video" in (plan_item.get("format") or "").lower():
            # Beat-structured like the real client's directed
            # script: pain, reveal, demo, proof, then the CTA line,
            # one line per beat, so mock runs exercise all six
            # storyboard beats (the hook comes from the topic).
            brand = brand_voice.get("brand_name", "the brand")
            lines = [
                "Customers message your page after hours and wait until morning for a reply.",
                f"Meet {brand}, the assistant that answers your page messages for you.",
                "Watch it answer a price question, take the customer's details and line up the follow-up.",
                "Built for SME owners who sell through their page and cannot sit in the inbox all day.",
                "Message us to get started, and we will map the first step with you.",
            ]
            text = "\n".join(lines) + " #FYFAI #AIAutomation #SME"
            return {
                "platform": plan_item.get("platform", "facebook"),
                "text": text,
                "hashtags": ["#FYFAI", "#AIAutomation", "#SME"],
            }
        text = (
            f"{topic}. We built this for SME owners who sell through their page and "
            "cannot sit in the inbox all day. Message us to get started, and we will "
            "map the first step with you. #FYFAI #AIAutomation #SME"
        )
        return {
            "platform": plan_item.get("platform", "facebook"),
            "text": text,
            "hashtags": ["#FYFAI", "#AIAutomation", "#SME"],
        }

    def direct_visual(
        self, plan_item: dict, draft_text: str, brand_voice: dict, style: str
    ) -> dict:
        """Deterministic direction for both visual styles, offline."""
        brand = brand_voice.get("brand_name", "the brand")
        topic = plan_item.get("topic", "the post")
        colours = (
            brand_voice.get("brand_colors")
            or "Primary #123B8F; Accent #F5B301; Background #F7F5F0; Ink #14213D"
        )
        if style == "concept":
            concept = (
                f"Visual metaphor for \"{topic}\": the post's one message as a "
                "single bold object in a single scene."
            )
            no_exceptions = (
                "No exceptions: every instance of the metaphor element is inside "
                "the protective action, none appears outside it, and the protected "
                "subject sits fully inside the safe zone."
            )
            prompt = (
                f"Concept: one visual metaphor carrying the message of \"{topic}\" "
                f"for {brand}, in the brand colours ({colours}).\n"
                "Composition: one bold central object, generous clean negative "
                "space in the top third for a headline.\n"
                "Subject: the metaphor object only, rendered large and sharp.\n"
                "Setting: a plain studio setting in the brand colours, nothing "
                "competing with the subject.\n"
                "Camera and style: straight-on product photography, soft even "
                "light, high detail.\n"
                "Constraints: no text, no letters, no logos, no watermark, clean "
                f"negative space for a headline. {no_exceptions}"
            )
            return {"concept": concept, "prompt": prompt, "no_exceptions": no_exceptions}
        character = ""
        if str(plan_item.get("character") or "").strip().lower() == "yes":
            character = (
                f" Include {brand_voice.get('character_name') or 'the brand character'}, "
                "the brand character, presenting the scene."
            )
        concept = f"Scene: \"{topic}\" brought to life inside the {brand} brand world."
        prompt = (
            f"A rich, warm scene for {brand} on the theme \"{topic}\", in the brand "
            f"colours ({colours}).{character} Friendly small-business setting, soft "
            "evening light, clean calm space in the top third of the frame for a "
            "headline. No text, no letters, no logos, no watermark."
        )
        return {"concept": concept, "prompt": prompt, "no_exceptions": ""}

    def narrate(self, stats: dict, brand_voice: dict) -> str:
        totals = stats.get("totals", {})
        best = stats.get("best_post") or {}
        return (
            f"across {totals.get('posts', 0)} tracked posts the page earned "
            f"{totals.get('reach', 0)} reach and {totals.get('engagement', 0)} "
            f"engagement; the strongest post was {best.get('post_id', 'n/a')} "
            f"with {best.get('engagement', 0)} engagement, so its angle leads "
            "the next plan."
        )

    def verdict(self, draft: dict, check_summary: str) -> dict:
        passed = "[FAIL]" not in check_summary
        return {
            "verdict": "pass" if passed else "revise",
            "reasons": ["All deterministic brand rules passed."] if passed else [check_summary],
        }

    def humanize(self, text: str, brand_voice: dict) -> str:
        """Offline stand-in: the mock has no model, so the text
        passes through unchanged. The pass itself is exercised in
        tests with rewriting doubles, and in production the real
        client rewrites in the brand voice."""
        return text


def get_client(settings=None):
    """Factory: real client only in meta mode with a key, else mock."""
    from .config import get_settings

    settings = settings or get_settings()
    if settings.model_mode == "meta" and settings.model_api_key:
        return MetaModelClient(api_key=settings.model_api_key, usage_log=settings.usage_log)
    return MockClient()


def get_image_client(settings=None):
    """Factory for the Muse Image plate route: a client only in
    meta mode with a key, else None.

    Callers treat None as "no plates": the video falls back to
    template frames, so the pipeline never depends on the image
    route existing (and mock mode stays hermetic).
    """
    from .config import get_settings

    settings = settings or get_settings()
    if settings.model_mode == "meta" and settings.model_api_key:
        return MetaImageClient(api_key=settings.model_api_key, usage_log=settings.usage_log)
    return None


def get_baseten_client(api_key: str | None = None, usage_log: Path | str | None = None):
    """Open-weights route: Muse Spark Open served by Baseten.

    Returns None when no Baseten key is configured (BASETEN_API_KEY).
    The hackathon key works with this one model only, so plan, draft
    and verdict calls on this client all use MODEL_SPARK_OPEN.
    """
    key = api_key or os.environ.get("BASETEN_API_KEY") or None
    if not key:
        return None
    client = MetaModelClient(api_key=key, usage_log=usage_log, base_url=BASETEN_BASE_URL)
    client.main_model = MODEL_SPARK_OPEN
    client.verdict_model = MODEL_SPARK_OPEN
    client.reasoning_effort = "low"
    return client


def get_judge_client(settings=None):
    """The Brand Checker judge: Muse Wonder in a dedicated pass.

    Owner's decision (2026-11-03): Muse Wonder holds every
    big-decision role, including brand verdicts. The judge is its
    own MetaModelClient instance on the Meta Model API, never the
    drafting client object, so verdicts run as the Judge role's own
    pass through verdict() with verdict_model set to MODEL_WONDER,
    and the pipeline's same-object guard passes. The deterministic
    checker in code remains the independent, model-free layer under
    the verdict. Muse Spark Open via Baseten (get_baseten_client)
    stays in the code as an optional alternate route; it is not the
    configured judge.

    Returns None in mock mode or without a Meta key; callers then
    use the drafting client's verdict, so the pipeline never depends
    on the judge existing.
    """
    from .config import get_settings

    settings = settings or get_settings()
    if settings.model_mode == "meta" and settings.model_api_key:
        return MetaModelClient(api_key=settings.model_api_key, usage_log=settings.usage_log)
    return None
