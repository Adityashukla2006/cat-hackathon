"""Equipment how-to guides: markdown files with a small frontmatter block, split by section."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

GUIDES_DIR = Path(__file__).resolve().parents[1] / "guides"


class GuideSection(BaseModel):
    guide_id: str
    guide_title: str
    heading: str
    text: str

    @property
    def source(self) -> str:
        return f"{self.guide_title} > {self.heading}"


class Guide(BaseModel):
    id: str
    title: str
    machines: list[str]
    tags: list[str]
    body: str
    sections: list[GuideSection]


def _split_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_guide(guide_id: str, raw: str) -> Guide:
    lines = raw.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"guide {guide_id} is missing frontmatter")
    end = lines.index("---", 1)
    meta = dict(line.split(":", 1) for line in lines[1:end] if ":" in line)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    body = "\n".join(lines[end + 1 :]).strip()
    title = meta.get("title")
    if not title:
        raise ValueError(f"guide {guide_id} has no title")

    sections: list[GuideSection] = []
    heading, buf = "Overview", []

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text:
            sections.append(
                GuideSection(guide_id=guide_id, guide_title=title, heading=heading, text=text)
            )

    for line in body.split("\n"):
        if line.startswith("## "):
            flush()
            heading, buf = line[3:].strip(), []
        elif not line.startswith("# "):
            buf.append(line)
    flush()

    return Guide(
        id=guide_id,
        title=title,
        machines=_split_list(meta.get("machines", "")),
        tags=_split_list(meta.get("tags", "")),
        body=body,
        sections=sections,
    )


def load_guides(directory: Path = GUIDES_DIR) -> list[Guide]:
    return [
        parse_guide(path.stem, path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.md"))
    ]


@lru_cache
def get_guides() -> tuple[Guide, ...]:
    return tuple(load_guides())
