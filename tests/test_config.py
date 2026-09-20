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

    assert config.enabled_capabilities == ("tools", "skills")
    assert config.tools.enabled is True
    assert config.skills.enabled is True
    assert config.skills.roots == ("./skills", "~/.agents/skills")
    assert config.compaction.trigger_tokens == 16000


def test_default_configuration_enables_core_tool_and_skill_systems() -> None:
    config = MosaicConfig()

    assert config.enabled_capabilities == ("tools", "skills")
    assert config.tools.enabled is True
    assert config.skills.enabled is True
    assert config.builtins.tools_enabled is True
    assert config.builtins.skills_enabled is True
    assert config.network.enabled is False


def test_config_reads_builtin_category_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAIC_BUILTIN_TOOLS_ENABLED", "true")
    monkeypatch.setenv("MOSAIC_BUILTIN_SKILLS_ENABLED", "true")
    monkeypatch.setenv("MOSAIC_NETWORK_ENABLED", "true")
    monkeypatch.setenv("MOSAIC_NETWORK_PROVIDER", "ddgs")

    config = MosaicConfig.from_env()

    assert config.builtins.tools_enabled is True
    assert config.builtins.skills_enabled is True
    assert config.network.enabled is True
    assert config.network.provider == "ddgs"
