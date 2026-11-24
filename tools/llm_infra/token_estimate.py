"""Conservative UTF-8 proxy, without a tokenizer dependency."""


def estimate_input_tokens(*parts: str) -> int:
    """Round up bytes / 3. Usually high for Latin and Vietnamese, closer for Japanese."""
    return (sum(len(part.encode("utf-8")) for part in parts) + 2) // 3
