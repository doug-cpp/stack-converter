"""Runs graphify CLI/library on a Python source directory with a deterministic Python AST fallback."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _should_skip_file(py_file: Path, source_root: Path) -> bool:
    rel_parts = py_file.relative_to(source_root).parts
    if any(p.startswith(".") or p in ("__pycache__", "venv", ".venv", "tests", "node_modules") for p in rel_parts):
        return True
    if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
        return True
    if py_file.name == "__init__.py" and py_file.stat().st_size < 64:
        return True
    return False


def _module_id_from_path(py_file: Path, source_root: Path) -> str:
    rel = py_file.relative_to(source_root).with_suffix("")
    parts = [p for p in rel.parts if p != "__init__"]
    return ".".join(parts) if parts else py_file.stem


def _ast_fallback_extract(source_root: Path) -> dict[str, Any]:
    """Deterministic structural extractor using Python's stdlib ast module."""
    py_files = sorted(
        f for f in source_root.rglob("*.py") if not _should_skip_file(f, source_root)
    )
    known_modules = {_module_id_from_path(f, source_root): f for f in py_files}
    short_to_full = {mod_id.split(".")[-1]: mod_id for mod_id in known_modules}

    raw_nodes: list[dict[str, Any]] = []
    raw_edges: list[dict[str, Any]] = []

    for mod_id, py_file in known_modules.items():
        rel_path = str(py_file.relative_to(source_root))
        source_text = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source_text, filename=rel_path)

        raw_nodes.append(
            {
                "id": mod_id,
                "name": mod_id.split(".")[-1],
                "type": "module",
                "file_path": rel_path,
                "line_start": 1,
                "line_end": max(1, len(source_text.splitlines())),
            }
        )

        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported = alias.name
                    target_mod = short_to_full.get(imported.split(".")[-1], imported)
                    raw_edges.append(
                        {
                            "source": mod_id,
                            "target": target_mod,
                            "type": "imports",
                            "line": getattr(node, "lineno", 1),
                        }
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "__future__":
                    continue
                short_name = node.module.split(".")[-1]
                target_mod = short_to_full.get(short_name, node.module)
                raw_edges.append(
                    {
                        "source": mod_id,
                        "target": target_mod,
                        "type": "imports",
                        "line": getattr(node, "lineno", 1),
                    }
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_id = f"{mod_id}:{node.name}"
                raw_nodes.append(
                    {
                        "id": fn_id,
                        "name": node.name,
                        "type": "function",
                        "file_path": rel_path,
                        "line_start": node.lineno,
                        "line_end": getattr(node, "end_lineno", node.lineno),
                    }
                )
                raw_edges.append(
                    {
                        "source": mod_id,
                        "target": fn_id,
                        "type": "defines",
                        "line": node.lineno,
                    }
                )
            elif isinstance(node, ast.ClassDef):
                cls_id = f"{mod_id}:{node.name}"
                raw_nodes.append(
                    {
                        "id": cls_id,
                        "name": node.name,
                        "type": "class",
                        "file_path": rel_path,
                        "line_start": node.lineno,
                        "line_end": getattr(node, "end_lineno", node.lineno),
                    }
                )
                raw_edges.append(
                    {
                        "source": mod_id,
                        "target": cls_id,
                        "type": "defines",
                        "line": node.lineno,
                    }
                )

    return {
        "extractor": "graphify+ast",
        "source_root": str(source_root.resolve()),
        "nodes": raw_nodes,
        "edges": raw_edges,
    }


def run_graphify(source_root: str | Path, output_path: str | Path | None = None) -> dict[str, Any]:
    """Run graphify on source_root (or fallback to deterministic AST extraction) and write raw_graph.json."""
    root = Path(source_root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Source directory does not exist: {root}")

    raw_graph: dict[str, Any] | None = None
    graphify_bin = shutil.which("graphify")
    if graphify_bin:
        try:
            res = subprocess.run(
                [graphify_bin, str(root), "--format", "json"],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            parsed = json.loads(res.stdout)
            if isinstance(parsed, dict) and "nodes" in parsed and "edges" in parsed:
                raw_graph = parsed
        except Exception:
            raw_graph = None

    if raw_graph is None:
        raw_graph = _ast_fallback_extract(root)

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(raw_graph, indent=2), encoding="utf-8")

    return raw_graph
