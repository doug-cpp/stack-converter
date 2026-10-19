"""Characterizer Agent and real Python execution harness to record JSON I/O oracle suites."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from stackconverter.llm.base import AgentCaller
from stackconverter.schemas import (
    CharacterizationCase,
    CharacterizationProposal,
    CharacterizationSuite,
    CodeGraph,
    Node,
    NodeType,
)


def _is_json_serializable(value: Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, OverflowError):
        return False


def _execute_python_module_cases(
    source_root: Path,
    mod_node: Node,
    proposed_cases: list[CharacterizationCase],
) -> list[CharacterizationCase]:
    """Import the real Python module and record actual return values for each proposed input."""
    if not mod_node.file_path:
        return []
    full_path = (source_root / mod_node.file_path).resolve()
    if not full_path.exists():
        return []

    added_sys_path = False
    root_str = str(source_root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
        added_sys_path = True

    recorded: list[CharacterizationCase] = []
    try:
        spec = importlib.util.spec_from_file_location(mod_node.id, full_path)
        if spec is None or spec.loader is None:
            return []
        module_obj = importlib.util.module_from_spec(spec)
        sys.modules[mod_node.id] = module_obj
        spec.loader.exec_module(module_obj)

        for case in proposed_cases:
            fn = getattr(module_obj, case.function_name, None)
            if not callable(fn):
                continue
            try:
                result = fn(*case.args, **case.kwargs)
                if _is_json_serializable(result):
                    recorded.append(
                        CharacterizationCase(
                            function_name=case.function_name,
                            args=case.args,
                            kwargs=case.kwargs,
                            expected_output=json.loads(json.dumps(result)),
                            raises_exception=None,
                        )
                    )
            except Exception as exc:
                recorded.append(
                    CharacterizationCase(
                        function_name=case.function_name,
                        args=case.args,
                        kwargs=case.kwargs,
                        expected_output=None,
                        raises_exception=type(exc).__name__,
                    )
                )
    finally:
        if added_sys_path and root_str in sys.path:
            sys.path.remove(root_str)

    return recorded


async def record_characterization_suites(
    graph: CodeGraph,
    caller: AgentCaller,
    characterization_dir: str | Path | None = None,
) -> dict[str, CharacterizationSuite]:
    """Generate test inputs via Characterizer Agent and record real Python outputs as JSON oracle."""
    source_root = Path(graph.source_root)
    out_dir = Path(characterization_dir) if characterization_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    suites: dict[str, CharacterizationSuite] = {}

    for mod in graph.module_nodes():
        if not mod.file_path:
            continue
        fn_nodes = [
            n
            for n in graph.nodes
            if n.node_type == NodeType.FUNCTION
            and n.file_path == mod.file_path
            and n.is_public
        ]
        if not fn_nodes:
            suites[mod.id] = CharacterizationSuite(
                module_id=mod.id,
                file_path=mod.file_path,
                cases=[],
            )
            continue

        payload = {
            "module_id": mod.id,
            "file_path": mod.file_path,
            "functions": [
                {
                    "name": fn.name,
                    "signature": fn.signature,
                    "parameters": [p.model_dump(mode="json") for p in fn.parameters],
                    "return_annotation": fn.return_annotation,
                    "docstring": fn.docstring,
                }
                for fn in fn_nodes
            ],
        }
        proposal = await caller.call_agent("characterizer", payload, CharacterizationProposal)
        recorded_cases = _execute_python_module_cases(source_root, mod, proposal.cases)
        suite = CharacterizationSuite(
            module_id=mod.id,
            file_path=mod.file_path,
            cases=recorded_cases,
        )
        suites[mod.id] = suite

        if out_dir:
            safe_name = mod.id.replace(".", "_")
            (out_dir / f"{safe_name}.json").write_text(
                json.dumps(suite.model_dump(mode="json"), indent=2),
                encoding="utf-8",
            )

    return suites
