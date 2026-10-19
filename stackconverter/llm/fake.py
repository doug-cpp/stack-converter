"""Deterministic Fake LLM Provider with built-in AST-to-TypeScript transpiler for offline runs and tests."""

from __future__ import annotations

import ast
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class _PyToTSTranspiler(ast.NodeVisitor):
    """Deterministic Python AST to strict TypeScript transpiler used by FakeProvider."""

    def __init__(self, known_internal_modules: set[str] | None = None) -> None:
        self.known_internal_modules = known_internal_modules or set()
        self.exported_signatures: list[str] = []
        self._declared_vars: list[set[str]] = [set()]

    def transpile(self, source_code: str) -> tuple[str, list[str]]:
        tree = ast.parse(source_code)
        lines: list[str] = []
        for stmt in tree.body:
            rendered = self._render_TopStmt(stmt)
            if rendered:
                lines.append(rendered)
        code = "\n\n".join(lines).strip() + "\n"
        return code, self.exported_signatures

    def _map_type(self, node: ast.AST | None) -> str:
        if node is None:
            return "number"
        if isinstance(node, ast.Name):
            mapping = {
                "int": "number",
                "float": "number",
                "str": "string",
                "bool": "boolean",
                "None": "void",
                "Any": "unknown",
                "object": "unknown",
                "dict": "Record<string, unknown>",
                "list": "unknown[]",
                "tuple": "unknown[]",
            }
            return mapping.get(node.id, node.id)
        if isinstance(node, ast.Constant):
            if node.value is None:
                return "null"
            if isinstance(node.value, str):
                return node.value
            return str(node.value)
        if isinstance(node, ast.Subscript):
            base = self._map_type(node.value)
            if isinstance(node.value, ast.Name):
                base_name = node.value.id
                if base_name in ("list", "List", "Sequence", "Iterable"):
                    elem = self._map_type(node.slice)
                    return f"Array<{elem}>"
                if base_name in ("dict", "Dict", "Mapping"):
                    if isinstance(node.slice, ast.Tuple) and len(node.slice.elts) == 2:
                        k_type = self._map_type(node.slice.elts[0])
                        v_type = self._map_type(node.slice.elts[1])
                        return f"Record<{k_type}, {v_type}>"
                    return "Record<string, number>"
                if base_name == "Optional":
                    inner = self._map_type(node.slice)
                    return f"{inner} | null"
                if base_name in ("tuple", "Tuple"):
                    if isinstance(node.slice, ast.Tuple):
                        elts = ", ".join(self._map_type(e) for e in node.slice.elts)
                        return f"[{elts}]"
            return base
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            left = self._map_type(node.left)
            right = self._map_type(node.right)
            if left == right:
                return left
            return f"{left} | {right}"
        return "unknown"

    def _render_TopStmt(self, node: ast.stmt) -> str:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            doc = node.value.value.strip().replace("*/", "* /")
            return f"/**\n * {doc}\n */"
        if isinstance(node, ast.ImportFrom):
            if node.module in ("__future__", "typing", "dataclasses", "enum", "math"):
                return ""
            if node.module:
                short_mod = node.module.split(".")[-1]
                names = [alias.asname or alias.name for alias in node.names]
                return f'import {{ {", ".join(names)} }} from "./{short_mod}";'
            return ""
        if isinstance(node, ast.Import):
            return ""
        if isinstance(node, ast.ClassDef):
            return self._render_ClassDef(node)
        if isinstance(node, ast.FunctionDef):
            return self._render_FunctionDef(node, is_export=not node.name.startswith("_"))
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            ts_type = self._map_type(node.annotation)
            val = self._render_expr(node.value) if node.value else "undefined"
            self._declared_vars[-1].add(name)
            sig = f"export const {name}: {ts_type}"
            self.exported_signatures.append(sig)
            return f"export const {name}: {ts_type} = {val};"
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            val = self._render_expr(node.value)
            self._declared_vars[-1].add(name)
            self.exported_signatures.append(f"export const {name}")
            return f"export const {name} = {val};"
        return ""

    def _render_ClassDef(self, node: ast.ClassDef) -> str:
        fields: list[str] = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                f_name = item.target.id
                f_type = self._map_type(item.annotation)
                fields.append(f"  {f_name}: {f_type};")
        sig = f"export interface {node.name}"
        self.exported_signatures.append(sig)
        body_str = "\n".join(fields) if fields else "  [key: string]: unknown;"
        return f"export interface {node.name} {{\n{body_str}\n}}"

    def _render_FunctionDef(self, node: ast.FunctionDef, is_export: bool = True) -> str:
        params: list[str] = []
        num_args = len(node.args.args)
        num_defaults = len(node.args.defaults)
        default_offset = num_args - num_defaults

        local_vars: set[str] = set()
        for idx, arg in enumerate(node.args.args):
            if arg.arg == "self":
                continue
            local_vars.add(arg.arg)
            p_type = self._map_type(arg.annotation)
            if idx >= default_offset:
                def_node = node.args.defaults[idx - default_offset]
                def_expr = self._render_expr(def_node)
                params.append(f"{arg.arg}: {p_type} = {def_expr}")
            else:
                params.append(f"{arg.arg}: {p_type}")

        ret_type = self._map_type(node.returns) if node.returns else "number"
        prefix = "export " if is_export else ""
        sig = f"{prefix}function {node.name}({', '.join(params)}): {ret_type}"
        if is_export:
            self.exported_signatures.append(sig)

        self._declared_vars.append(local_vars)
        body_lines: list[str] = []
        for stmt in node.body:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                continue
            rendered = self._render_stmt(stmt, indent=1)
            if rendered:
                body_lines.append(rendered)
        self._declared_vars.pop()

        if not body_lines:
            body_lines.append("  return undefined as never;")
        return f"{sig} {{\n" + "\n".join(body_lines) + "\n}"

    def _is_declared(self, name: str) -> bool:
        return any(name in scope for scope in self._declared_vars)

    def _declare(self, name: str) -> None:
        self._declared_vars[-1].add(name)

    def _render_stmt(self, node: ast.stmt, indent: int = 1) -> str:
        pad = "  " * indent
        if isinstance(node, ast.Return):
            if node.value is None:
                return f"{pad}return;"
            return f"{pad}return {self._render_expr(node.value)};"
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    name = target.id
                    val = self._render_expr(node.value)
                    if self._is_declared(name):
                        return f"{pad}{name} = {val};"
                    self._declare(name)
                    return f"{pad}let {name} = {val};"
                if isinstance(target, ast.Tuple):
                    names = [self._render_expr(e) for e in target.elts]
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            self._declare(elt.id)
                    return f"{pad}const [{', '.join(names)}] = {self._render_expr(node.value)};"
                return f"{pad}{self._render_expr(target)} = {self._render_expr(node.value)};"
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            ts_type = self._map_type(node.annotation)
            val = self._render_expr(node.value) if node.value else "undefined"
            if self._is_declared(name):
                return f"{pad}{name} = {val};"
            self._declare(name)
            return f"{pad}let {name}: {ts_type} = {val};"
        if isinstance(node, ast.AugAssign):
            target_s = self._render_expr(node.target)
            val_s = self._render_expr(node.value)
            op_map = {
                ast.Add: "+=",
                ast.Sub: "-=",
                ast.Mult: "*=",
                ast.Div: "/=",
            }
            op_s = op_map.get(type(node.op), "+=")
            return f"{pad}{target_s} {op_s} {val_s};"
        if isinstance(node, ast.If):
            cond = self._render_cond(node.test)
            then_lines = [self._render_stmt(s, indent + 1) for s in node.body]
            then_block = "\n".join(line for line in then_lines if line)
            res = f"{pad}if ({cond}) {{\n{then_block}\n{pad}}}"
            if node.orelse:
                else_lines = [self._render_stmt(s, indent + 1) for s in node.orelse]
                else_block = "\n".join(line for line in else_lines if line)
                res += f" else {{\n{else_block}\n{pad}}}"
            return res
        if isinstance(node, ast.For):
            if isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name) and node.iter.func.id == "range":
                target_name = self._render_expr(node.target)
                self._declare(target_name)
                args = node.iter.args
                if len(args) == 1:
                    start_s, stop_s = "0", self._render_expr(args[0])
                else:
                    start_s, stop_s = self._render_expr(args[0]), self._render_expr(args[1])
                body_lines = [self._render_stmt(s, indent + 1) for s in node.body]
                body_block = "\n".join(line for line in body_lines if line)
                return f"{pad}for (let {target_name} = {start_s}; {target_name} < {stop_s}; {target_name}++) {{\n{body_block}\n{pad}}}"
            if (
                isinstance(node.iter, ast.Call)
                and isinstance(node.iter.func, ast.Attribute)
                and node.iter.func.attr == "items"
                and isinstance(node.target, ast.Tuple)
                and len(node.target.elts) == 2
            ):
                k_name = self._render_expr(node.target.elts[0])
                v_name = self._render_expr(node.target.elts[1])
                self._declare(k_name)
                self._declare(v_name)
                obj_s = self._render_expr(node.iter.func.value)
                body_lines = [self._render_stmt(s, indent + 1) for s in node.body]
                body_block = "\n".join(line for line in body_lines if line)
                return f"{pad}for (const [{k_name}, {v_name}] of Object.entries({obj_s})) {{\n{body_block}\n{pad}}}"
            target_s = self._render_expr(node.target)
            if isinstance(node.target, ast.Name):
                self._declare(node.target.id)
            iter_s = self._render_expr(node.iter)
            body_lines = [self._render_stmt(s, indent + 1) for s in node.body]
            body_block = "\n".join(line for line in body_lines if line)
            return f"{pad}for (const {target_s} of {iter_s}) {{\n{body_block}\n{pad}}}"
        if isinstance(node, ast.While):
            cond = self._render_cond(node.test)
            body_lines = [self._render_stmt(s, indent + 1) for s in node.body]
            body_block = "\n".join(line for line in body_lines if line)
            return f"{pad}while ({cond}) {{\n{body_block}\n{pad}}}"
        if isinstance(node, ast.Raise):
            if isinstance(node.exc, ast.Call) and node.exc.args:
                msg = self._render_expr(node.exc.args[0])
                return f"{pad}throw new Error({msg});"
            return f'{pad}throw new Error("Runtime error");'
        if isinstance(node, ast.Expr):
            return f"{pad}{self._render_expr(node.value)};"
        if isinstance(node, ast.Continue):
            return f"{pad}continue;"
        if isinstance(node, ast.Break):
            return f"{pad}break;"
        return ""

    def _render_cond(self, node: ast.expr) -> str:
        return self._render_expr(node)

    def _render_expr(self, node: ast.expr) -> str:
        if isinstance(node, ast.Constant):
            if node.value is True:
                return "true"
            if node.value is False:
                return "false"
            if node.value is None:
                return "null"
            if isinstance(node.value, str):
                escaped = node.value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                return f'"{escaped}"'
            return repr(node.value)
        if isinstance(node, ast.Name):
            if node.id == "True":
                return "true"
            if node.id == "False":
                return "false"
            if node.id == "None":
                return "null"
            return node.id
        if isinstance(node, ast.UnaryOp):
            operand = self._render_expr(node.operand)
            if isinstance(node.op, ast.Not):
                return f"(!{operand})"
            if isinstance(node.op, ast.USub):
                return f"(-{operand})"
            if isinstance(node.op, ast.UAdd):
                return f"(+{operand})"
        if isinstance(node, ast.BinOp):
            left = self._render_expr(node.left)
            right = self._render_expr(node.right)
            if isinstance(node.op, ast.FloorDiv):
                return f"Math.floor({left} / {right})"
            if isinstance(node.op, ast.Pow):
                return f"Math.pow({left}, {right})"
            op_map = {
                ast.Add: "+",
                ast.Sub: "-",
                ast.Mult: "*",
                ast.Div: "/",
                ast.Mod: "%",
            }
            op_s = op_map.get(type(node.op), "+")
            return f"({left} {op_s} {right})"
        if isinstance(node, ast.BoolOp):
            op_s = " && " if isinstance(node.op, ast.And) else " || "
            parts = [self._render_expr(v) for v in node.values]
            return "(" + op_s.join(parts) + ")"
        if isinstance(node, ast.Compare):
            left = self._render_expr(node.left)
            clauses: list[str] = []
            curr_left = left
            for op, comp in zip(node.ops, node.comparators, strict=False):
                right = self._render_expr(comp)
                if isinstance(op, (ast.Eq, ast.Is)):
                    clauses.append(f"({curr_left} === {right})")
                elif isinstance(op, (ast.NotEq, ast.IsNot)):
                    clauses.append(f"({curr_left} !== {right})")
                elif isinstance(op, ast.Lt):
                    clauses.append(f"({curr_left} < {right})")
                elif isinstance(op, ast.LtE):
                    clauses.append(f"({curr_left} <= {right})")
                elif isinstance(op, ast.Gt):
                    clauses.append(f"({curr_left} > {right})")
                elif isinstance(op, ast.GtE):
                    clauses.append(f"({curr_left} >= {right})")
                elif isinstance(op, ast.In):
                    if isinstance(comp, (ast.List, ast.Tuple, ast.Set)):
                        clauses.append(f"{right}.includes({curr_left})")
                    else:
                        clauses.append(
                            f"(Array.isArray({right}) ? {right}.includes({curr_left}) : Object.prototype.hasOwnProperty.call({right}, {curr_left}))"
                        )
                elif isinstance(op, ast.NotIn):
                    if isinstance(comp, (ast.List, ast.Tuple, ast.Set)):
                        clauses.append(f"(!{right}.includes({curr_left}))")
                    else:
                        clauses.append(
                            f"(!(Array.isArray({right}) ? {right}.includes({curr_left}) : Object.prototype.hasOwnProperty.call({right}, {curr_left})))"
                        )
                curr_left = right
            return " && ".join(clauses)
        if isinstance(node, ast.IfExp):
            cond = self._render_expr(node.test)
            body = self._render_expr(node.body)
            orelse = self._render_expr(node.orelse)
            return f"({cond} ? {body} : {orelse})"
        if isinstance(node, ast.List):
            elts = [self._render_expr(e) for e in node.elts]
            return f"[{', '.join(elts)}]"
        if isinstance(node, ast.Tuple):
            elts = [self._render_expr(e) for e in node.elts]
            return f"[{', '.join(elts)}]"
        if isinstance(node, ast.Dict):
            pairs: list[str] = []
            for k, v in zip(node.keys, node.values, strict=False):
                if k is None:
                    pairs.append(f"...{self._render_expr(v)}")
                else:
                    k_s = self._render_expr(k)
                    v_s = self._render_expr(v)
                    pairs.append(f"[{k_s}]: {v_s}" if not isinstance(k, ast.Constant) else f"{k_s}: {v_s}")
            return f"{{ {', '.join(pairs)} }}"
        if isinstance(node, ast.Subscript):
            val = self._render_expr(node.value)
            sl = self._render_expr(node.slice)
            return f"{val}[{sl}]"
        if isinstance(node, ast.Attribute):
            val = self._render_expr(node.value)
            if val == "math":
                math_map = {
                    "pi": "Math.PI",
                    "e": "Math.E",
                    "sqrt": "Math.sqrt",
                    "ceil": "Math.ceil",
                    "floor": "Math.floor",
                    "fabs": "Math.abs",
                }
                return math_map.get(node.attr, f"Math.{node.attr}")
            return f"{val}.{node.attr}"
        if isinstance(node, ast.Call):
            return self._render_Call(node)
        if isinstance(node, ast.ListComp) and len(node.generators) == 1:
            gen = node.generators[0]
            target_s = self._render_expr(gen.target)
            iter_s = self._render_expr(gen.iter)
            elt_s = self._render_expr(node.elt)
            expr = iter_s
            for if_clause in gen.ifs:
                cond_s = self._render_expr(if_clause)
                expr = f"{expr}.filter(({target_s}) => {cond_s})"
            return f"{expr}.map(({target_s}) => {elt_s})"
        if isinstance(node, ast.GeneratorExp) and len(node.generators) == 1:
            gen = node.generators[0]
            target_s = self._render_expr(gen.target)
            iter_s = self._render_expr(gen.iter)
            elt_s = self._render_expr(node.elt)
            expr = iter_s
            for if_clause in gen.ifs:
                cond_s = self._render_expr(if_clause)
                expr = f"{expr}.filter(({target_s}) => {cond_s})"
            return f"{expr}.map(({target_s}) => {elt_s})"
        if isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value.replace("`", "\\`"))
                elif isinstance(v, ast.FormattedValue):
                    parts.append(f"${{{self._render_expr(v.value)}}}")
            return "`" + "".join(parts) + "`"
        return "undefined"

    def _render_Call(self, node: ast.Call) -> str:
        args = [self._render_expr(a) for a in node.args]
        if isinstance(node.func, ast.Name):
            fn = node.func.id
            if fn == "len" and len(args) == 1:
                return f"{args[0]}.length"
            if fn == "round":
                if len(args) == 1:
                    return f"Math.round({args[0]})"
                if len(args) == 2:
                    return f"(Math.round(({args[0]} + Number.EPSILON) * Math.pow(10, {args[1]})) / Math.pow(10, {args[1]}))"
            if fn == "sum" and len(args) >= 1:
                init = args[1] if len(args) > 1 else "0"
                return f"{args[0]}.reduce((acc: number, val: number) => acc + val, {init})"
            if fn == "min" and len(args) >= 1:
                if len(args) == 1:
                    return f"Math.min(...{args[0]})"
                return f"Math.min({', '.join(args)})"
            if fn == "max" and len(args) >= 1:
                if len(args) == 1:
                    return f"Math.max(...{args[0]})"
                return f"Math.max({', '.join(args)})"
            if fn == "abs" and len(args) == 1:
                return f"Math.abs({args[0]})"
            if fn == "int" and len(args) == 1:
                return f"Math.trunc(Number({args[0]}))"
            if fn == "float" and len(args) == 1:
                return f"Number({args[0]})"
            if fn == "str" and len(args) == 1:
                return f"String({args[0]})"
            if fn == "bool" and len(args) == 1:
                return f"Boolean({args[0]})"
            if fn == "sorted" and len(args) >= 1:
                return f"[...{args[0]}].sort((a, b) => (a > b ? 1 : a < b ? -1 : 0))"
            if fn == "list" and len(args) == 1:
                return f"[...{args[0]}]"
            return f"{fn}({', '.join(args)})"

        if isinstance(node.func, ast.Attribute):
            obj = self._render_expr(node.func.value)
            attr = node.func.attr
            if attr == "append" and len(args) == 1:
                return f"{obj}.push({args[0]})"
            if attr == "get" and len(args) >= 1:
                default_val = args[1] if len(args) > 1 else "undefined"
                return f"({obj}[{args[0]}] ?? {default_val})"
            if attr == "strip" and len(args) == 0:
                return f"{obj}.trim()"
            if attr == "lower" and len(args) == 0:
                return f"{obj}.toLowerCase()"
            if attr == "upper" and len(args) == 0:
                return f"{obj}.toUpperCase()"
            if attr == "startswith" and len(args) == 1:
                return f"{obj}.startsWith({args[0]})"
            if attr == "endswith" and len(args) == 1:
                return f"{obj}.endsWith({args[0]})"
            if attr == "keys" and len(args) == 0:
                return f"Object.keys({obj})"
            if attr == "values" and len(args) == 0:
                return f"Object.values({obj})"
            if attr == "items" and len(args) == 0:
                return f"Object.entries({obj})"
            return f"{obj}.{attr}({', '.join(args)})"

        func_s = self._render_expr(node.func)
        return f"{func_s}({', '.join(args)})"


class FakeProvider:
    """Deterministic offline LLM provider for testing and zero-cost runs."""

    name = "fake"

    def __init__(self, model_name: str = "fake-deterministic-v1") -> None:
        self.model_name = model_name

    async def generate_structured(
        self,
        role: str,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type[T],
        validation_error_feedback: str | None = None,
    ) -> dict[str, Any]:
        """Produce deterministic schema-valid responses based on the agent role."""
        if role == "documenter":
            return self._handle_documenter(payload)
        if role == "judge":
            return self._handle_judge(payload)
        if role == "characterizer":
            return self._handle_characterizer(payload)
        if role == "translator":
            return self._handle_translator(payload)
        if role == "fixer":
            return self._handle_fixer(payload)
        raise ValueError(f"Unsupported role in FakeProvider: {role}")

    def _handle_documenter(self, payload: dict[str, Any]) -> dict[str, Any]:
        node = payload.get("node", {})
        node_id = node.get("id", "unknown")
        docstring = node.get("docstring") or f"Deterministic semantic documentation for {node_id}."
        imports = list(node.get("imports", []))
        params = [p.get("name", "arg") for p in node.get("parameters", [])]
        return {
            "node_id": node_id,
            "purpose": docstring.splitlines()[0] if docstring else f"Module or symbol {node_id}",
            "inputs": params or ["Module-level inputs"],
            "outputs": [node.get("return_annotation") or "Deterministic return value"],
            "side_effects": ["None (pure computation)"],
            "invariants": ["Deterministic outputs for identical inputs", "Strict numeric and string bounds"],
            "edge_cases": ["Empty inputs", "Zero or negative numeric values"],
            "external_dependencies": imports,
            "error_model": "Raises standard Error on invalid domain parameters",
            "concurrency_model": "Synchronous single-threaded execution",
        }

    def _handle_judge(self, payload: dict[str, Any]) -> dict[str, Any]:
        evidences = payload.get("evidences", [])
        judgments: list[dict[str, Any]] = []
        has_central_high = False

        for ev in evidences:
            ev_id = ev.get("id", "ev_0")
            axis = ev.get("axis", "ecosystem")
            risk = ev.get("risk_level", "medium")
            file_path = ev.get("file_path", "")
            desc = ev.get("description", "")

            is_peripheral_file = any(
                marker in file_path.lower() for marker in ("cli", "script", "debug", "helper", "test")
            )
            if risk == "high" and not is_peripheral_file:
                scope = "central"
                has_central_high = True
            else:
                scope = "peripheral" if is_peripheral_file or risk != "high" else "central"

            judgments.append(
                {
                    "evidence_id": ev_id,
                    "mitigation_argument": (
                        f"Could attempt to offload {axis} pattern in '{file_path}' to worker_threads or external service."
                    ),
                    "incompatibility_argument": (
                        f"Pattern '{desc}' in '{file_path}' relies on Python runtime/ecosystem semantics lacking a 1:1 native TypeScript/Node.js equivalent."
                    ),
                    "classification": scope,
                    "adjusted_risk_level": risk,
                    "rationale": (
                        f"Classified as {scope} with {risk} risk based on module centrality and AST pattern ({axis})."
                    ),
                }
            )

        alternatives = (
            [
                "Go (native goroutines and multi-core CPU parallelism)",
                "Rust (zero-cost abstractions, Rayon data parallelism, and SIMD ndarray ecosystem)",
                "Hybrid architecture: keep CPU/scientific core in Python microservice and expose gRPC/HTTP to Node.js",
            ]
            if has_central_high
            else []
        )

        return {
            "judgments": judgments,
            "overall_architectural_notes": (
                "Central high-risk architectural patterns detected; direct migration to Node.js/TypeScript is unsafe."
                if has_central_high
                else "Codebase is structurally compatible with strict TypeScript on Node.js."
            ),
            "suggested_alternatives": alternatives,
        }

    def _handle_characterizer(self, payload: dict[str, Any]) -> dict[str, Any]:
        module_id = payload.get("module_id", "module")
        functions = payload.get("functions", [])
        cases: list[dict[str, Any]] = []

        for fn in functions:
            fn_name = fn.get("name", "")
            params = fn.get("parameters", [])
            sample_args = self._synthesize_args(fn_name, params, variant=0)
            alt_args = self._synthesize_args(fn_name, params, variant=1)
            cases.append({"function_name": fn_name, "args": sample_args, "kwargs": {}})
            if alt_args != sample_args:
                cases.append({"function_name": fn_name, "args": alt_args, "kwargs": {}})

        return {
            "module_id": module_id,
            "cases": cases,
        }

    def _synthesize_args(self, fn_name: str, params: list[dict[str, Any]], variant: int = 0) -> list[Any]:
        args: list[Any] = []
        for p in params:
            p_name = p.get("name", "").lower()
            p_ann = (p.get("annotation") or "").lower()
            default_val = p.get("default")
            if default_val is not None and variant == 0:
                try:
                    args.append(ast.literal_eval(default_val))
                    continue
                except Exception:
                    pass

            if "items" in p_name or "orders" in p_name or "records" in p_name:
                if "invoice" in fn_name or "line" in fn_name or "summary" in fn_name or "validate" in fn_name:
                    args.append(
                        [
                            {"sku": "ITEM-1", "unit_price": 50.0, "quantity": 2},
                            {"sku": "ITEM-2", "unit_price": 25.0, "quantity": 1 + variant},
                        ]
                    )
                else:
                    args.append(
                        [
                            {"customer_id": "C1", "subtotal": 120.0, "total": 130.0},
                            {"customer_id": "C2", "subtotal": 80.0 + variant * 20.0, "total": 90.0},
                        ]
                    )
            elif "prices" in p_name or "values" in p_name or "numbers" in p_name or "amounts" in p_name or "revenues" in p_name:
                args.append([100.0, 250.5, 49.5] if variant == 0 else [50.0, 150.0])
            elif "region" in p_name or "country" in p_name or "state" in p_name:
                args.append("US_CA" if variant == 0 else "EU_DE")
            elif "coupon" in p_name or "code" in p_name:
                args.append("SAVE10" if variant == 0 else "WELCOME20")
            elif "tier" in p_name or "level" in p_name:
                args.append("gold" if variant == 0 else "silver")
            elif "rate" in p_name or "pct" in p_name or "percent" in p_name or "discount" in p_name:
                args.append(0.10 if variant == 0 else 0.15)
            elif "qty" in p_name or "quantity" in p_name or "count" in p_name or "decimals" in p_name:
                args.append(2 if variant == 0 else 3)
            elif "list" in p_ann:
                args.append([10.0, 20.0, 30.0] if variant == 0 else [5.0, 15.0])
            elif "dict" in p_ann:
                args.append({"a": 10.0, "b": 20.0})
            elif "str" in p_ann:
                args.append("standard" if variant == 0 else "premium")
            elif "bool" in p_ann:
                args.append(variant == 0)
            elif "int" in p_ann:
                args.append(10 if variant == 0 else 25)
            else:
                args.append(100.0 if variant == 0 else 250.0)
        return args

    def _handle_translator(self, payload: dict[str, Any]) -> dict[str, Any]:
        module_id = payload.get("module_id", "module")
        source_code = payload.get("source_code", "")
        target_path = payload.get("target_path", f"src/{module_id.split('.')[-1]}.ts")
        transpiler = _PyToTSTranspiler()
        ts_code, signatures = transpiler.transpile(source_code)
        return {
            "module_id": module_id,
            "target_path": target_path,
            "typescript_code": ts_code,
            "exported_signatures": signatures,
            "notes": f"Deterministically translated {module_id} from Python AST to strict TypeScript.",
        }

    def _handle_fixer(self, payload: dict[str, Any]) -> dict[str, Any]:
        module_id = payload.get("module_id", "module")
        source_code = payload.get("source_code", "")
        target_path = payload.get("target_path", f"src/{module_id.split('.')[-1]}.ts")
        current_ts = payload.get("current_typescript_code", "")
        if source_code:
            transpiler = _PyToTSTranspiler()
            ts_code, signatures = transpiler.transpile(source_code)
        else:
            ts_code = current_ts
            signatures = []
        return {
            "module_id": module_id,
            "target_path": target_path,
            "typescript_code": ts_code,
            "exported_signatures": signatures,
            "notes": f"Repaired module {module_id} using deterministic AST transpiler.",
        }
