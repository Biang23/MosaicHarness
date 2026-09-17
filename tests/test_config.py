from __future__ import annotations

import pytest

from mosaic_harness import MosaicConfig


def test_environment_variables_select_capabilities_without_import_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOSAIC_TOOLS_ENABLED", "true")
    monkeypatch.setenv("MOSAIC_SKILL_PATHS", "./skills, ~/.agents/skills")
    monkeypatch.setenv("MOSAIC_COMPACTION_TRIGGER_TOKENS", "16000")

    config = MosaicConfig.from_env()

    assert config.enabled_capabilities == ("tools",)
    assert config.tools.enabled is True
    assert config.skills.enabled is False
    assert config.skills.roots == ("./skills", "~/.agents/skills")
    assert config.compaction.trigger_tokens == 16000
