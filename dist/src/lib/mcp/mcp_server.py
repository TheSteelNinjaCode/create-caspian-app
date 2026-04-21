from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASPIAN_CONFIG_PATH = PROJECT_ROOT / "caspian.config.json"
PACKAGE_JSON_PATH = PROJECT_ROOT / "package.json"
FILES_LIST_PATH = PROJECT_ROOT / "settings" / "files-list.json"
COMPONENT_MAP_PATH = PROJECT_ROOT / "settings" / "component-map.json"


mcp = FastMCP(
    name="Mapka MCP",
    instructions=(
        "Read-only workspace metadata for the Mapka Caspian application. "
        "Use these tools for project configuration, generated file inventory, and component discovery."
    ),
)


def _load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_paths(paths: list[str]) -> list[str]:
    return [item.removeprefix("./").replace("\\", "/") for item in paths]


@mcp.tool
def project_info() -> dict[str, Any]:
    """Return the core Caspian and package metadata for this workspace."""

    config = _load_json(CASPIAN_CONFIG_PATH, {})
    package = _load_json(PACKAGE_JSON_PATH, {})

    return {
        "projectName": config.get("projectName") or package.get("name") or PROJECT_ROOT.name,
        "projectRoot": str(PROJECT_ROOT),
        "packageVersion": package.get("version"),
        "caspianVersion": config.get("version"),
        "browserSyncTarget": config.get("bsTarget"),
        "featureFlags": {
            "backendOnly": config.get("backendOnly"),
            "tailwindcss": config.get("tailwindcss"),
            "mcp": config.get("mcp"),
            "prisma": config.get("prisma"),
            "typescript": config.get("typescript"),
        },
        "componentScanDirs": config.get("componentScanDirs", []),
    }


@mcp.tool
def workspace_files(kind: Literal["all", "app", "public"] = "all") -> dict[str, Any]:
    """Return the generated workspace file inventory, optionally filtered by area."""

    files = _normalize_paths(_load_json(FILES_LIST_PATH, []))

    if kind == "app":
        selected = [path for path in files if path.startswith("src/app/")]
    elif kind == "public":
        selected = [path for path in files if path.startswith("public/")]
    else:
        selected = files

    return {
        "kind": kind,
        "count": len(selected),
        "files": selected,
    }


@mcp.tool
def component_inventory() -> dict[str, Any]:
    """Return the latest generated component inventory for the workspace."""

    components = _load_json(COMPONENT_MAP_PATH, [])

    return {
        "count": len(components),
        "components": components,
    }