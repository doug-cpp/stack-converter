"""Renders report.md and prints Rich summary tables in the terminal."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from stackconverter.schemas import RunMetrics, Verdict, VerdictType


def generate_report(
    verdict: Verdict,
    metrics: RunMetrics,
    output_path: str | Path | None = None,
) -> str:
    """Render the executive Markdown report from Verdict and RunMetrics."""
    template_path = Path(__file__).resolve().parent / "template.md"
    template = template_path.read_text(encoding="utf-8")

    axes_rows = [
        f"| `{a.axis.value}` | **{a.risk_level.value.upper()}** | {'Yes' if a.has_central_high_risk else 'No'} | {a.summary} |"
        for a in verdict.axes
    ]
    axes_table = "\n".join(axes_rows)

    if verdict.blocking_evidences:
        b_lines = ["### Blocking Architectural Evidences (`file:line`)", ""]
        for ev in verdict.blocking_evidences:
            b_lines.append(
                f"- **`{ev.file_path}:{ev.line}`** (`{ev.axis.value}` / `{ev.detector}`): {ev.description}  \n"
                f"  Snippet: `{ev.snippet}`"
            )
        blocking_section = "\n".join(b_lines)
    else:
        blocking_section = "### Blocking Architectural Evidences\n\nNone."

    if verdict.caveats:
        c_lines = ["### Technical Debt & Caveats", ""]
        for cav in verdict.caveats:
            c_lines.append(f"- {cav}")
        caveats_section = "\n".join(c_lines)
    else:
        caveats_section = "### Technical Debt & Caveats\n\nNone."

    if verdict.suggested_alternatives:
        alt_lines = ["### Suggested Alternative Target Architectures", ""]
        for alt in verdict.suggested_alternatives:
            alt_lines.append(f"- {alt}")
        alternatives_section = "\n".join(alt_lines)
    else:
        alternatives_section = ""

    if verdict.verdict == VerdictType.NOT_RECOMMENDED:
        conversion_section = (
            "> **Migration Halted by Viability Gate:** Code translation was intentionally skipped because "
            "central high-risk incompatibilities make a direct TypeScript migration unsafe."
        )
    else:
        conv_lines = [
            f"- **Modules Converted:** `{metrics.converted_modules} / {metrics.total_modules}`",
            f"- **Pending Modules:** `{metrics.pending_modules}`",
            f"- **Characterization Oracle Cases Passed:** `{metrics.passed_characterization_cases} / {metrics.total_characterization_cases}`",
            "",
            "| Module | Level | Target Path | Status | Attempts | `tsc` | `eslint` | Oracle |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for entry in metrics.module_entries:
            conv_lines.append(
                f"| `{entry.module_id}` | {entry.level} | `{entry.target_path}` | **{entry.status.value}** | "
                f"{entry.attempts} | {'PASS' if entry.tsc_passed else 'FAIL'} | "
                f"{'PASS' if entry.eslint_passed else 'FAIL'} | "
                f"{'PASS' if entry.characterization_passed else 'FAIL'} |"
            )
        conversion_section = "\n".join(conv_lines)

    rendered = template.format(
        run_id=metrics.run_id,
        source_root=metrics.source_root,
        source_stack=metrics.source_stack,
        target_stack=metrics.target_stack,
        verdict=verdict.verdict.value,
        llm_calls=metrics.llm_calls,
        cache_hits=metrics.cache_hits,
        verdict_rationale=verdict.rationale,
        axes_table=axes_table,
        blocking_section=blocking_section,
        caveats_section=caveats_section,
        alternatives_section=alternatives_section,
        conversion_section=conversion_section,
    ).strip() + "\n"

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")

    return rendered


def print_terminal_summary(
    verdict: Verdict,
    metrics: RunMetrics,
    console: Console | None = None,
) -> None:
    """Display Rich formatted tables for the Viability Gate and Module Conversion results."""
    con = console or Console()

    verdict_color = {
        VerdictType.RECOMMENDED: "green",
        VerdictType.VIABLE_WITH_CAVEATS: "yellow",
        VerdictType.NOT_RECOMMENDED: "red",
    }[verdict.verdict]

    con.print(
        Panel(
            f"[bold cyan]Stack Migration:[/bold cyan] {metrics.source_stack} -> {metrics.target_stack}\n"
            f"[bold {verdict_color}]Verdict: {verdict.verdict.value.upper()}[/bold {verdict_color}]\n"
            f"{verdict.rationale}",
            title=f"StackConverter Viability Gate — Run '{metrics.run_id}'",
            border_style=verdict_color,
        )
    )

    axis_table = Table(title="7-Axis Viability Assessment")
    axis_table.add_column("Axis", style="cyan")
    axis_table.add_column("Risk Level", style="bold")
    axis_table.add_column("Central High", justify="center")
    axis_table.add_column("Summary")

    for a in verdict.axes:
        r_color = {"low": "green", "medium": "yellow", "high": "red"}[a.risk_level.value]
        axis_table.add_row(
            a.axis.value,
            f"[{r_color}]{a.risk_level.value.upper()}[/{r_color}]",
            "YES" if a.has_central_high_risk else "no",
            a.summary,
        )
    con.print(axis_table)

    if verdict.blocking_evidences:
        ev_table = Table(title="Blocking Architectural Evidences (file:line)", border_style="red")
        ev_table.add_column("Location", style="bold red")
        ev_table.add_column("Axis", style="cyan")
        ev_table.add_column("Snippet", style="yellow")
        ev_table.add_column("Description")
        for ev in verdict.blocking_evidences:
            ev_table.add_row(f"{ev.file_path}:{ev.line}", ev.axis.value, ev.snippet, ev.description)
        con.print(ev_table)

    if metrics.module_entries:
        mod_table = Table(title="Topological Module Conversion Summary")
        mod_table.add_column("Module", style="cyan")
        mod_table.add_column("Level", justify="right")
        mod_table.add_column("Status", style="bold")
        mod_table.add_column("Attempts", justify="right")
        mod_table.add_column("tsc --strict", justify="center")
        mod_table.add_column("eslint", justify="center")
        mod_table.add_column("tsx Oracle", justify="center")
        for m in metrics.module_entries:
            st_color = "green" if m.status.value == "converted" else "red"
            mod_table.add_row(
                m.module_id,
                str(m.level),
                f"[{st_color}]{m.status.value.upper()}[/{st_color}]",
                str(m.attempts),
                "[green]PASS[/green]" if m.tsc_passed else "[red]FAIL[/red]",
                "[green]PASS[/green]" if m.eslint_passed else "[red]FAIL[/red]",
                "[green]PASS[/green]" if m.characterization_passed else "[red]FAIL[/red]",
            )
        con.print(mod_table)
