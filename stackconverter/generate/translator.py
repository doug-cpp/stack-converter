"""Translator Agent invocation and TypeScript project scaffolding."""

from __future__ import annotations

import json
from pathlib import Path

from stackconverter.generate.context import build_translation_context
from stackconverter.llm.base import AgentCaller
from stackconverter.schemas import CodeGraph, MigrationPlan, ModuleCode, Node, NodeDoc


def ensure_ts_project_scaffold(output_ts_dir: str | Path) -> Path:
    """Create package.json, tsconfig.json, and src/ inside output_ts_dir if not present."""
    out_dir = Path(output_ts_dir)
    src_dir = out_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    pkg_json_path = out_dir / "package.json"
    if not pkg_json_path.exists():
        pkg_data = {
            "name": "migrated-ts-project",
            "version": "0.1.0",
            "private": True,
            "type": "module",
            "scripts": {
                "typecheck": "tsc --noEmit --strict",
            },
        }
        pkg_json_path.write_text(json.dumps(pkg_data, indent=2) + "\n", encoding="utf-8")

    tsconfig_path = out_dir / "tsconfig.json"
    if not tsconfig_path.exists():
        tsconfig_data = {
            "compilerOptions": {
                "target": "ES2022",
                "module": "ESNext",
                "moduleResolution": "bundler",
                "strict": True,
                "noImplicitAny": True,
                "strictNullChecks": True,
                "noUnusedLocals": False,
                "noUnusedParameters": False,
                "esModuleInterop": True,
                "skipLibCheck": True,
                "forceConsistentCasingInFileNames": True,
                "noEmit": True,
                "rootDir": "src",
            },
            "include": ["src/**/*.ts"],
        }
        tsconfig_path.write_text(json.dumps(tsconfig_data, indent=2) + "\n", encoding="utf-8")

    return out_dir


def write_module_code(output_ts_dir: str | Path, module_code: ModuleCode) -> Path:
    """Write the generated TypeScript file into output_ts_dir."""
    out_dir = ensure_ts_project_scaffold(output_ts_dir)
    target_file = out_dir / module_code.target_path
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(module_code.typescript_code, encoding="utf-8")
    return target_file


async def translate_module(
    graph: CodeGraph,
    module_node: Node,
    node_doc: NodeDoc | None,
    plan: MigrationPlan,
    converted_modules: dict[str, ModuleCode],
    caller: AgentCaller,
    output_ts_dir: str | Path,
    rules_path: str | Path | None = None,
) -> ModuleCode:
    """Translate a Python module node to TypeScript via the Translator Agent and write to disk."""
    payload = build_translation_context(
        graph=graph,
        module_node=module_node,
        node_doc=node_doc,
        plan=plan,
        converted_modules=converted_modules,
        rules_path=rules_path,
    )
    module_code = await caller.call_agent("translator", payload, ModuleCode)
    write_module_code(output_ts_dir, module_code)
    return module_code
