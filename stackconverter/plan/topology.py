"""Topological sorting of internal modules into conversion levels with SCC cycle grouping."""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

from stackconverter.plan.libmap import resolve_library_mappings
from stackconverter.schemas import CodeGraph, CycleGroup, EdgeType, MigrationPlan


def compute_topological_levels(graph: CodeGraph) -> tuple[list[list[str]], list[CycleGroup]]:
    """Compute bottom-up conversion levels (level 0 = leaves with no internal dependencies)."""
    module_ids = sorted(m.id for m in graph.module_nodes())
    module_set = set(module_ids)

    # Directed graph where edge u -> v means module u depends on (imports) module v
    dep_graph = nx.DiGraph()
    for m_id in module_ids:
        dep_graph.add_node(m_id)

    for edge in graph.edges:
        if edge.edge_type == EdgeType.IMPORTS and edge.source in module_set and edge.target in module_set:
            if edge.source != edge.target:
                dep_graph.add_edge(edge.source, edge.target)

    # Detect strongly connected components (cycles)
    sccs = list(nx.strongly_connected_components(dep_graph))
    cycles: list[CycleGroup] = []
    node_to_scc: dict[str, str] = {}
    scc_members: dict[str, list[str]] = {}

    cycle_idx = 0
    for comp in sorted(sccs, key=lambda c: sorted(c)[0]):
        sorted_members = sorted(comp)
        if len(sorted_members) > 1:
            cycle_idx += 1
            group_id = f"cycle_{cycle_idx}"
            cycles.append(CycleGroup(group_id=group_id, modules=sorted_members))
        else:
            group_id = sorted_members[0]
        scc_members[group_id] = sorted_members
        for m in sorted_members:
            node_to_scc[m] = group_id

    # Build condensation DAG where edge C_dep -> C_consumer means C_dep must be converted BEFORE C_consumer
    dag = nx.DiGraph()
    for gid in scc_members:
        dag.add_node(gid)

    for u, v in dep_graph.edges():
        gu, gv = node_to_scc[u], node_to_scc[v]
        if gu != gv:
            # u imports v => v (gv) must be converted before u (gu)
            dag.add_edge(gv, gu)

    # Kahn's algorithm by generation
    levels: list[list[str]] = []
    remaining = set(dag.nodes())
    while remaining:
        zero_in = sorted(
            n for n in remaining if all(pred not in remaining for pred in dag.predecessors(n))
        )
        if not zero_in:
            zero_in = sorted(remaining)
        expanded_level: list[str] = []
        for gid in zero_in:
            expanded_level.extend(scc_members[gid])
            remaining.remove(gid)
        levels.append(sorted(expanded_level))

    return levels, cycles


def _render_plan_markdown(plan: MigrationPlan) -> str:
    lines = [
        f"# Migration Plan (`{plan.source_stack}` -> `{plan.target_stack}`)",
        "",
        "## Topological Conversion Levels (Leaves -> Entry Points)",
        "",
    ]
    for idx, level in enumerate(plan.levels):
        mods = ", ".join(f"`{m}`" for m in level)
        lines.append(f"- **Level {idx}:** {mods}")

    if plan.cycles:
        lines.extend(["", "## Detected Dependency Cycles", ""])
        for c in plan.cycles:
            lines.append(f"- **{c.group_id}:** {', '.join(f'`{m}`' for m in c.modules)}")

    lines.extend(
        [
            "",
            "## Library Equivalence Map",
            "",
            "| Python Package | Status | Target Equivalent | Notes |",
            "|---|---|---|---|",
        ]
    )
    for entry in plan.library_mappings:
        lines.append(
            f"| `{entry.python_package}` | `{entry.status.value}` | {entry.ts_equivalent or 'N/A'} | {entry.notes} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_migration_plan(
    graph: CodeGraph,
    libmap_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    target_stack: str = "typescript-node",
) -> MigrationPlan:
    """Build and persist the topological MigrationPlan (`plan.json` and `plan.md`)."""
    from stackconverter.schemas import resolve_target_stack

    spec = resolve_target_stack(target_stack)
    levels, cycles = compute_topological_levels(graph)
    lib_mappings = resolve_library_mappings(graph, libmap_path=libmap_path)
    plan = MigrationPlan(
        levels=levels,
        cycles=cycles,
        library_mappings=lib_mappings,
        source_stack=spec.source_stack,
        target_stack=spec.id,
        target_language=spec.target_language,
    )

    if output_dir is not None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "plan.json").write_text(json.dumps(plan.model_dump(mode="json"), indent=2), encoding="utf-8")
        (out / "plan.md").write_text(_render_plan_markdown(plan), encoding="utf-8")

    return plan

