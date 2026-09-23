import pytest

from app.guides import load_guides, parse_guide

RAW = """---
title: Test guide
machines: excavator, wheel_loader
tags: a, b
---

# Test guide

Intro line.

## First
Do the first thing.

## Second
Do the second thing.
"""


def test_parse_guide_frontmatter_and_sections():
    guide = parse_guide("test", RAW)
    assert guide.title == "Test guide"
    assert guide.machines == ["excavator", "wheel_loader"]
    assert guide.tags == ["a", "b"]
    assert [s.heading for s in guide.sections] == ["Overview", "First", "Second"]
    assert guide.sections[1].text == "Do the first thing."
    assert guide.sections[2].source == "Test guide > Second"


def test_parse_guide_rejects_missing_frontmatter_or_title():
    with pytest.raises(ValueError):
        parse_guide("x", "# No frontmatter")
    with pytest.raises(ValueError):
        parse_guide("x", "---\ntags: a\n---\nbody")


def test_shipped_guides_parse_and_have_content():
    guides = load_guides()
    assert len(guides) >= 8
    for guide in guides:
        assert guide.machines, guide.id
        assert guide.tags, guide.id
        assert len(guide.sections) >= 2, guide.id


@pytest.mark.parametrize(
    "tag", ["seatbelt", "walkaround", "soft ground", "fatigue", "idle", "joystick", "emergency"]
)
def test_guides_cover_core_topics(tag):
    assert any(tag in g.tags for g in load_guides())
