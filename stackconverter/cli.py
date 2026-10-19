"""Typer CLI and Rich terminal visualization for StackConverter."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.tree import Tree

from stackconverter.config import ProviderName, load_config
from stackconverter.pipeline.main_graph import (
    run_analyze_stage,
    run_convert_stage,
    run_full_pipeline,
    run_plan_stage,
    run_validate_stage,
)
from stackconverter.report.generator import print_terminal_summary
from stackconverter.schemas import (
    TARGET_STACK_REGISTRY,
    RunMetrics,
    TargetStackSpec,
    TargetStackStatus,
    resolve_target_stack,
)

app = typer.Typer(
    name="stackconverter",
    help="AI-Assisted Source Code Migration Accelerator with a Deterministic Codebase Graph and Viability Gate.",
    no_args_is_help=True,
)
console = Console()


def _default_run_id() -> str:
    return "run_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def _print_target_catalog_table(title: str = "Target Output Stack Catalog") -> None:
    table = Table(title=title)
    table.add_column("Stack ID", style="bold cyan")
    table.add_column("Aliases")
    table.add_column("Source -> Target", style="bold")
    table.add_column("Deterministic Validators")
    table.add_column("Status", justify="center")

    for spec in TARGET_STACK_REGISTRY.values():
        status_badge = (
            "[bold green]AVAILABLE (PoC)[/bold green]"
            if spec.status == TargetStackStatus.AVAILABLE
            else "[dim yellow]ROADMAP[/dim yellow]"
        )
        table.add_row(
            spec.id,
            ", ".join(spec.aliases),
            f"{spec.source_stack} -> {spec.display_name}",
            ", ".join(spec.validators),
            status_badge,
        )
    console.print(table)


def _select_target_stack(target_option: str | None) -> TargetStackSpec:
    """Resolve explicit --target flag or prompt interactively if running in a live TTY."""
    chosen = target_option
    if chosen is None and sys.stdin.isatty() and os.getenv("STACKCONVERTER_NON_INTERACTIVE") != "1":
        _print_target_catalog_table(title="Select the Target Output Stack")
        chosen = Prompt.ask(
            "[bold cyan]Select the target output stack[/bold cyan]",
            default="typescript-node",
            console=console,
        )

    try:
        spec = resolve_target_stack(chosen)
    except ValueError as exc:
        console.print(
            Panel(
                f"[bold red]{exc}[/bold red]",
                title="Unsupported Target Output Stack",
                border_style="red",
            )
        )
        raise typer.Exit(code=1) from exc

    console.print(
        f"[bold cyan]Target Output Stack:[/bold cyan] [green]{spec.id}[/green] "
        f"({spec.source_stack} -> {spec.display_name})"
    )
    return spec


@app.command("targets")
def cmd_targets() -> None:
    """List registered target output stacks, aliases, validators, and PoC availability status."""
    _print_target_catalog_table()


@app.command("run")
def cmd_run(
    source_dir: Annotated[
        Path,
        typer.Argument(help="Path to the source Python project directory."),
    ],
    target: Annotated[
        str | None,
        typer.Option(
            "--target",
            "-t",
            help="Select the target output stack (e.g., 'typescript-node' or alias 'typescript'). Prompts if omitted in interactive terminal.",
        ),
    ] = None,
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Identifier for the output run directory under runs/<run_id>."),
    ] = None,
    resume: Annotated[
        str | None,
        typer.Option("--resume", help="Resume an existing interrupted run by its run_id."),
    ] = None,
    cache_dir: Annotated[
        str | None,
        typer.Option("--cache-dir", help="Override the LLM SHA-256 disk cache directory (e.g., demo_cache)."),
    ] = None,
    provider: Annotated[
        ProviderName | None,
        typer.Option("--provider", help="Override LLM provider (fake | gemini_api | claude_subscription)."),
    ] = None,
) -> None:
    """Run the complete end-to-end StackConverter pipeline (Steps 1 through 9)."""
    spec = _select_target_stack(target)
    effective_run_id = resume or run_id or _default_run_id()
    cfg = load_config(
        provider_override=provider,
        cache_dir_override=cache_dir,
        target_stack_override=spec.id,
    )

    verdict, metrics = asyncio.run(
        run_full_pipeline(
            source_root=source_dir,
            run_id=effective_run_id,
            config=cfg,
            resume=bool(resume),
        )
    )
    print_terminal_summary(verdict, metrics, console=console)
    run_path = cfg.resolve_path(cfg.paths.runs_dir) / effective_run_id
    console.print(f"\n[bold green]Artifacts saved to:[/bold green] {run_path}")


@app.command("analyze")
def cmd_analyze(
    source_dir: Annotated[
        Path,
        typer.Argument(help="Path to the source Python project directory."),
    ],
    target: Annotated[
        str | None,
        typer.Option(
            "--target",
            "-t",
            help="Select the target output stack (e.g., 'typescript-node').",
        ),
    ] = None,
    run_id: Annotated[
        str,
        typer.Option("--run-id", help="Run identifier under runs/<run_id>."),
    ] = "default_run",
    cache_dir: Annotated[
        str | None,
        typer.Option("--cache-dir", help="Override LLM disk cache directory."),
    ] = None,
    provider: Annotated[
        ProviderName | None,
        typer.Option("--provider", help="Override LLM provider."),
    ] = None,
) -> None:
    """Steps 1-5: Extract graph, enrich docs, run AST detectors, and compute Viability Verdict."""
    spec = _select_target_stack(target)
    cfg = load_config(
        provider_override=provider,
        cache_dir_override=cache_dir,
        target_stack_override=spec.id,
    )
    verdict = asyncio.run(run_analyze_stage(source_root=source_dir, run_id=run_id, config=cfg))
    dummy_metrics = RunMetrics(
        run_id=run_id,
        source_root=str(source_dir.resolve()),
        source_stack=spec.source_stack,
        target_stack=spec.id,
        verdict=verdict.verdict,
    )
    print_terminal_summary(verdict, dummy_metrics, console=console)


@app.command("plan")
def cmd_plan(
    run_id: Annotated[
        str,
        typer.Option("--run-id", help="Run identifier previously initialized by 'analyze'."),
    ] = "default_run",
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Select the target output stack (default: 'typescript-node')."),
    ] = None,
) -> None:
    """Step 6: Compute topological migration levels and library equivalence map."""
    spec = resolve_target_stack(target)
    cfg = load_config(target_stack_override=spec.id)
    plan = asyncio.run(run_plan_stage(run_id=run_id, config=cfg))

    tree = Tree(
        f"[bold cyan]Topological Migration Plan ({plan.source_stack} -> {plan.target_stack}) — Run '{run_id}'[/bold cyan]"
    )
    for idx, level in enumerate(plan.levels):
        lvl_branch = tree.add(f"[bold yellow]Level {idx}[/bold yellow] (Leaves -> Entry Points)")
        for mod in level:
            lvl_branch.add(f"[green]{mod}[/green]")
    console.print(tree)

    if plan.library_mappings:
        lib_table = Table(title="Library Equivalence Map")
        lib_table.add_column("Python Package", style="cyan")
        lib_table.add_column("Status", style="bold")
        lib_table.add_column("Target Equivalent")
        lib_table.add_column("Notes")
        for entry in plan.library_mappings:
            lib_table.add_row(
                entry.python_package,
                entry.status.value,
                entry.ts_equivalent or "N/A",
                entry.notes,
            )
        console.print(lib_table)


@app.command("convert")
def cmd_convert(
    run_id: Annotated[
        str,
        typer.Option("--run-id", help="Run identifier previously planned by 'plan'."),
    ] = "default_run",
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Select the target output stack (default: 'typescript-node')."),
    ] = None,
    cache_dir: Annotated[
        str | None,
        typer.Option("--cache-dir", help="Override LLM disk cache directory."),
    ] = None,
    provider: Annotated[
        ProviderName | None,
        typer.Option("--provider", help="Override LLM provider."),
    ] = None,
) -> None:
    """Steps 7-8: Record Python characterization oracle and translate modules level-by-level."""
    spec = resolve_target_stack(target)
    cfg = load_config(
        provider_override=provider,
        cache_dir_override=cache_dir,
        target_stack_override=spec.id,
    )
    entries = asyncio.run(run_convert_stage(run_id=run_id, config=cfg))
    console.print(
        f"[bold green]Converted {len(entries)} module(s) to '{spec.id}' for run '{run_id}'.[/bold green]"
    )


@app.command("validate")
def cmd_validate(
    run_id: Annotated[
        str,
        typer.Option("--run-id", help="Run identifier to validate and generate report.md."),
    ] = "default_run",
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Select the target output stack (default: 'typescript-node')."),
    ] = None,
) -> None:
    """Steps 8-9: Run tsc/eslint/characterization validation and generate final report.md."""
    spec = resolve_target_stack(target)
    cfg = load_config(target_stack_override=spec.id)
    verdict, metrics = asyncio.run(run_validate_stage(run_id=run_id, config=cfg))
    print_terminal_summary(verdict, metrics, console=console)


if __name__ == "__main__":
    app()
