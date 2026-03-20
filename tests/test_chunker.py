import tempfile, os, textwrap
from backend.tools.ast_chunker import chunk_file
from backend.models.schemas import Language

def _write(suffix, content):
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(textwrap.dedent(content))
    f.flush()
    return f.name

def test_python_function_chunk():
    path = _write(".py", """
        def add(a, b):
            return a + b
        def subtract(a, b):
            return a - b
    """)
    chunks = chunk_file(path)
    os.unlink(path)
    names = [c.name for c in chunks]
    assert "add" in names
    assert "subtract" in names

def test_python_class_chunk():
    path = _write(".py", """
        class MyClass:
            def method(self):
                pass
    """)
    chunks = chunk_file(path)
    os.unlink(path)
    types = [c.chunk_type for c in chunks]
    assert "class" in types

def test_js_function_chunk():
    path = _write(".js", """
        function greet(name) {
            return 'hello ' + name;
        }
    """)
    chunks = chunk_file(path)
    os.unlink(path)
    assert any(c.name == "greet" for c in chunks)

def test_unknown_extension_returns_empty():
    path = _write(".txt", "hello world")
    chunks = chunk_file(path)
    os.unlink(path)
    assert chunks == []

def test_chunk_has_line_numbers():
    path = _write(".py", """
        def foo():
            x = 1
            return x
    """)
    chunks = chunk_file(path)
    os.unlink(path)
    fn = next((c for c in chunks if c.name == "foo"), None)
    assert fn is not None
    assert fn.start_line > 0
    assert fn.end_line >= fn.start_line
