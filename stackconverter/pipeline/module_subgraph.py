"""Per-module conversion subgraph: Translator -> Validate (tsc + eslint + tsx oracle) -> Fixer (up to 3 retries)."""

from __future__ import annotations

import json
from pathlib import Path

from stackconverter.config import AppConfig
from stackconverter.generate.translator import translate_module
from stackconverter.llm.base import AgentCaller
from stackconverter.schemas import (
    CharacterizationSuite,
    CodeGraph,
    MigrationPlan,
    ModuleCode,
    ModuleConversionStatus,
    ModuleReportEntry,
    Node,
    NodeDoc,
    ValidationDiagnostic,
    ValidationResult,
)
from stackconverter.validate.characterization_runner import run_characterization_oracle
from stackconverter.validate.eslint import run_eslint_check
from stackconverter.validate.fixer import fix_module_code
from stackconverter.validate.tsc import run_tsc_check


def validate_module_attempt(
    module_id: str,
    target_path: str,
    attempt: int,
    output_ts_dir: Path,
    validation_dir: Path,
    suite: CharacterizationSuite | None,
    config: AppConfig,
) -> ValidationResult:
    """Run deterministic tsc, eslint, and tsx characterization oracle for a single module attempt."""
    validation_dir.mkdir(parents=True, exist_ok=True)
    diagnostics: list[ValidationDiagnostic] = []

    if config.validation.run_tsc:
        tsc_ok, tsc_diags, tsc_log = run_tsc_check(output_ts_dir, target_path=target_path)
        diagnostics.extend(tsc_diags)
    else:
        tsc_ok, tsc_log = True, "Skipped"

    if config.validation.run_eslint:
        eslint_ok, eslint_diags, eslint_log = run_eslint_check(output_ts_dir, target_path=target_path)
        diagnostics.extend(eslint_diags)
    else:
        eslint_ok, eslint_log = True, "Skipped"

    if config.validation.run_characterization:
        char_ok, char_total, char_matched, char_diags, char_log = run_characterization_oracle(
            output_ts_dir,
            target_path=target_path,
            suite=suite,
        )
        diagnostics.extend(char_diags)
    else:
        char_ok, char_total, char_matched, char_log = True, 0, 0, "Skipped"

    val_result = ValidationResult(
        module_id=module_id,
        attempt=attempt,
        tsc_passed=tsc_ok,
        eslint_passed=eslint_ok,
        characterization_passed=char_ok,
        characterization_total=char_total,
        characterization_matched=char_matched,
        diagnostics=diagnostics,
    )

    safe_mod = module_id.replace(".", "_")
    artifact_file = validation_dir / f"{safe_mod}_attempt_{attempt}.json"
    artifact_file.write_text(
        json.dumps(
            {
                "validation": val_result.model_dump(mode="json"),
                "logs": {
                    "tsc": tsc_log,
                    "eslint": eslint_log,
                    "characterization": char_log,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return val_result


async def convert_and_validate_module(
    graph: CodeGraph,
    module_node: Node,
    level: int,
    node_doc: NodeDoc | None,
    plan: MigrationPlan,
    suite: CharacterizationSuite | None,
    converted_modules: dict[str, ModuleCode],
    caller: AgentCaller,
    config: AppConfig,
    output_ts_dir: Path,
    validation_dir: Path,
) -> tuple[ModuleCode, ValidationResult, ModuleReportEntry]:
    """Execute the Translator -> Validator -> Fixer loop (up to max_fix_attempts) for one module."""
    max_attempts = max(1, config.validation.max_fix_attempts)
    rules_path = config.resolve_path(config.paths.rules_path)

    module_code = await translate_module(
        graph=graph,
        module_node=module_node,
        node_doc=node_doc,
        plan=plan,
        converted_modules=converted_modules,
        caller=caller,
        output_ts_dir=output_ts_dir,
        rules_path=rules_path,
    )

    val_result = validate_module_attempt(
        module_id=module_node.id,
        target_path=module_code.target_path,
        attempt=1,
        output_ts_dir=output_ts_dir,
        validation_dir=validation_dir,
        suite=suite,
        config=config,
    )

    attempt = 1
    while not val_result.passed and attempt < max_attempts:
        attempt += 1
        module_code = await fix_module_code(
            graph=graph,
            module_node=module_node,
            node_doc=node_doc,
            current_code=module_code,
            diagnostics=val_result.diagnostics,
            converted_modules=converted_modules,
            attempt=attempt,
            caller=caller,
            output_ts_dir=output_ts_dir,
        )
        val_result = validate_module_attempt(
            module_id=module_node.id,
            target_path=module_code.target_path,
            attempt=attempt,
            output_ts_dir=output_ts_dir,
            validation_dir=validation_dir,
            suite=suite,
            config=config,
        )

    status = ModuleConversionStatus.CONVERTED if val_result.passed else ModuleConversionStatus.PENDING
    report_entry = ModuleReportEntry(
        module_id=module_node.id,
        source_path=module_node.file_path or f"{module_node.id}.py",
        target_path=module_code.target_path,
        level=level,
        status=status,
        attempts=attempt,
        tsc_passed=val_result.tsc_passed,
        eslint_passed=val_result.eslint_passed,
        characterization_passed=val_result.characterization_passed,
        diagnostics=val_result.diagnostics,
    )
    return module_code, val_result, report_entry
