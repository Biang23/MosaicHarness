from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .blueprints import AgentBlueprint


@dataclass(frozen=True, slots=True)
class AgentTemplate:
    """A safe starter blueprint for the visual creator experience."""

    id: str
    display_name: str
    description: str
    icon: str
    system_prompt: str
    tool_refs: tuple[str, ...] = ()
    skill_refs: tuple[str, ...] = ()
    memory_policy: dict[str, Any] | None = None
    pixel_theme: str = "mosaic"

    def instantiate(
        self,
        *,
        slug: str,
        model_ref: Any,
        display_name: str | None = None,
    ) -> AgentBlueprint:
        return AgentBlueprint(
            slug=slug,
            display_name=display_name or self.display_name,
            system_prompt=self.system_prompt,
            icon=self.icon,
            pixel_theme=self.pixel_theme,
            template_id=self.id,
            model_ref=model_ref,
            tool_refs=self.tool_refs,
            skill_refs=self.skill_refs,
            memory_policy=dict(self.memory_policy or {}),
        )


class TemplateCatalog:
    def __init__(self, templates: Iterable[AgentTemplate] = ()) -> None:
        self._templates: dict[str, AgentTemplate] = {}
        for template in templates:
            self.register(template)

    def register(self, template: AgentTemplate) -> AgentTemplate:
        if template.id in self._templates:
            raise ValueError(f"template already registered: {template.id}")
        self._templates[template.id] = template
        return template

    def get(self, template_id: str) -> AgentTemplate:
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise KeyError(f"unknown template: {template_id}") from exc

    def list(self) -> tuple[AgentTemplate, ...]:
        return tuple(self._templates.values())

    def discover(self, query: str = "", *, limit: int = 20) -> tuple[AgentTemplate, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        lowered = query.casefold().strip()
        matches = tuple(
            template
            for template in self._templates.values()
            if not lowered
            or lowered in f"{template.id} {template.display_name} {template.description}".casefold()
        )
        return matches[:limit]

    def instantiate(self, template_id: str, **kwargs: Any) -> AgentBlueprint:
        return self.get(template_id).instantiate(**kwargs)


def built_in_templates() -> tuple[AgentTemplate, ...]:
    return (
        AgentTemplate(
            id="researcher",
            display_name="Research Scout",
            description="Research a question and return a concise, sourced answer.",
            icon="compass",
            system_prompt=(
                "Research carefully. Prefer primary sources, cite important claims, "
                "and state uncertainty when evidence is incomplete."
            ),
            tool_refs=("web_search", "fetch_url"),
            skill_refs=("network-research",),
            memory_policy={"namespace": "research", "write": False},
        ),
        AgentTemplate(
            id="support",
            display_name="Support Guide",
            description="Answer customer questions clearly and escalate risky actions.",
            icon="speech-bubble",
            system_prompt=(
                "Help the customer clearly. Ask for missing context, never invent policy, "
                "and explain when a human needs to take over."
            ),
            tool_refs=("current_time",),
            memory_policy={"namespace": "support", "write": False},
        ),
        AgentTemplate(
            id="document-organizer",
            display_name="Document Organizer",
            description="Extract structure from local documents and summarize findings.",
            icon="folder",
            system_prompt=(
                "Organize document contents into clear sections. Preserve source wording "
                "for important facts and identify missing or ambiguous information."
            ),
            tool_refs=("list_files", "read_file", "search_document"),
            memory_policy={"namespace": "documents", "write": False},
        ),
    )


__all__ = ["AgentTemplate", "TemplateCatalog", "built_in_templates"]
