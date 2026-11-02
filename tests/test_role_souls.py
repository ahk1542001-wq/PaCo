"""Role souls: every role has a standing definition file with the
sections the company structure promises (owns / stops / self-check),
so the definitions cannot silently drift away from the shape."""

from pathlib import Path

ROLES = Path(__file__).resolve().parent.parent / "roles"
EXPECTED = {
    "ceo": "Control Layer",
    "strategist": "Department 1",
    "copywriter": "Department 1",
    "designer": "Department 1",
    "brand-checker": "Department 1",
    "scheduler": "Department 2",
    "analyst": "Department 2",
}


def test_every_role_has_a_soul_file():
    for slug, department in EXPECTED.items():
        path = ROLES / f"{slug}.md"
        assert path.exists(), f"missing role soul: {path}"
        text = path.read_text(encoding="utf-8")
        assert department in text
        for section in ("## Owns", "## Stops", "## Self-check", "## Skills", "## Tools", "## Model"):
            assert section in text, f"{slug}.md lacks {section}"


def test_the_ceo_soul_keeps_the_gate_with_the_owner():
    text = (ROLES / "ceo.md").read_text(encoding="utf-8")
    assert "Cannot approve in the owner's place" in text
