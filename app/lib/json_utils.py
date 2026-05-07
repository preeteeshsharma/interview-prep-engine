import re


def strip_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) that Claude sometimes wraps JSON in."""
    return re.sub(r"^```[a-z]*\n?", "", text.strip(), flags=re.MULTILINE).rstrip("`").strip()
