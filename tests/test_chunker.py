from app.lib.chunker import chunk_message


def test_short_message_no_split():
    assert chunk_message("hello") == ["hello"]


def test_long_message_splits():
    long = "word\n" * 1000
    chunks = chunk_message(long)
    assert len(chunks) > 1
    assert all(len(c) <= 4096 for c in chunks)
    assert chunks[0].startswith("(1/")
