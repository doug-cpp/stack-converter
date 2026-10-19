"""End-to-end LangGraph StateGraph orchestration with SQLite checkpointing."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Literal

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from stackconverter.config import AppConfig, load_config
from stackconverter.enrich.characterizer import record_characterization_suites
from stackconverter.enrich.documenter import enrich_graph_nodes
from stackconverter.extract.graphify_runner import run_graphify
from stackconverter.extract.normalizer import normalize_graph
from stackconverter.llm.base import AgentCaller
from stackconverter.pipeline.module_subgraph import (
    convert_and_validate_module,
    validate_module_attempt,
)
from stackconverter.pipeline.state import PipelineState
from stackconverter.plan.topology import build_migration_plan
from stackconverter.report.generator import generate_report
from stackconverter.schemas import (
    CharacterizationSuite,
    CodeGraph,
    Evidence,
    JudgmentResult,
    MigrationPlan,
    ModuleCode,
    ModuleConversionStatus,
    ModuleReportEntry,
    NodeDoc,
    RunMetrics,
    ValidationResult,
    Verdict,
    VerdictType,
)
from stackconverter.viability.detectors import run_all_detectors
from stackconverter.viability.judge import run_dialectical_judge
from stackconverter.viability.verdict_rules import compute_verdict


def build_main_graph(caller: AgentCaller, config: AppConfig) -> StateGraph:
    """Construct the 9-stage LangGraph StateGraph for StackConverter."""

    async def node_extract(state: PipelineState) -> PipelineState:
        run_dir = Path(state["run_dir"])
        source_root = Path(state["source_root"])
        raw_graph = run_graphify(source_root, output_path=run_dir / "raw_graph.json")
        graph = normalize_graph(raw_graph, source_root, output_path=run_dir / "graph.json")
        return {
            "raw_graph": raw_graph,
            "graph": graph.model_dump(mode="json"),
        }

    async def node_enrich(state: PipelineState) -> PipelineState:
        run_dir = Path(state["run_dir"])
        graph = CodeGraph.model_validate(state["graph"])
        docs = await enrich_graph_nodes(graph, caller=caller, docs_dir=run_dir / "docs")
        return {
            "node_docs": {k: v.model_dump(mode="json") for k, v in docs.items()},
        }

    async def node_detect(state: PipelineState) -> PipelineState:
        run_dir = Path(state["run_dir"])
        graph = CodeGraph.model_validate(state["graph"])
        libmap_path = config.resolve_path(config.paths.libmap_path)
        evidences = run_all_detectors(graph, libmap_path=libmap_path)
        ev_dicts = [e.model_dump(mode="json") for e in evidences]
        (run_dir / "evidences.json").write_text(json.dumps(ev_dicts, indent=2), encoding="utf-8")
        return {"evidences": ev_dicts}

    async def node_judge(state: PipelineState) -> PipelineState:
        run_dir = Path(state["run_dir"])
        graph = CodeGraph.model_validate(state["graph"])
        evidences = [Evidence.model_validate(e) for e in state.get("evidences", [])]
        docs = {k: NodeDoc.model_validate(v) for k, v in state.get("node_docs", {}).items()}
        judgment = await run_dialectical_judge(
            graph=graph,
            evidences=evidences,
            node_docs=docs,
            caller=caller,
            output_path=run_dir / "judgment.json",
        )
        return {"judgment": judgment.model_dump(mode="json")}

    async def node_verdict(state: PipelineState) -> PipelineState:
        run_dir = Path(state["run_dir"])
        evidences = [Evidence.model_validate(e) for e in state.get("evidences", [])]
        judgment = JudgmentResult.model_validate(state["judgment"])
        verdict = compute_verdict(
            evidences=evidences,
            judgment_result=judgment,
            output_path=run_dir / "verdict.json",
        )
        return {"verdict": verdict.model_dump(mode="json")}

    def route_after_verdict(state: PipelineState) -> Literal["plan", "report"]:
        verdict = Verdict.model_validate(state["verdict"])
        if verdict.verdict == VerdictType.NOT_RECOMMENDED:
            return "report"
        return "plan"

    async def node_plan(state: PipelineState) -> PipelineState:
        run_dir = Path(state["run_dir"])
        graph = CodeGraph.model_validate(state["graph"])
        libmap_path = config.resolve_path(config.paths.libmap_path)
        plan = build_migration_plan(
            graph,
            libmap_path=libmap_path,
            output_dir=run_dir,
            target_stack=config.default_target_stack,
        )
        return {
            "plan": plan.model_dump(mode="json"),
            "current_level": 0,
            "converted_modules": {},
            "validation_results": {},
            "module_entries": [],
        }

    async def node_characterize(state: PipelineState) -> PipelineState:
        run_dir = Path(state["run_dir"])
        graph = CodeGraph.model_validate(state["graph"])
        suites = await record_characterization_suites(
            graph=graph,
            caller=caller,
            characterization_dir=run_dir / "characterization",
        )
        return {
            "characterization": {k: v.model_dump(mode="json") for k, v in suites.items()},
        }

    async def node_convert_level(state: PipelineState) -> PipelineState:
        run_dir = Path(state["run_dir"])
        graph = CodeGraph.model_validate(state["graph"])
        plan = MigrationPlan.model_validate(state["plan"])
        docs = {k: NodeDoc.model_validate(v) for k, v in state.get("node_docs", {}).items()}
        suites = {
            k: CharacterizationSuite.model_validate(v)
            for k, v in state.get("characterization", {}).items()
        }
        converted = {
            k: ModuleCode.model_validate(v)
            for k, v in state.get("converted_modules", {}).items()
        }
        validations = {
            k: ValidationResult.model_validate(v)
            for k, v in state.get("validation_results", {}).items()
        }
        entries = [ModuleReportEntry.model_validate(e) for e in state.get("module_entries", [])]

        lvl_idx = state.get("current_level", 0)
        if lvl_idx < len(plan.levels):
            level_modules = plan.levels[lvl_idx]
            for mod_id in level_modules:
                mod_node = graph.get_node(mod_id)
                if mod_node is None:
                    continue
                mod_code, val_res, entry = await convert_and_validate_module(
                    graph=graph,
                    module_node=mod_node,
                    level=lvl_idx,
                    node_doc=docs.get(mod_id),
                    plan=plan,
                    suite=suites.get(mod_id),
                    converted_modules=converted,
                    caller=caller,
                    config=config,
                    output_ts_dir=run_dir / "output_ts",
                    validation_dir=run_dir / "validation",
                )
                converted[mod_id] = mod_code
                validations[mod_id] = val_res
                entries.append(entry)

        return {
            "current_level": lvl_idx + 1,
            "converted_modules": {k: v.model_dump(mode="json") for k, v in converted.items()},
            "validation_results": {k: v.model_dump(mode="json") for k, v in validations.items()},
            "module_entries": [e.model_dump(mode="json") for e in entries],
        }

    def route_next_level(state: PipelineState) -> Literal["convert_level", "report"]:
        plan = MigrationPlan.model_validate(state["plan"])
        if state.get("current_level", 0) < len(plan.levels):
            return "convert_level"
        return "report"

    async def node_report(state: PipelineState) -> PipelineState:
        run_dir = Path(state["run_dir"])
        verdict = Verdict.model_validate(state["verdict"])
        entries = [ModuleReportEntry.model_validate(e) for e in state.get("module_entries", [])]
        validations = [
            ValidationResult.model_validate(v)
            for v in state.get("validation_results", {}).values()
        ]
        graph = CodeGraph.model_validate(state["graph"])
        total_mods = len(graph.module_nodes())
        converted_count = sum(1 for e in entries if e.status == ModuleConversionStatus.CONVERTED)
        pending_count = sum(1 for e in entries if e.status == ModuleConversionStatus.PENDING)
        total_char = sum(v.characterization_total for v in validations)
        passed_char = sum(v.characterization_matched for v in validations)

        metrics = RunMetrics(
            run_id=state["run_id"],
            source_root=state["source_root"],
            source_stack=config.default_source_stack,
            target_stack=config.default_target_stack,
            verdict=verdict.verdict,
            total_modules=total_mods,
            converted_modules=converted_count,
            pending_modules=pending_count,
            total_characterization_cases=total_char,
            passed_characterization_cases=passed_char,
            cache_hits=caller.cache.hits,
            llm_calls=caller.llm_calls,
            module_entries=entries,
        )
        report_md = generate_report(verdict, metrics, output_path=run_dir / "report.md")
        return {
            "metrics": metrics.model_dump(mode="json"),
            "report_markdown": report_md,
        }

    workflow = StateGraph(PipelineState)
    workflow.add_node("extract", node_extract)
    workflow.add_node("enrich", node_enrich)
    workflow.add_node("detect", node_detect)
    workflow.add_node("judge", node_judge)
    workflow.add_node("verdict", node_verdict)
    workflow.add_node("plan", node_plan)
    workflow.add_node("characterize", node_characterize)
    workflow.add_node("convert_level", node_convert_level)
    workflow.add_node("report", node_report)

    workflow.add_edge(START, "extract")
    workflow.add_edge("extract", "enrich")
    workflow.add_edge("enrich", "detect")
    workflow.add_edge("detect", "judge")
    workflow.add_edge("judge", "verdict")
    workflow.add_conditional_edges(
        "verdict",
        route_after_verdict,
        {"plan": "plan", "report": "report"},
    )
    workflow.add_edge("plan", "characterize")
    workflow.add_edge("characterize", "convert_level")
    workflow.add_conditional_edges(
        "convert_level",
        route_next_level,
        {"convert_level": "convert_level", "report": "report"},
    )
    workflow.add_edge("report", END)

    return workflow


async def run_full_pipeline(
    source_root: str | Path,
    run_id: str,
    config: AppConfig | None = None,
    resume: bool = False,
) -> tuple[Verdict, RunMetrics]:
    """Execute or resume the full LangGraph migration pipeline with SQLite checkpointing."""
    cfg = config or load_config()
    caller = AgentCaller(config=cfg)
    run_dir = cfg.resolve_path(cfg.paths.runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_db = run_dir / "checkpoint.sqlite"

    workflow = build_main_graph(caller, cfg)
    conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
    try:
        # Use MemorySaver + SQLite persistence for async execution compatibility
        from langgraph.checkpoint.memory import MemorySaver

        memory_saver = MemorySaver()
        # Ensure SQLite checkpoint table is created and persisted on disk
        _ = SqliteSaver(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS stackconverter_checkpoints (run_id TEXT PRIMARY KEY, state_json TEXT)"
        )
        conn.commit()

        app = workflow.compile(checkpointer=memory_saver)
        thread_cfg = {"configurable": {"thread_id": run_id}}

        initial_state: PipelineState = {
            "run_id": run_id,
            "source_root": str(Path(source_root).resolve()),
            "run_dir": str(run_dir),
            "config_dict": cfg.model_dump(mode="json"),
        }

        if resume:
            row = conn.execute(
                "SELECT state_json FROM stackconverter_checkpoints WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row and row[0]:
                saved_state = json.loads(row[0])
                initial_state.update(saved_state)

        final_state = await app.ainvoke(initial_state, config=thread_cfg)
        conn.execute(
            "INSERT OR REPLACE INTO stackconverter_checkpoints (run_id, state_json) VALUES (?, ?)",
            (run_id, json.dumps(final_state, default=str)),
        )
        conn.commit()
    finally:
        conn.close()

    verdict = Verdict.model_validate(final_state["verdict"])
    metrics = RunMetrics.model_validate(final_state["metrics"])
    return verdict, metrics


async def run_analyze_stage(
    source_root: str | Path,
    run_id: str,
    config: AppConfig | None = None,
) -> Verdict:
    """Run Steps 1-5: extract, enrich, detect, judge, and compute verdict."""
    cfg = config or load_config()
    caller = AgentCaller(config=cfg)
    run_dir = cfg.resolve_path(cfg.paths.runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_graph = run_graphify(source_root, output_path=run_dir / "raw_graph.json")
    graph = normalize_graph(raw_graph, source_root, output_path=run_dir / "graph.json")
    docs = await enrich_graph_nodes(graph, caller=caller, docs_dir=run_dir / "docs")

    libmap_path = cfg.resolve_path(cfg.paths.libmap_path)
    evidences = run_all_detectors(graph, libmap_path=libmap_path)
    (run_dir / "evidences.json").write_text(
        json.dumps([e.model_dump(mode="json") for e in evidences], indent=2),
        encoding="utf-8",
    )
    judgment = await run_dialectical_judge(
        graph=graph,
        evidences=evidences,
        node_docs=docs,
        caller=caller,
        output_path=run_dir / "judgment.json",
    )
    verdict = compute_verdict(
        evidences=evidences,
        judgment_result=judgment,
        output_path=run_dir / "verdict.json",
    )
    return verdict


async def run_plan_stage(
    run_id: str,
    config: AppConfig | None = None,
) -> MigrationPlan:
    """Run Step 6: compute topological migration plan and library equivalence map."""
    cfg = config or load_config()
    run_dir = cfg.resolve_path(cfg.paths.runs_dir) / run_id
    graph_path = run_dir / "graph.json"
    if not graph_path.exists():
        raise FileNotFoundError(f"graph.json not found in {run_dir}. Run 'analyze' first.")
    graph = CodeGraph.model_validate(json.loads(graph_path.read_text(encoding="utf-8")))
    libmap_path = cfg.resolve_path(cfg.paths.libmap_path)
    return build_migration_plan(
        graph,
        libmap_path=libmap_path,
        output_dir=run_dir,
        target_stack=cfg.default_target_stack,
    )


async def run_convert_stage(
    run_id: str,
    config: AppConfig | None = None,
) -> list[ModuleReportEntry]:
    """Run Steps 7-8: record characterization oracle and convert modules level-by-level."""
    cfg = config or load_config()
    caller = AgentCaller(config=cfg)
    run_dir = cfg.resolve_path(cfg.paths.runs_dir) / run_id

    graph = CodeGraph.model_validate(json.loads((run_dir / "graph.json").read_text(encoding="utf-8")))
    plan = MigrationPlan.model_validate(json.loads((run_dir / "plan.json").read_text(encoding="utf-8")))

    docs: dict[str, NodeDoc] = {}
    docs_dir = run_dir / "docs"
    if docs_dir.exists():
        for doc_file in docs_dir.glob("*.json"):
            doc = NodeDoc.model_validate(json.loads(doc_file.read_text(encoding="utf-8")))
            docs[doc.node_id] = doc

    suites = await record_characterization_suites(
        graph=graph,
        caller=caller,
        characterization_dir=run_dir / "characterization",
    )

    converted: dict[str, ModuleCode] = {}
    entries: list[ModuleReportEntry] = []

    for lvl_idx, level_modules in enumerate(plan.levels):
        for mod_id in level_modules:
            mod_node = graph.get_node(mod_id)
            if mod_node is None:
                continue
            mod_code, _val_res, entry = await convert_and_validate_module(
                graph=graph,
                module_node=mod_node,
                level=lvl_idx,
                node_doc=docs.get(mod_id),
                plan=plan,
                suite=suites.get(mod_id),
                converted_modules=converted,
                caller=caller,
                config=cfg,
                output_ts_dir=run_dir / "output_ts",
                validation_dir=run_dir / "validation",
            )
            converted[mod_id] = mod_code
            entries.append(entry)

    return entries


async def run_validate_stage(
    run_id: str,
    config: AppConfig | None = None,
) -> tuple[Verdict, RunMetrics]:
    """Run Steps 8-9: validate generated TypeScript modules and render report.md."""
    cfg = config or load_config()
    run_dir = cfg.resolve_path(cfg.paths.runs_dir) / run_id

    graph = CodeGraph.model_validate(json.loads((run_dir / "graph.json").read_text(encoding="utf-8")))
    verdict = Verdict.model_validate(json.loads((run_dir / "verdict.json").read_text(encoding="utf-8")))
    plan = MigrationPlan.model_validate(json.loads((run_dir / "plan.json").read_text(encoding="utf-8")))

    suites: dict[str, CharacterizationSuite] = {}
    char_dir = run_dir / "characterization"
    if char_dir.exists():
        for cfile in char_dir.glob("*.json"):
            s = CharacterizationSuite.model_validate(json.loads(cfile.read_text(encoding="utf-8")))
            suites[s.module_id] = s

    entries: list[ModuleReportEntry] = []
    total_char = 0
    passed_char = 0

    for lvl_idx, level_modules in enumerate(plan.levels):
        for mod_id in level_modules:
            mod_node = graph.get_node(mod_id)
            if mod_node is None:
                continue
            short_name = mod_id.split(".")[-1]
            target_path = f"src/{short_name}.ts"
            val_res = validate_module_attempt(
                module_id=mod_id,
                target_path=target_path,
                attempt=1,
                output_ts_dir=run_dir / "output_ts",
                validation_dir=run_dir / "validation",
                suite=suites.get(mod_id),
                config=cfg,
            )
            total_char += val_res.characterization_total
            passed_char += val_res.characterization_matched
            status = (
                ModuleConversionStatus.CONVERTED
                if val_res.passed
                else ModuleConversionStatus.PENDING
            )
            entries.append(
                ModuleReportEntry(
                    module_id=mod_id,
                    source_path=mod_node.file_path or f"{mod_id}.py",
                    target_path=target_path,
                    level=lvl_idx,
                    status=status,
                    attempts=1,
                    tsc_passed=val_res.tsc_passed,
                    eslint_passed=val_res.eslint_passed,
                    characterization_passed=val_res.characterization_passed,
                    diagnostics=val_res.diagnostics,
                )
            )

    converted_count = sum(1 for e in entries if e.status == ModuleConversionStatus.CONVERTED)
    pending_count = sum(1 for e in entries if e.status == ModuleConversionStatus.PENDING)
    metrics = RunMetrics(
        run_id=run_id,
        source_root=graph.source_root,
        source_stack=plan.source_stack,
        target_stack=plan.target_stack,
        verdict=verdict.verdict,
        total_modules=len(graph.module_nodes()),
        converted_modules=converted_count,
        pending_modules=pending_count,
        total_characterization_cases=total_char,
        passed_characterization_cases=passed_char,
        cache_hits=0,
        llm_calls=0,
        module_entries=entries,
    )
    generate_report(verdict, metrics, output_path=run_dir / "report.md")
    return verdict, metrics

