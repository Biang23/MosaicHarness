from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .api import MosaicPlatformAPI
from .connectors import ConnectorRegistry
from .repositories import SQLiteBlueprintRepository
from .service import MosaicPlatform

API_VERSION = "platform.v1"


class LocalControlPlaneApp:
    """Health/meta wrapper around the decoupled platform API."""

    def __init__(
        self,
        api: MosaicPlatformAPI,
        platform: MosaicPlatform,
        database_path: Path,
    ) -> None:
        self.api = api
        self.platform = platform
        self.database_path = database_path

    async def __call__(self, scope: Mapping[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("method") == "GET":
            path = str(scope.get("path", ""))
            if path == "/health":
                await self._json(
                    send,
                    200,
                    {
                        "status": "ok",
                        "api_version": API_VERSION,
                        "database_path": str(self.database_path),
                        "blueprints": len(self.platform.list_blueprints()),
                    },
                )
                return
            if path == "/meta":
                await self._json(
                    send,
                    200,
                    {
                        "api_version": API_VERSION,
                        "database_path": str(self.database_path),
                        "capabilities": [
                            "blueprints",
                            "templates",
                            "resources",
                            "preview",
                            "releases",
                        ],
                    },
                )
                return
        await self.api(scope, receive, send)

    async def _json(self, send: Any, status: int, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})


def create_app(
    runtime: Any,
    *,
    database_path: str | Path,
    cors_origins: tuple[str, ...] = (),
) -> LocalControlPlaneApp:
    path = Path(database_path).expanduser()
    repository = SQLiteBlueprintRepository(path)
    platform = MosaicPlatform(
        runtime,
        repository=repository,
        connectors=ConnectorRegistry(),
    )
    return LocalControlPlaneApp(
        MosaicPlatformAPI(platform, cors_origins=cors_origins),
        platform,
        path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local Mosaic Agent Foundry control plane")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--cors-origin", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("Install the optional 'platform' extra to run the server") from exc

    from ..core.runtime import MosaicHarness

    app = create_app(
        MosaicHarness(),
        database_path=args.database,
        cors_origins=tuple(args.cors_origin),
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["API_VERSION", "LocalControlPlaneApp", "build_parser", "create_app", "main"]
