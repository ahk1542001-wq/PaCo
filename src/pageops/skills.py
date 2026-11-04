"""Role skill loading.

Each role in roles/ names the skills behind its work. The fitted
skill files live in the repo's skills/<role>/ directory and are
loaded into the role's prompts at call time, so the method is
part of the instruction the model actually receives, not just a
claim in a document. A role with no skill folder gets no block;
nothing fails because a folder is missing.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"
MAX_SKILL_CHARS = 7000


@lru_cache(maxsize=None)
def load_skills(role: str) -> str:
    """The role's fitted skill texts, concatenated, or ""."""
    folder = SKILLS_ROOT / role
    if not folder.is_dir():
        return ""
    parts = []
    for path in sorted(folder.glob("*.md")):
        parts.append(path.read_text(encoding="utf-8").strip())
    text = "\n\n".join(p for p in parts if p)
    return text[:MAX_SKILL_CHARS]


def skills_block(role: str) -> str:
    """The formatted block for a prompt, or "" when no skills."""
    skills = load_skills(role)
    if not skills:
        return ""
    return f"ROLE SKILLS for {role} (follow these methods):\n{skills}"


def with_skills(instruction: str, role: str) -> str:
    """Append the role's skill block to an instruction."""
    block = skills_block(role)
    if not block:
        return instruction
    return f"{instruction}\n\n{block}"
