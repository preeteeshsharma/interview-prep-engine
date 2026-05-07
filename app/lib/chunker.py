def chunk_message(text: str, limit: int = 4096) -> list[str]:
    """Split text into chunks no longer than `limit` characters.

    Splits on newlines, never mid-word. Adds a (1/N) prefix to each chunk
    when the message requires more than one chunk.
    """
    if len(text) <= limit:
        return [text]

    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        # A single line that exceeds the limit must be split on word boundaries.
        if len(line) > limit:
            # Flush current buffer first.
            if current:
                chunks.append("".join(current))
                current = []
                current_len = 0

            words = line.split(" ")
            word_buf: list[str] = []
            word_buf_len = 0
            for word in words:
                # +1 for the space we'd prepend (except for the first word).
                sep_len = 1 if word_buf else 0
                if word_buf_len + sep_len + len(word) > limit:
                    if word_buf:
                        chunks.append(" ".join(word_buf))
                    word_buf = [word]
                    word_buf_len = len(word)
                else:
                    word_buf.append(word)
                    word_buf_len += sep_len + len(word)
            if word_buf:
                remainder = " ".join(word_buf)
                # Try to continue with the next batch in the main loop.
                current = [remainder]
                current_len = len(remainder)
        elif current_len + len(line) > limit:
            # Current line would overflow — flush and start fresh.
            chunks.append("".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line)

    if current:
        chunks.append("".join(current))

    if len(chunks) == 1:
        return chunks

    # Prefix each chunk with (i/N).
    total = len(chunks)
    return [f"({i + 1}/{total}) {chunk}" for i, chunk in enumerate(chunks)]
