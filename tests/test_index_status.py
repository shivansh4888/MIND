from backend.models.schemas import IndexStatus


def test_index_status_tracks_root_path():
    status = IndexStatus(root_path="/tmp/project", is_indexing=True)

    assert status.root_path == "/tmp/project"
    assert status.is_indexing is True
