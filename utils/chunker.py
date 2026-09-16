def chunk_text(text: str, chunk_size: int) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
