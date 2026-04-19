import hashlib
from pathlib import Path
from typing import Optional
from tree_sitter import Language as TSLanguage, Parser
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript

from backend.models.schemas import CodeChunk, Language

# Build grammars once at import time
PY_LANGUAGE  = TSLanguage(tspython.language())
JS_LANGUAGE  = TSLanguage(tsjavascript.language())

def _make_parser(lang: Language) -> Parser:
    p = Parser()
    if lang == Language.PYTHON:
        p.language = PY_LANGUAGE
    else:
        p.language = JS_LANGUAGE
    return p

def _detect_language(file_path: str) -> Language:
    ext = Path(file_path).suffix.lower()
    mapping = {
        ".py": Language.PYTHON,
        ".js": Language.JAVASCRIPT,
        ".ts": Language.TYPESCRIPT,
        ".jsx": Language.JAVASCRIPT,
        ".tsx": Language.TYPESCRIPT,
    }
    return mapping.get(ext, Language.UNKNOWN)

def _chunk_id(file_path: str, start: int, end: int) -> str:
    raw = f"{file_path}:{start}:{end}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]

def _get_node_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

def _extract_docstring_python(node, source: bytes) -> Optional[str]:
    """Extract docstring from a Python function/class node."""
    for child in node.children:
        if child.type == "block":
            for stmt in child.children:
                if stmt.type == "expression_statement":
                    for sub in stmt.children:
                        if sub.type == "string":
                            return _get_node_text(sub, source).strip('"\' \n')
    return None

def _extract_docstring_js(node, source: bytes) -> Optional[str]:
    """Extract JSDoc comment before a JS/TS function."""
    # Look at preceding siblings for block comments
    parent = node.parent
    if not parent:
        return None
    siblings = list(parent.children)
    idx = siblings.index(node)
    for i in range(idx - 1, max(idx - 3, -1), -1):
        sib = siblings[i]
        if sib.type == "comment":
            text = _get_node_text(sib, source)
            if text.startswith("/**") or text.startswith("//"):
                return text.strip()
    return None

def _collect_imports_python(tree, source: bytes) -> list[str]:
    imports = []
    for node in tree.root_node.children:
        if node.type in ("import_statement", "import_from_statement"):
            imports.append(_get_node_text(node, source).strip())
    return imports

def _collect_imports_js(tree, source: bytes) -> list[str]:
    imports = []
    for node in tree.root_node.children:
        if node.type in ("import_statement", "import_declaration"):
            imports.append(_get_node_text(node, source).strip())
    return imports

def _chunk_python(file_path: str, source: bytes, tree) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []
    all_imports = _collect_imports_python(tree, source)

    # Emit an import-block chunk if there are imports
    if all_imports:
        block = "\n".join(all_imports)
        chunks.append(CodeChunk(
            chunk_id=_chunk_id(file_path, 0, len(all_imports)),
            file_path=file_path,
            language=Language.PYTHON,
            chunk_type="import_block",
            name="imports",
            content=block,
            start_line=1,
            end_line=len(all_imports),
            imports=all_imports,
        ))

    def walk(node, parent_class: Optional[str] = None):
        if node.type == "class_definition":
            class_name = ""
            for child in node.children:
                if child.type == "identifier":
                    class_name = _get_node_text(child, source)
                    break
            class_text = _get_node_text(node, source)
            chunks.append(CodeChunk(
                chunk_id=_chunk_id(file_path, node.start_point[0], node.end_point[0]),
                file_path=file_path,
                language=Language.PYTHON,
                chunk_type="class",
                name=class_name,
                content=class_text[:3000],  # cap very large classes
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                docstring=_extract_docstring_python(node, source),
                imports=all_imports,
            ))
            for child in node.children:
                walk(child, parent_class=class_name)

        elif node.type in ("function_definition", "async_function_def"):
            func_name = ""
            for child in node.children:
                if child.type == "identifier":
                    func_name = _get_node_text(child, source)
                    break
            func_text = _get_node_text(node, source)
            chunks.append(CodeChunk(
                chunk_id=_chunk_id(file_path, node.start_point[0], node.end_point[0]),
                file_path=file_path,
                language=Language.PYTHON,
                chunk_type="function",
                name=func_name,
                content=func_text[:2000],
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent_name=parent_class,
                docstring=_extract_docstring_python(node, source),
                imports=all_imports,
            ))
        else:
            for child in node.children:
                walk(child, parent_class=parent_class)

    for node in tree.root_node.children:
        walk(node)

    return chunks

def _chunk_js(file_path: str, source: bytes, tree, lang: Language) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []
    all_imports = _collect_imports_js(tree, source)

    if all_imports:
        block = "\n".join(all_imports)
        chunks.append(CodeChunk(
            chunk_id=_chunk_id(file_path, 0, len(all_imports)),
            file_path=file_path,
            language=lang,
            chunk_type="import_block",
            name="imports",
            content=block,
            start_line=1,
            end_line=len(all_imports),
            imports=all_imports,
        ))

    FUNC_TYPES = {
        "function_declaration", "function_expression",
        "arrow_function", "method_definition",
        "generator_function_declaration",
    }
    CLASS_TYPES = {"class_declaration", "class_expression"}

    def walk(node, parent_class: Optional[str] = None):
        if node.type in CLASS_TYPES:
            class_name = ""
            for child in node.children:
                if child.type == "identifier":
                    class_name = _get_node_text(child, source)
                    break
            chunks.append(CodeChunk(
                chunk_id=_chunk_id(file_path, node.start_point[0], node.end_point[0]),
                file_path=file_path,
                language=lang,
                chunk_type="class",
                name=class_name,
                content=_get_node_text(node, source)[:3000],
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                docstring=_extract_docstring_js(node, source),
                imports=all_imports,
            ))
            for child in node.children:
                walk(child, parent_class=class_name)

        elif node.type in FUNC_TYPES:
            func_name = ""
            for child in node.children:
                if child.type in ("identifier", "property_identifier"):
                    func_name = _get_node_text(child, source)
                    break
            chunks.append(CodeChunk(
                chunk_id=_chunk_id(file_path, node.start_point[0], node.end_point[0]),
                file_path=file_path,
                language=lang,
                chunk_type="function",
                name=func_name or "anonymous",
                content=_get_node_text(node, source)[:2000],
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent_name=parent_class,
                docstring=_extract_docstring_js(node, source),
                imports=all_imports,
            ))
        else:
            for child in node.children:
                walk(child, parent_class=parent_class)

    for node in tree.root_node.children:
        walk(node)

    return chunks

def chunk_file(file_path: str) -> list[CodeChunk]:
    """Main entry point. Parse a file and return all its chunks."""
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return []

    lang = _detect_language(file_path)
    if lang == Language.UNKNOWN:
        return []

    try:
        source = path.read_bytes()
        parser_lang = Language.PYTHON if lang == Language.PYTHON else Language.JAVASCRIPT
        parser = _make_parser(parser_lang)
        tree = parser.parse(source)

        if lang == Language.PYTHON:
            return _chunk_python(file_path, source, tree)
        else:
            return _chunk_js(file_path, source, tree, lang)
    except Exception as e:
        print(f"[chunker] Failed on {file_path}: {e}")
        return []
