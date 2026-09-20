from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .base import MosaicSkill


@dataclass(frozen=True, slots=True)
class SkillManifest(MosaicSkill):
    name: str
    description: str
    path: Path
    body: str
    metadata: dict[str, str]

    def instructions(self) -> str:
        return self.body


class SkillRegistry:
    """Filesystem-backed SKILL.md catalog with progressive disclosure."""

    def __init__(self, roots: tuple[str, ...]) -> None:
        self.roots = tuple(Path(root).expanduser() for root in roots)
        self._skills: dict[str, MosaicSkill] = {}
        self.refresh()

    @property
    def skills(self) -> tuple[MosaicSkill, ...]:
        return tuple(self._skills.values())

    def refresh(self) -> None:
        self._skills.clear()
        for root in self.roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("SKILL.md")):
                manifest = _parse_skill(path)
                self._skills[manifest.name] = manifest

    def get(self, name: str) -> MosaicSkill | None:
        return self._skills.get(name)

    def register(self, skill: MosaicSkill) -> None:
        self._skills[skill.name] = skill

    def search(self, query: str, limit: int = 5) -> tuple[MosaicSkill, ...]:
        lowered = query.casefold()
        ranked = [
            skill
            for skill in self.skills
            if lowered in f"{skill.name} {skill.description}".casefold()
        ]
        return tuple(ranked[:limit])


def _parse_skill(path: Path) -> SkillManifest:
    raw = path.read_text(encoding="utf-8")
    metadata: dict[str, str] = {}
    body = raw
    if raw.startswith("---"):
        _, frontmatter, body = raw.split("---", 2)
        for line in frontmatter.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip("\"'")
    name = metadata.get("name") or path.parent.name
    description = metadata.get("description") or f"Skill from {path.parent.name}"
    return SkillManifest(
        name=name,
        description=description,
        path=path,
        body=body.strip(),
        metadata=metadata,
    )
