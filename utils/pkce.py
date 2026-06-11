"""PKCE (Proof Key for Code Exchange) utility functions."""
from __future__ import annotations

import base64
import hashlib
import secrets


def generate_pkce() -> tuple[str, str]:
    """Generate a PKCE code_verifier and its matching code_challenge (S256).

    Returns:
        (code_verifier, code_challenge) tuple
    """
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge
