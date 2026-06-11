"""Verify whether automatic refresh for OAuth accounts is working.

Usage (inside the container, working directory /app):
    uv run python scripts/verify_oauth_refresh.py            # read-only diagnostics, safe
    uv run python scripts/verify_oauth_refresh.py --force    # actually trigger a refresh

Read-only mode: lists each account's remaining access_token lifetime, whether it has a refresh_token,
          last refresh time and last refresh error, to judge whether there is anything to refresh.
--force: forces a refresh_access_token(force=True) for every account that has a refresh_token,
          directly verifying whether the refresh_token + this project's client_id can obtain a new access_token from OpenAI.
          This actually rotates the access_token (the new token is valid and does not damage the account).
"""
from __future__ import annotations

import sys

from services.account_service import account_service


def _fmt_remaining(seconds: int | None) -> str:
    if seconds is None:
        return "cannot parse exp"
    if seconds <= 0:
        return f"expired {(-seconds) // 3600}h ago"
    return f"expires in {seconds // 3600}h{(seconds % 3600) // 60}m"


def diagnose() -> list[str]:
    """Read-only: print each account's refresh-readiness, return the list of tokens that have a refresh_token."""
    tokens = account_service.list_tokens()
    print(f"Total accounts: {len(tokens)}\n")
    refreshable: list[str] = []
    for token in tokens:
        account = account_service.get_account(token) or {}
        remaining = account_service._token_expires_in(token)
        has_rt = bool(str(account.get("refresh_token") or "").strip())
        if has_rt:
            refreshable.append(token)
        print(f"- email={account.get('email') or '(unknown)'}")
        print(f"    access_token[:20]   = {token[:20]}...")
        print(f"    time to expiry      = {_fmt_remaining(remaining)}")
        print(f"    refresh_token       = {'yes ✅' if has_rt else 'no ❌ (cannot auto-refresh)'}")
        print(f"    last_token_refresh_at    = {account.get('last_token_refresh_at')}")
        print(f"    last_token_refresh_error = {account.get('last_token_refresh_error')}")
        print()
    return refreshable


def force_refresh(tokens: list[str]) -> None:
    """Force a refresh for every account once, comparing before/after state to judge success."""
    if not tokens:
        print("No accounts have a refresh_token; cannot verify refresh.")
        return
    print("=" * 60)
    print(f"Starting forced refresh for {len(tokens)} accounts (real calls to OpenAI)...\n")
    ok = 0
    for token in tokens:
        before = account_service.get_account(token) or {}
        new_token = account_service.refresh_access_token(token, force=True, event="manual_verify")
        after = account_service.get_account(new_token) or {}
        err = str(after.get("last_token_refresh_error") or "").strip()
        rotated = new_token != token
        success = bool(new_token) and not err
        if success:
            ok += 1
        print(f"- email={before.get('email') or '(unknown)'}")
        print(f"    old access_token[:20] = {token[:20]}...")
        print(f"    new access_token[:20] = {new_token[:20]}...")
        print(f"    token rotated        = {'yes' if rotated else 'no (may return the same value when exp is not yet within the refresh window)'}")
        print(f"    last_token_refresh_at    = {after.get('last_token_refresh_at')}")
        print(f"    last_token_refresh_error = {after.get('last_token_refresh_error') or 'none'}")
        print(f"    >>> refresh result   = {'success ✅' if success else 'failed ❌'}")
        print()
    print("=" * 60)
    print(f"Summary: {ok}/{len(tokens)} accounts refreshed successfully")
    if ok == len(tokens):
        print("✅ The auto-refresh mechanism fully works for these accounts — refresh_token matches client_id.")
    else:
        print("❌ Some accounts failed to refresh; check last_token_refresh_error above, or the [oauth-login]/refresh logs in docker logs.")


def main() -> None:
    do_force = "--force" in sys.argv[1:]
    refreshable = diagnose()
    if do_force:
        force_refresh(refreshable)
    else:
        print("Tip: add the --force flag to actually trigger a refresh and verify it succeeds.")


if __name__ == "__main__":
    main()
