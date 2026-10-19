"""Resolves external Python imports against libmap/python_to_ts.yaml."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from stackconverter.schemas import CodeGraph, LibMapEntry, LibMapStatus


def resolve_library_mappings(
    graph: CodeGraph,
    libmap_path: str | Path | None = None,
) -> list[LibMapEntry]:
    """Resolve all external imports used by modules in the CodeGraph against python_to_ts.yaml."""
    if libmap_path is None:
        libmap_path = Path(__file__).resolve().parent.parent.parent / "libmap" / "python_to_ts.yaml"
    else:
        libmap_path = Path(libmap_path)

    raw_data: dict = {}
    if libmap_path.exists():
        raw_data = yaml.safe_load(libmap_path.read_text(encoding="utf-8")) or {}

    stdlib_map: dict = raw_data.get("stdlib") or {}
    third_party_map: dict = raw_data.get("third_party") or {}
    unsupported_map: dict = raw_data.get("unsupported") or {}

    internal_modules = {m.id for m in graph.module_nodes()} | {
        m.id.split(".")[0] for m in graph.module_nodes()
    } | {m.name for m in graph.module_nodes()}

    external_pkgs: set[str] = set()
    for mod in graph.module_nodes():
        for imp in mod.imports:
            root_pkg = imp.split(".")[0]
            if root_pkg not in internal_modules:
                external_pkgs.add(root_pkg)

    entries: list[LibMapEntry] = []
    for pkg in sorted(external_pkgs):
        if pkg in unsupported_map:
            info = unsupported_map[pkg] or {}
            entries.append(
                LibMapEntry(
                    python_package=pkg,
                    ts_equivalent=info.get("ts_equivalent"),
                    npm_package=info.get("npm_package"),
                    status=LibMapStatus.UNSUPPORTED,
                    notes=str(info.get("notes", "")),
                )
            )
        elif pkg in stdlib_map:
            info = stdlib_map[pkg] or {}
            entries.append(
                LibMapEntry(
                    python_package=pkg,
                    ts_equivalent=info.get("ts_equivalent", "Node.js stdlib"),
                    npm_package=info.get("npm_package"),
                    status=LibMapStatus.STDLIB,
                    notes=str(info.get("notes", "")),
                )
            )
        elif pkg in third_party_map:
            info = third_party_map[pkg] or {}
            entries.append(
                LibMapEntry(
                    python_package=pkg,
                    ts_equivalent=info.get("ts_equivalent"),
                    npm_package=info.get("npm_package"),
                    status=LibMapStatus.MAPPED,
                    notes=str(info.get("notes", "")),
                )
            )
        elif pkg in sys.stdlib_module_names:
            entries.append(
                LibMapEntry(
                    python_package=pkg,
                    ts_equivalent="Node.js / ES2022 built-in",
                    npm_package=None,
                    status=LibMapStatus.STDLIB,
                    notes="Standard library module.",
                )
            )
        else:
            entries.append(
                LibMapEntry(
                    python_package=pkg,
                    ts_equivalent=None,
                    npm_package=None,
                    status=LibMapStatus.UNMAPPED,
                    notes="Not present in libmap/python_to_ts.yaml.",
                )
            )

    return entries
