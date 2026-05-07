from __future__ import annotations

# match_corpus is intentionally not wired into the default generate_plan flow.
# generate_plan uses Claude's built-in knowledge to suggest LeetCode problems (DSA),
# standard LLD problems, and company-tailored sysdesign problems.
#
# This module exists as an extension point for users who maintain a private local
# corpus of custom interview problems. To wire it in:
#   1. Set CORPUS_ROOTS in .env:
#      CORPUS_ROOTS=/path/to/lld-repo:LLD,/path/to/dsa-repo:DSA
#   2. Call match_corpus() inside generate_plan() and append results to the user prompt.


async def match_corpus(
    weak_patterns: list[str],
    exclude_recent: list[str],
    round_types: list[str] | None = None,
) -> list[str]:
    """Return drill suggestions from a user-configured local corpus.

    Not called by default. See module docstring for wiring instructions.
    Returns an empty list until configured.
    """
    return []
