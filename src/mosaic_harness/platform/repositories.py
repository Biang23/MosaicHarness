from __future__ import annotations

import builtins
import json
import os
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import RLock
from typing import Any, Protocol, cast

from .blueprints import AgentBlueprint, ReleaseManifest
from .connectors import ConnectorSpec


class BlueprintNotFoundError(KeyError):
    """Raised when a blueprint or release cannot be found."""


class BlueprintRepository(Protocol):
    """Persistence boundary shared by the platform service and local stores."""

    def create(self, blueprint: AgentBlueprint) -> AgentBlueprint: ...

    def save(self, blueprint: AgentBlueprint) -> AgentBlueprint: ...

    def get(self, blueprint_id: str) -> AgentBlueprint: ...

    def list(self) -> tuple[AgentBlueprint, ...]: ...

    def update(
        self,
        blueprint_id: str,
        blueprint: AgentBlueprint | None = None,
        **changes: object,
    ) -> AgentBlueprint: ...

    def publish(self, blueprint_id: str, *, changelog: str | None = None) -> ReleaseManifest: ...

    def get_release(self, blueprint_id: str, *, version: int | None = None) -> ReleaseManifest: ...

    def list_releases(self, blueprint_id: str) -> tuple[ReleaseManifest, ...]: ...

    def rollback(self, blueprint_id: str, *, version: int) -> ReleaseManifest: ...


class InMemoryBlueprintRepository:
    """Local-first repository with draft and immutable release storage."""

    def __init__(self) -> None:
        self._blueprints: dict[str, AgentBlueprint] = {}
        self._releases: dict[str, list[ReleaseManifest]] = {}

    def create(self, blueprint: AgentBlueprint) -> AgentBlueprint:
        if blueprint.id in self._blueprints:
            raise ValueError(f"blueprint '{blueprint.id}' already exists")
        self._blueprints[blueprint.id] = blueprint
        self._releases.setdefault(blueprint.id, [])
        return blueprint

    def save(self, blueprint: AgentBlueprint) -> AgentBlueprint:
        if blueprint.id in self._blueprints:
            self._blueprints[blueprint.id] = blueprint
            self._releases.setdefault(blueprint.id, [])
            return blueprint
        return self.create(blueprint)

    def get(self, blueprint_id: str) -> AgentBlueprint:
        try:
            return self._blueprints[blueprint_id]
        except KeyError as exc:
            raise BlueprintNotFoundError(blueprint_id) from exc

    def list(self) -> tuple[AgentBlueprint, ...]:
        return tuple(self._blueprints.values())

    def update(
        self,
        blueprint_id: str,
        blueprint: AgentBlueprint | None = None,
        **changes: object,
    ) -> AgentBlueprint:
        current = self.get(blueprint_id)
        if blueprint is not None and changes:
            raise TypeError("pass either a blueprint or field changes, not both")
        if blueprint is not None:
            if blueprint.id != blueprint_id:
                raise ValueError("replacement blueprint id does not match blueprint_id")
            updated = blueprint
        else:
            if "id" in changes:
                raise ValueError("blueprint id cannot be changed")
            updated = replace(current, **cast(Any, changes))
        updated = replace(updated, status="draft")
        self._blueprints[blueprint_id] = updated
        return updated

    def publish(self, blueprint_id: str, *, changelog: str | None = None) -> ReleaseManifest:
        current = self.get(blueprint_id)
        existing = self._releases.setdefault(blueprint_id, [])
        if existing:
            candidate_fingerprint = current.fingerprint
            if existing[-1].fingerprint == candidate_fingerprint:
                return existing[-1]
        version = len(self._releases.setdefault(blueprint_id, [])) + 1
        release = ReleaseManifest.from_blueprint(current, version=version, changelog=changelog)
        releases = self._releases[blueprint_id]
        releases.append(release)
        self._blueprints[blueprint_id] = replace(
            current,
            status="published",
            version=version,
            changelog=release.changelog,
        )
        return release

    def get_release(self, blueprint_id: str, *, version: int | None = None) -> ReleaseManifest:
        releases = self._release_list(blueprint_id)
        if version is None:
            return releases[-1]
        for release in releases:
            if release.version == version:
                return release
        raise BlueprintNotFoundError(f"release {blueprint_id}@{version}")

    def list_releases(self, blueprint_id: str) -> tuple[ReleaseManifest, ...]:
        return tuple(self._release_list(blueprint_id))

    def rollback(self, blueprint_id: str, *, version: int) -> ReleaseManifest:
        target = self.get_release(blueprint_id, version=version)
        next_version = len(self._releases[blueprint_id]) + 1
        release = ReleaseManifest.from_blueprint(
            target.to_blueprint(status="draft"),
            version=next_version,
            changelog=f"Rollback to version {version}",
        )
        releases = self._releases[blueprint_id]
        releases.append(release)
        self._blueprints[blueprint_id] = replace(
            release.to_blueprint(status="published"),
            version=next_version,
            changelog=release.changelog,
        )
        return release

    def _release_list(self, blueprint_id: str) -> builtins.list[ReleaseManifest]:
        if blueprint_id not in self._blueprints:
            raise BlueprintNotFoundError(blueprint_id)
        releases = self._releases.get(blueprint_id, [])
        if not releases:
            raise BlueprintNotFoundError(f"no releases for blueprint '{blueprint_id}'")
        return releases


class SQLiteBlueprintRepository:
    """Transactional, local-first repository backed by a single SQLite file.

    The database path is intentionally explicit. This class never chooses a
    home-directory default, and only stores JSON-safe blueprint/release data.
    Credential references are accepted by connector validation but are omitted
    before connector rows and exported bundles are written.
    """

    SCHEMA_VERSION = 1
    DEFAULT_BUSY_TIMEOUT_MS = 5_000

    def __init__(
        self,
        database_path: str | Path,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        if not database_path:
            raise ValueError("database_path must be explicit")
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        self.database_path = str(database_path)
        self.busy_timeout_ms = busy_timeout_ms
        self._lock = RLock()

        if self.database_path != ":memory:":
            path = Path(self.database_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                self._restrict_permissions(path)

        self._connection = sqlite3.connect(
            self.database_path,
            timeout=busy_timeout_ms / 1000,
            isolation_level=None,
            check_same_thread=False,
        )
        self._configure()
        self._migrate()
        self._restrict_database_permissions()

    @property
    def connection(self) -> sqlite3.Connection:
        """Expose the configured connection for diagnostics and migrations."""

        return self._connection

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> SQLiteBlueprintRepository:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def create(self, blueprint: AgentBlueprint) -> AgentBlueprint:
        blueprint = self._canonical_blueprint(blueprint)
        payload = blueprint.to_json()
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO blueprints
                        (id, slug, status, version, fingerprint, payload)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        blueprint.id,
                        blueprint.slug,
                        blueprint.status,
                        blueprint.version,
                        blueprint.fingerprint,
                        payload,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"blueprint '{blueprint.id}' already exists") from exc
        return blueprint

    def save(self, blueprint: AgentBlueprint) -> AgentBlueprint:
        blueprint = self._canonical_blueprint(blueprint)
        payload = blueprint.to_json()
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM blueprints WHERE id = ?", (blueprint.id,)
            ).fetchone()
            if existing is None:
                try:
                    connection.execute(
                        """
                        INSERT INTO blueprints
                            (id, slug, status, version, fingerprint, payload)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            blueprint.id,
                            blueprint.slug,
                            blueprint.status,
                            blueprint.version,
                            blueprint.fingerprint,
                            payload,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError(f"blueprint '{blueprint.id}' already exists") from exc
            else:
                self._update_row(connection, blueprint)
        return blueprint

    def get(self, blueprint_id: str) -> AgentBlueprint:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM blueprints WHERE id = ?", (blueprint_id,)
            ).fetchone()
        if row is None:
            raise BlueprintNotFoundError(blueprint_id)
        return AgentBlueprint.from_json(str(row[0]))

    def list(self) -> tuple[AgentBlueprint, ...]:
        with self._lock:
            rows = self._connection.execute("SELECT payload FROM blueprints ORDER BY id").fetchall()
        return tuple(AgentBlueprint.from_json(str(row[0])) for row in rows)

    def update(
        self,
        blueprint_id: str,
        blueprint: AgentBlueprint | None = None,
        **changes: object,
    ) -> AgentBlueprint:
        with self._transaction() as connection:
            current = self._get_from_connection(connection, blueprint_id)
            if blueprint is not None and changes:
                raise TypeError("pass either a blueprint or field changes, not both")
            if blueprint is not None:
                if blueprint.id != blueprint_id:
                    raise ValueError("replacement blueprint id does not match blueprint_id")
                updated = blueprint
            else:
                if "id" in changes:
                    raise ValueError("blueprint id cannot be changed")
                updated = replace(current, **cast(Any, changes))
            updated = self._canonical_blueprint(replace(updated, status="draft"))
            self._update_row(connection, updated)
        return updated

    def publish(self, blueprint_id: str, *, changelog: str | None = None) -> ReleaseManifest:
        with self._transaction() as connection:
            current = self._get_from_connection(connection, blueprint_id)
            latest_row = connection.execute(
                """
                SELECT payload FROM releases
                WHERE blueprint_id = ?
                ORDER BY version DESC LIMIT 1
                """,
                (blueprint_id,),
            ).fetchone()
            if latest_row is not None:
                latest = ReleaseManifest.from_json(str(latest_row[0]))
                if latest.fingerprint == current.fingerprint:
                    return latest

            next_version = self._next_version(connection, blueprint_id)
            release = ReleaseManifest.from_blueprint(
                current,
                version=next_version,
                changelog=changelog if changelog is not None else None,
            )
            self._insert_release(connection, release)
            self._update_row(
                connection,
                replace(
                    current,
                    status="published",
                    version=release.version,
                    changelog=release.changelog,
                ),
            )
            return release

    def get_release(self, blueprint_id: str, *, version: int | None = None) -> ReleaseManifest:
        with self._lock:
            if version is None:
                row = self._connection.execute(
                    """
                    SELECT payload FROM releases
                    WHERE blueprint_id = ?
                    ORDER BY version DESC LIMIT 1
                    """,
                    (blueprint_id,),
                ).fetchone()
            else:
                row = self._connection.execute(
                    """
                    SELECT payload FROM releases
                    WHERE blueprint_id = ? AND version = ?
                    """,
                    (blueprint_id, version),
                ).fetchone()
        if row is None:
            self._raise_release_not_found(blueprint_id, version)
        return ReleaseManifest.from_json(str(row[0]))

    def list_releases(self, blueprint_id: str) -> tuple[ReleaseManifest, ...]:
        with self._lock:
            if (
                self._connection.execute(
                    "SELECT id FROM blueprints WHERE id = ?", (blueprint_id,)
                ).fetchone()
                is None
            ):
                raise BlueprintNotFoundError(blueprint_id)
            rows = self._connection.execute(
                """
                SELECT payload FROM releases
                WHERE blueprint_id = ?
                ORDER BY version
                """,
                (blueprint_id,),
            ).fetchall()
        if not rows:
            raise BlueprintNotFoundError(f"no releases for blueprint '{blueprint_id}'")
        return tuple(ReleaseManifest.from_json(str(row[0])) for row in rows)

    def rollback(self, blueprint_id: str, *, version: int) -> ReleaseManifest:
        with self._transaction() as connection:
            target = self._get_release_from_connection(connection, blueprint_id, version)
            next_version = self._next_version(connection, blueprint_id)
            release = ReleaseManifest.from_blueprint(
                target.to_blueprint(status="draft"),
                version=next_version,
                changelog=f"Rollback to version {version}",
            )
            self._insert_release(connection, release)
            self._update_row(
                connection,
                replace(
                    release.to_blueprint(status="published"),
                    version=release.version,
                    changelog=release.changelog,
                ),
            )
            return release

    def save_connector(self, connector: ConnectorSpec | Mapping[str, Any]) -> dict[str, Any]:
        """Persist public connector metadata; never persist credential_ref."""

        spec = (
            connector
            if isinstance(connector, ConnectorSpec)
            else ConnectorSpec.model_validate(connector)
        )
        public = spec.to_public_dict()
        payload = json.dumps(public, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO connectors (id, payload)
                VALUES (?, ?)
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload
                """,
                (spec.id, payload),
            )
        return public

    def get_connector(self, connector_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM connectors WHERE id = ?", (connector_id,)
            ).fetchone()
        if row is None:
            raise BlueprintNotFoundError(f"connector '{connector_id}'")
        return dict(json.loads(str(row[0])))

    def list_connectors(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = self._connection.execute("SELECT payload FROM connectors ORDER BY id").fetchall()
        return tuple(dict(json.loads(str(row[0]))) for row in rows)

    def export_bundle(self, blueprint_id: str) -> dict[str, Any]:
        blueprint = self.get(blueprint_id)
        releases = self.list_releases(blueprint_id) if self._has_releases(blueprint_id) else ()
        connector_ids = set(blueprint.connector_refs)
        connectors = [
            connector for connector in self.list_connectors() if connector["id"] in connector_ids
        ]
        return {
            "format": "mosaic-agent-blueprint-bundle",
            "schema_version": self.SCHEMA_VERSION,
            "blueprint": blueprint.to_dict(),
            "releases": [release.to_dict() for release in releases],
            "connectors": connectors,
        }

    def export_blueprint_bundle(self, blueprint_id: str) -> dict[str, Any]:
        return self.export_bundle(blueprint_id)

    def import_bundle(self, bundle: Mapping[str, Any]) -> AgentBlueprint:
        if bundle.get("format") != "mosaic-agent-blueprint-bundle":
            raise ValueError("unsupported blueprint bundle format")
        if int(bundle.get("schema_version", 0)) != self.SCHEMA_VERSION:
            raise ValueError("unsupported blueprint bundle schema version")
        blueprint_payload = bundle.get("blueprint")
        if not isinstance(blueprint_payload, Mapping):
            raise ValueError("bundle blueprint must be an object")
        blueprint = AgentBlueprint.from_dict(blueprint_payload)
        releases_payload = bundle.get("releases", ())
        connectors_payload = bundle.get("connectors", ())
        if not isinstance(releases_payload, (list, tuple)) or not isinstance(
            connectors_payload, (list, tuple)
        ):
            raise ValueError("bundle releases and connectors must be arrays")
        releases = tuple(
            ReleaseManifest.from_dict(item)
            for item in releases_payload
            if isinstance(item, Mapping)
        )
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT payload FROM blueprints WHERE id = ?", (blueprint.id,)
            ).fetchone()
            if existing is not None:
                current = AgentBlueprint.from_json(str(existing[0]))
                if current.fingerprint != blueprint.fingerprint:
                    raise ValueError(
                        f"blueprint '{blueprint.id}' already exists with different data"
                    )
            else:
                self._insert_blueprint(connection, blueprint)
            for payload in connectors_payload:
                if isinstance(payload, Mapping):
                    self._insert_connector(connection, payload)
            for release in releases:
                existing_release = connection.execute(
                    """
                    SELECT fingerprint FROM releases
                    WHERE blueprint_id = ? AND version = ?
                    """,
                    (release.blueprint_id, release.version),
                ).fetchone()
                if existing_release is None:
                    self._insert_release(connection, release)
                elif str(existing_release[0]) != release.fingerprint:
                    raise ValueError(
                        f"release {release.blueprint_id}@{release.version} conflicts "
                        "with existing data"
                    )
        return self.get(blueprint.id)

    def import_blueprint_bundle(self, bundle: Mapping[str, Any]) -> AgentBlueprint:
        return self.import_bundle(bundle)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
                self._restrict_database_permissions()

    def _configure(self) -> None:
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        if self.database_path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")

    def _migrate(self) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS blueprints (
                    id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS releases (
                    blueprint_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    release_id TEXT NOT NULL UNIQUE,
                    fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (blueprint_id, version),
                    FOREIGN KEY (blueprint_id) REFERENCES blueprints(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS connectors (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO schema_meta (key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(self.SCHEMA_VERSION),),
            )

    def _insert_blueprint(self, connection: sqlite3.Connection, blueprint: AgentBlueprint) -> None:
        try:
            connection.execute(
                """
                INSERT INTO blueprints
                    (id, slug, status, version, fingerprint, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    blueprint.id,
                    blueprint.slug,
                    blueprint.status,
                    blueprint.version,
                    blueprint.fingerprint,
                    blueprint.to_json(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"blueprint '{blueprint.id}' already exists") from exc

    def _update_row(self, connection: sqlite3.Connection, blueprint: AgentBlueprint) -> None:
        try:
            result = connection.execute(
                """
                UPDATE blueprints
                SET slug = ?, status = ?, version = ?, fingerprint = ?, payload = ?
                WHERE id = ?
                """,
                (
                    blueprint.slug,
                    blueprint.status,
                    blueprint.version,
                    blueprint.fingerprint,
                    blueprint.to_json(),
                    blueprint.id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"blueprint slug '{blueprint.slug}' already exists") from exc
        if result.rowcount != 1:
            raise BlueprintNotFoundError(blueprint.id)

    def _insert_release(self, connection: sqlite3.Connection, release: ReleaseManifest) -> None:
        try:
            connection.execute(
                """
                INSERT INTO releases
                    (blueprint_id, version, release_id, fingerprint, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    release.blueprint_id,
                    release.version,
                    release.release_id,
                    release.fingerprint,
                    release.to_json(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"release {release.blueprint_id}@{release.version} already exists"
            ) from exc

    def _insert_connector(self, connection: sqlite3.Connection, payload: Mapping[str, Any]) -> None:
        spec = ConnectorSpec.model_validate(dict(payload))
        public = spec.to_public_dict()
        connection.execute(
            """
            INSERT INTO connectors (id, payload)
            VALUES (?, ?)
            ON CONFLICT(id) DO UPDATE SET payload = excluded.payload
            """,
            (
                spec.id,
                json.dumps(public, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            ),
        )

    def _get_from_connection(
        self, connection: sqlite3.Connection, blueprint_id: str
    ) -> AgentBlueprint:
        row = connection.execute(
            "SELECT payload FROM blueprints WHERE id = ?", (blueprint_id,)
        ).fetchone()
        if row is None:
            raise BlueprintNotFoundError(blueprint_id)
        return AgentBlueprint.from_json(str(row[0]))

    def _get_release_from_connection(
        self, connection: sqlite3.Connection, blueprint_id: str, version: int
    ) -> ReleaseManifest:
        row = connection.execute(
            """
            SELECT payload FROM releases
            WHERE blueprint_id = ? AND version = ?
            """,
            (blueprint_id, version),
        ).fetchone()
        if row is None:
            self._raise_release_not_found(blueprint_id, version)
        return ReleaseManifest.from_json(str(row[0]))

    @staticmethod
    def _next_version(connection: sqlite3.Connection, blueprint_id: str) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM releases WHERE blueprint_id = ?",
            (blueprint_id,),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _canonical_blueprint(blueprint: AgentBlueprint) -> AgentBlueprint:
        return AgentBlueprint.from_json(blueprint.to_json())

    def _has_releases(self, blueprint_id: str) -> bool:
        with self._lock:
            return (
                self._connection.execute(
                    "SELECT 1 FROM releases WHERE blueprint_id = ? LIMIT 1", (blueprint_id,)
                ).fetchone()
                is not None
            )

    @staticmethod
    def _raise_release_not_found(blueprint_id: str, version: int | None) -> None:
        if version is None:
            raise BlueprintNotFoundError(f"no releases for blueprint '{blueprint_id}'")
        raise BlueprintNotFoundError(f"release {blueprint_id}@{version}")

    def _restrict_database_permissions(self) -> None:
        if self.database_path == ":memory:":
            return
        path = Path(self.database_path)
        for candidate in (
            path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ):
            if candidate.exists():
                self._restrict_permissions(candidate)

    @staticmethod
    def _restrict_permissions(path: Path) -> None:
        os.chmod(path, 0o600)


__all__ = [
    "BlueprintNotFoundError",
    "BlueprintRepository",
    "InMemoryBlueprintRepository",
    "SQLiteBlueprintRepository",
]
