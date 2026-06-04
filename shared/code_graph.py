"""Code graph mapping with PageRank ranking for TypeScript/JavaScript projects."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
from loguru import logger


@dataclass
class CodeNode:
    """A single code entity (class, function, interface, etc.)."""

    file_path: str
    name: str
    node_type: str  # class | function | interface | import | export
    line_number: int
    references: list[str] = field(default_factory=list)


@dataclass
class FileSummary:
    """Parsed summary of a single source file."""

    path: str
    exports: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    size_bytes: int = 0
    line_count: int = 0


# Regex patterns for TypeScript / JavaScript parsing
_RE_IMPORT_FROM = re.compile(r"""import\s+(?:.*?)\s+from\s+['"]([^'"]+)['"]""", re.MULTILINE)
_RE_IMPORT_SIDE = re.compile(r"""import\s+['"]([^'"]+)['"]""", re.MULTILINE)
_RE_EXPORT = re.compile(
    r"""export\s+(?:default\s+)?(?:class|function|interface|const|let|var|enum|type)\s+(\w+)""",
    re.MULTILINE,
)
_RE_CLASS = re.compile(
    r"""(?:export\s+(?:default\s+)?)?class\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+implements\s+([\w,\s]+))?""",
    re.MULTILINE,
)
_RE_FUNCTION = re.compile(r"""(?:export\s+(?:default\s+)?)?function\s+(\w+)""", re.MULTILINE)
_RE_ARROW = re.compile(
    r"""(?:export\s+(?:default\s+)?)?(?:const|let)\s+(\w+)\s*=\s*(?:\([^)]*\)|[a-zA-Z_]\w*)\s*=>""",
    re.MULTILINE,
)
_RE_INTERFACE = re.compile(r"""(?:export\s+)?interface\s+(\w+)""", re.MULTILINE)


class CodeGraph:
    """Builds and queries a code dependency graph with PageRank ranking."""

    def __init__(self) -> None:
        self.graph: nx.DiGraph = nx.DiGraph()
        self.summaries: dict[str, FileSummary] = {}
        self.nodes: dict[str, list[CodeNode]] = {}
        self._cache: dict[str, tuple[float, FileSummary, list[CodeNode]]] = {}
        self._pagerank: dict[str, float] = {}

    # Public API
    def build_graph(self, project_path: str) -> None:
        """Parse all .ts/.js files and build the dependency graph."""
        root = Path(project_path).resolve()
        if not root.is_dir():
            logger.error("Project path does not exist: {}", root)
            return

        logger.info("Building code graph for {}", root)

        self.graph.clear()
        self.summaries.clear()
        self.nodes.clear()
        self._cache.clear()

        source_files: list[Path] = []
        for ext in ("*.ts", "*.tsx", "*.js", "*.jsx"):
            source_files.extend(root.rglob(ext))

        source_files = [
            f for f in source_files if "node_modules" not in f.parts and "dist" not in f.parts
        ]

        logger.info("Found {} source files", len(source_files))

        for fp in source_files:
            self._parse_file(fp, root)

        for rel_path, summary in self.summaries.items():
            for imp in summary.imports:
                resolved = self._resolve_import(imp, rel_path, root)
                if resolved and resolved in self.summaries:
                    self.graph.add_edge(rel_path, resolved)

        if self.graph.number_of_nodes() > 0:
            try:
                self._pagerank = nx.pagerank(self.graph, max_iter=200, tol=1e-04)
            except nx.PowerIterationFailedConvergence:
                logger.warning("PageRank did not converge; using uniform ranking")
                n = self.graph.number_of_nodes()
                self._pagerank = {node: 1.0 / n for node in self.graph.nodes()}
        logger.info(
            "Graph built: {} nodes, {} edges",
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
        )

    def get_relevant_context(self, target_file: str, token_budget: int = 4000) -> str:
        """Return ranked code context for *target_file* within *token_budget*."""
        if not self._pagerank:
            return self.get_project_map()

        scores: dict[str, float] = {}
        target_norm = self._normalise(target_file)

        for node, pr in self._pagerank.items():
            proximity = self._proxivity(target_norm, node)
            scores[node] = pr * 0.4 + proximity * 0.6

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        lines: list[str] = []
        budget = token_budget
        for rel_path, _score in ranked:
            summary = self.summaries.get(rel_path)
            if not summary:
                continue
            entry = self._summarise_file_inline(rel_path, summary)
            est_tokens = len(entry) // 4  # 1 token ≈ 4 chars
            if est_tokens > budget:
                break
            lines.append(entry)
            budget -= est_tokens

        return "\n".join(lines)

    def get_file_summary(self, file_path: str) -> FileSummary | None:
        """Return parsed summary for a single file."""
        return self.summaries.get(self._normalise(file_path))

    def get_project_map(self) -> str:
        """Compact, token-efficient string representation of the project."""
        if not self.summaries:
            return "(empty project)"

        sorted_paths = sorted(self.summaries.keys())
        lines: list[str] = []
        current_dir = ""
        for rel_path in sorted_paths:
            summary = self.summaries[rel_path]
            parent = str(Path(rel_path).parent)
            if parent != current_dir:
                current_dir = parent
                if parent == ".":
                    lines.append("")
                else:
                    lines.append(f"\n{parent}/")

            name = Path(rel_path).name
            parts: list[str] = []
            for cls in summary.classes:
                parts.append(f"class {cls}")
            for fn in summary.functions:
                parts.append(f"function {fn}()")
            for iface in getattr(summary, "_interfaces", []):
                parts.append(f"interface {iface}")
            for exp in summary.exports:
                if exp not in summary.classes and exp not in summary.functions:
                    parts.append(f"const {exp}")

            detail = ", ".join(parts) if parts else "(no exports)"
            indent = "  " if parent == "." else "  "
            lines.append(f"{indent}{name}: {detail}")

        return "\n".join(lines).strip()

    def get_dependents(self, file_path: str) -> list[str]:
        """Files that depend on *file_path* (import it)."""
        norm = self._normalise(file_path)
        if norm not in self.graph:
            return []
        return list(self.graph.predecessors(norm))

    def get_dependencies(self, file_path: str) -> list[str]:
        """Files that *file_path* depends on (imports them)."""
        norm = self._normalise(file_path)
        if norm not in self.graph:
            return []
        return list(self.graph.successors(norm))

    # Parsing internals
    def _parse_file(self, file_path: Path, root: Path) -> None:
        rel = str(file_path.relative_to(root))
        mtime = file_path.stat().st_mtime

        # Cache: re-use parsed result if mtime unchanged
        if rel in self._cache:
            cached_mtime, cached_summary, cached_nodes = self._cache[rel]
            if abs(mtime - cached_mtime) < 1.0:
                self.summaries[rel] = cached_summary
                self.nodes[rel] = cached_nodes
                self.graph.add_node(rel)
                return

        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Cannot read {}: {}", rel, exc)
            return

        summary, code_nodes = self._extract(rel, text, file_path)
        summary.size_bytes = file_path.stat().st_size
        summary.line_count = text.count("\n") + 1

        self._cache[rel] = (mtime, summary, code_nodes)
        self.summaries[rel] = summary
        self.nodes[rel] = code_nodes
        self.graph.add_node(rel)

    def _extract(
        self, rel_path: str, text: str, file_path: Path
    ) -> tuple[FileSummary, list[CodeNode]]:
        summary = FileSummary(path=rel_path)
        code_nodes: list[CodeNode] = []

        for m in _RE_IMPORT_FROM.finditer(text):
            imp_path = m.group(1)
            summary.imports.append(imp_path)
            code_nodes.append(
                CodeNode(rel_path, imp_path, "import", self._line_of(text, m.start()), [])
            )
        for m in _RE_IMPORT_SIDE.finditer(text):
            imp_path = m.group(1)
            if imp_path not in summary.imports:
                summary.imports.append(imp_path)

        for m in _RE_EXPORT.finditer(text):
            summary.exports.append(m.group(1))

        for m in _RE_CLASS.finditer(text):
            name = m.group(1)
            summary.classes.append(name)
            refs: list[str] = []
            if m.group(2):
                refs.append(m.group(2))
            code_nodes.append(
                CodeNode(rel_path, name, "class", self._line_of(text, m.start()), refs)
            )

        for m in _RE_FUNCTION.finditer(text):
            name = m.group(1)
            summary.functions.append(name)
            code_nodes.append(
                CodeNode(rel_path, name, "function", self._line_of(text, m.start()), [])
            )

        for m in _RE_ARROW.finditer(text):
            name = m.group(1)
            summary.functions.append(name)
            code_nodes.append(
                CodeNode(rel_path, name, "function", self._line_of(text, m.start()), [])
            )

        # Interfaces stored as export names but tracked separately
        ifaces: list[str] = []
        for m in _RE_INTERFACE.finditer(text):
            name = m.group(1)
            ifaces.append(name)
            if name not in summary.exports:
                summary.exports.append(name)
            code_nodes.append(
                CodeNode(rel_path, name, "interface", self._line_of(text, m.start()), [])
            )

        return summary, code_nodes

    # Helpers
    @staticmethod
    def _line_of(text: str, pos: int) -> int:
        return text[:pos].count("\n") + 1

    def _normalise(self, file_path: str) -> str:
        """Best-effort normalisation to match stored relative paths."""
        p = Path(file_path)
        if p.is_absolute():
            for sp in self.summaries:
                if file_path.endswith(sp) or sp.endswith(file_path.replace("\\", "/")):
                    return sp
        return str(p).replace("\\", "/")

    @staticmethod
    def _resolve_import(import_path: str, from_file: str, root: Path) -> str | None:
        """Resolve a JS/TS import to a relative project path."""
        # Relative imports
        if import_path.startswith("."):
            base = (root / from_file).parent
            for ext in ("", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js"):
                candidate = base / f"{import_path}{ext}"
                try:
                    resolved = candidate.resolve().relative_to(root)
                    return str(resolved)
                except (ValueError, OSError):
                    continue
        # Bare specifiers — look in node_modules is out of scope
        return None

    def _proxivity(self, target: str, other: str) -> float:
        """Heuristic proximity score between two files in the graph."""
        if other == target:
            return 1.0
        if self.graph.has_edge(target, other) or self.graph.has_edge(other, target):
            return 0.8
        # Shared directory
        if Path(target).parent == Path(other).parent:
            return 0.5
        try:
            sp = nx.shortest_path_length(self.graph, target, other)
            return max(0.0, 1.0 - sp * 0.2)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return 0.1

    @staticmethod
    def _summarise_file_inline(rel_path: str, summary: FileSummary) -> str:
        parts: list[str] = [f"// {rel_path}"]
        for cls in summary.classes:
            parts.append(f"  class {cls}")
        for fn in summary.functions:
            parts.append(f"  function {fn}()")
        for exp in summary.exports:
            if exp not in summary.classes and exp not in summary.functions:
                parts.append(f"  export {exp}")
        return "\n".join(parts)
