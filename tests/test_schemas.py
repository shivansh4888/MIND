from backend.models.schemas import CodeChunk, Language, AgentResponse

def test_code_chunk_defaults():
    c = CodeChunk(
        chunk_id="abc123",
        file_path="test.py",
        language=Language.PYTHON,
        chunk_type="function",
        content="def foo(): pass",
        start_line=1,
        end_line=1,
    )
    assert c.imports == []
    assert c.embedding is None
    assert c.parent_name is None

def test_agent_response_defaults():
    r = AgentResponse(answer="hello", model_used="llama")
    assert r.citations == []
    assert r.chunks_used == 0
