"""Replace known secret values in text before it is logged or returned."""
from __future__ import annotations


def scrub_secrets(text: str, secret_list: dict[str, str]) -> str:
    """Replace each non-empty value in secret_list with ***REDACTED[<key>]***. Call it on stdout and stderr."""
    # longest first, so a secret that contains a shorter one is removed whole
    for key, val in sorted(secret_list.items(), key=lambda kv: -len(kv[1] or "")):
        if val:
            text = text.replace(val, f"***REDACTED[{key}]***")
    return text
