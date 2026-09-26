from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from mosaic_harness.platform import (
    AgentBlueprint,
    BlueprintNotFoundError,
    InMemoryBlueprintRepository,
    SQLiteBlueprintRepository,
)


def make_blueprint(**changes: Any) -> AgentBlueprint:
    values: dict[str, Any] = {
        "id": "bp-storage",
        "slug": "storage-agent",
        "display_name": "Storage Agent",
        "system_prompt": "Work with the stored blueprint.",
        "model_ref": {
            "provider": "openai",
            "model": "gpt-5",
            "api_key": "do-not-store",
            "api_key_env": "OPENAI_API_KEY",
        },
        "tool_refs": ("current_time",),
        "security_policy": {"secret_ref": "env:OPENAI_API_KEY"},
        "metadata": {"nested": {"token": "do-not-store", "owner": "local"}},
    }
    values.update(changes)
    return AgentBlueprint(**values)


@pytest.fixture(params=["memory", "sqlite"])
def repository(
    request: pytest.FixtureRequest, tmp_path: Path
) -> InMemoryBlueprintRepository | SQLiteBlueprintRepository:
    if request.param == "memory":
        return InMemoryBlueprintRepository()
    return SQLiteBlueprintRepository(tmp_path / "agent-foundry.sqlite3")


def test_repository_protocol_preserves_drafts_releases_and_rollbacks(repository: Any) -> None:
    draft = repository.create(make_blueprint())
    first = repository.publish(draft.id)
    repository.update(draft.id, system_prompt="Work with a newer stored blueprint.")
    second = repository.publish(draft.id)
    rollback = repository.rollback(draft.id, version=1)

    assert repository.get(draft.id).status == "published"
    assert [release.version for release in repository.list_releases(draft.id)] == [1, 2, 3]
    assert first.system_prompt == "Work with the stored blueprint."
    assert second.system_prompt == "Work with a newer stored blueprint."
    assert rollback.system_prompt == first.system_prompt


def test_sqlite_repository_survives_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "restart.sqlite3"
    first = SQLiteBlueprintRepository(database_path)
    blueprint = first.create(make_blueprint())
    release = first.publish(blueprint.id)
    first.close()

    second = SQLiteBlueprintRepository(database_path)
    persisted = second.get(blueprint.id)
    assert persisted.system_prompt == blueprint.system_prompt
    assert persisted.status == "published"
    assert persisted.version == 1
    assert second.get_release(blueprint.id, version=release.version) == release
    second.close()


def test_publish_is_idempotent_and_does_not_create_duplicate_versions(repository: Any) -> None:
    blueprint = repository.create(make_blueprint())
    first = repository.publish(blueprint.id)
    same = repository.publish(blueprint.id)

    assert same == first
    assert len(repository.list_releases(blueprint.id)) == 1


def test_sqlite_concurrent_publish_attempts_share_one_release(tmp_path: Path) -> None:
    database_path = tmp_path / "concurrent.sqlite3"
    seed = SQLiteBlueprintRepository(database_path)
    blueprint = seed.create(make_blueprint())
    seed.close()

    def publish_once(_: int) -> str:
        repository = SQLiteBlueprintRepository(database_path, busy_timeout_ms=10_000)
        try:
            return repository.publish(blueprint.id).release_id
        finally:
            repository.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        release_ids = list(executor.map(publish_once, range(8)))

    check = SQLiteBlueprintRepository(database_path)
    assert set(release_ids) == {check.get_release(blueprint.id).release_id}
    assert [release.version for release in check.list_releases(blueprint.id)] == [1]
    check.close()


def test_sqlite_configures_wal_foreign_keys_and_bounded_busy_timeout(tmp_path: Path) -> None:
    database_path = tmp_path / "pragmas.sqlite3"
    repository = SQLiteBlueprintRepository(database_path, busy_timeout_ms=3210)
    connection = repository.connection

    assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 3210
    assert (
        connection.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()[
            0
        ]
        == "1"
    )
    repository.close()
    assert os.stat(database_path).st_mode & 0o777 == 0o600


def test_sqlite_export_import_bundle_omits_credential_material(tmp_path: Path) -> None:
    database_path = tmp_path / "bundle.sqlite3"
    source = SQLiteBlueprintRepository(database_path)
    blueprint = source.create(make_blueprint())
    source.publish(blueprint.id)
    bundle = source.export_bundle(blueprint.id)

    serialized = json.dumps(bundle, sort_keys=True)
    assert "do-not-store" not in serialized
    assert '"api_key":' not in serialized
    assert "credential_ref" not in serialized

    imported_path = tmp_path / "imported.sqlite3"
    target = SQLiteBlueprintRepository(imported_path)
    imported = target.import_bundle(bundle)
    assert imported == target.get(blueprint.id)
    assert (
        target.get_release(blueprint.id, version=1).fingerprint
        == source.get_release(blueprint.id, version=1).fingerprint
    )
    source.close()
    target.close()


def test_sqlite_connector_storage_is_public_only(tmp_path: Path) -> None:
    repository = SQLiteBlueprintRepository(tmp_path / "connectors.sqlite3")
    repository.save_connector(
        {
            "id": "weather",
            "url": "https://api.example.test/weather",
            "allowed_domains": ["api.example.test"],
            "credential_ref": "env:WEATHER_API_KEY",
        }
    )

    public = repository.get_connector("weather")
    assert public["id"] == "weather"
    assert "credential_ref" not in public

    with pytest.raises(BlueprintNotFoundError):
        repository.get("missing")
    repository.close()
