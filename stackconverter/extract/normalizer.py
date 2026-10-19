"""Normalizes raw structural graph output into a Pydantic CodeGraph enriched with Python AST metadata."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from stackconverter.schemas import CodeGraph, Edge, EdgeType, Node, NodeType, ParameterInfo


def _extract_parameters(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ParameterInfo]:
    params: list[ParameterInfo] = []
    num_args = len(fn_node.args.args)
    num_defaults = len(fn_node.args.defaults)
    default_offset = num_args - num_defaults

    for idx, arg in enumerate(fn_node.args.args):
        if arg.arg == "self":
            continue
        ann = ast.unparse(arg.annotation) if arg.annotation is not None else None
        default_str: str | None = None
        if idx >= default_offset:
            default_node = fn_node.args.defaults[idx - default_offset]
            default_str = ast.unparse(default_node)
        params.append(ParameterInfo(name=arg.arg, annotation=ann, default=default_str))
    return params


def _build_signature(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    params = _extract_parameters(fn_node)
    param_strs = []
    for p in params:
        s = p.name
        if p.annotation:
            s += f": {p.annotation}"
        if p.default is not None:
            s += f" = {p.default}"
        param_strs.append(s)
    ret = f" -> {ast.unparse(fn_node.returns)}" if fn_node.returns is not None else ""
    return f"def {fn_node.name}({', '.join(param_strs)}){ret}"


def normalize_graph(
    raw_graph: dict[str, Any],
    source_root: str | Path,
    output_path: str | Path | None = None,
) -> CodeGraph:
    """Normalize raw graph dictionary and enrich nodes via Python AST inspection."""
    root = Path(source_root).resolve()
    raw_nodes = raw_graph.get("nodes", [])
    raw_edges = raw_graph.get("edges", [])

    ast_cache: dict[str, tuple[str, list[str], ast.Module]] = {}

    def _get_ast(rel_path: str) -> tuple[str, list[str], ast.Module] | None:
        if rel_path in ast_cache:
            return ast_cache[rel_path]
        full_path = root / rel_path
        if not full_path.exists():
            return None
        source = full_path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source, filename=rel_path)
        ast_cache[rel_path] = (source, lines, tree)
        return ast_cache[rel_path]

    nodes_by_id: dict[str, Node] = {}
    for rn in raw_nodes:
        node_id = str(rn["id"])
        raw_type = str(rn.get("type") or rn.get("node_type") or "module").lower()
        node_type = NodeType(raw_type) if raw_type in NodeType._value2member_map_ else NodeType.MODULE
        rel_path = rn.get("file_path")
        line_start = rn.get("line_start")
        line_end = rn.get("line_end")
        name = rn.get("name") or node_id.split(":")[-1].split(".")[-1]

        docstring: str | None = rn.get("docstring")
        source_code: str | None = rn.get("source_code")
        signature: str | None = rn.get("signature")
        parameters: list[ParameterInfo] = []
        return_annotation: str | None = rn.get("return_annotation")
        imports: list[str] = list(rn.get("imports", []))
        is_public = not name.startswith("_")

        if rel_path:
            parsed = _get_ast(rel_path)
            if parsed is not None:
                full_source, lines, tree = parsed
                if node_type == NodeType.MODULE:
                    docstring = ast.get_docstring(tree)
                    source_code = full_source
                    mod_imports: list[str] = []
                    for stmt in tree.body:
                        if isinstance(stmt, ast.Import):
                            for alias in stmt.names:
                                mod_imports.append(alias.name.split(".")[0])
                        elif isinstance(stmt, ast.ImportFrom) and stmt.module and stmt.module != "__future__":
                            mod_imports.append(stmt.module.split(".")[0])
                    imports = sorted(set(mod_imports))
                elif node_type in (NodeType.FUNCTION, NodeType.CLASS):
                    for stmt in tree.body:
                        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and stmt.name == name:
                            docstring = ast.get_docstring(stmt)
                            line_start = stmt.lineno
                            line_end = getattr(stmt, "end_lineno", stmt.lineno)
                            source_code = "\n".join(lines[line_start - 1 : line_end])
                            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                parameters = _extract_parameters(stmt)
                                return_annotation = (
                                    ast.unparse(stmt.returns) if stmt.returns is not None else None
                                )
                                signature = _build_signature(stmt)
                            else:
                                signature = f"class {stmt.name}"
                            break

        nodes_by_id[node_id] = Node(
            id=node_id,
            name=name,
            node_type=node_type,
            file_path=rel_path,
            line_start=line_start,
            line_end=line_end,
            signature=signature,
            parameters=parameters,
            return_annotation=return_annotation,
            is_public=is_public,
            docstring=docstring,
            source_code=source_code,
            imports=imports,
        )

    edges: list[Edge] = []
    seen_edges: set[tuple[str, str, EdgeType]] = set()
    for re_item in raw_edges:
        src = str(re_item["source"])
        tgt = str(re_item["target"])
        raw_etype = str(re_item.get("type") or re_item.get("edge_type") or "imports").lower()
        etype = EdgeType(raw_etype) if raw_etype in EdgeType._value2member_map_ else EdgeType.IMPORTS
        line = re_item.get("line")

        if tgt not in nodes_by_id and etype == EdgeType.IMPORTS:
            ext_pkg = tgt.split(".")[0]
            if ext_pkg not in nodes_by_id:
                nodes_by_id[ext_pkg] = Node(
                    id=ext_pkg,
                    name=ext_pkg,
                    node_type=NodeType.EXTERNAL_PACKAGE,
                    is_public=True,
                )
            tgt = ext_pkg

        key = (src, tgt, etype)
        if key not in seen_edges and src != tgt:
            seen_edges.add(key)
            edges.append(Edge(source=src, target=tgt, edge_type=etype, line=line))

    code_graph = CodeGraph(
        source_root=str(root),
        nodes=sorted(nodes_by_id.values(), key=lambda n: n.id),
        edges=sorted(edges, key=lambda e: (e.source, e.target, e.edge_type.value)),
    )

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(code_graph.model_dump(mode="json"), indent=2), encoding="utf-8")

    return code_graph
