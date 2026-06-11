"""Manual OAuth bridge service.

Lets the user walk through OpenAI's standard OAuth + PKCE authorization-code flow in their own browser:
  1. The backend generates code_verifier / code_challenge / state and builds the authorize URL.
  2. The user logs in; the browser is eventually redirected by OpenAI to the
     platform.openai.com callback URL; the user grabs the code from the address bar or devtools and pastes it back into the frontend.
  3. The backend uses the stored code_verifier + the pasted code to call /api/accounts/oauth/token
     and obtains {access_token, refresh_token, id_token}.

The resulting refresh_token uses the same client_id as account_service's auto-refresh mechanism
(app_2SKx67EdpoN0G6j64rFvigXD), so once persisted it directly enters the keepalive cycle.
"""
from __future__ import annotations

import secrets
import threading
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from curl_cffi import requests

from services.proxy_service import proxy_settings
from services.register.openai_register import (
    auth_base,
    common_headers,
    platform_auth0_client,
    platform_base,
    platform_oauth_audience,
    platform_oauth_client_id,
    platform_oauth_redirect_uri,
    sec_ch_ua,
    user_agent,
)


class OAuthLoginError(Exception):
    """Expected errors in the OAuth bridge flow; translated into 400 by the API layer."""


class OAuthLoginService:
    """Maintains temporary PKCE sessions and completes the code -> token exchange."""

    _SESSION_TTL_SECONDS = 10 * 60  # Max time for the user to open the browser and grab the code
    _MAX_SESSIONS = 64               # Prevent buildup; evict the oldest when over capacity

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _generate_pkce() -> tuple[str, str]:
        """Generate a PKCE code_verifier and its matching code_challenge (S256)."""
        from utils.pkce import generate_pkce
        return generate_pkce()

    def _purge_expired_locked(self) -> None:
        """Clean up expired or overflowing sessions; must be called while holding the lock."""
        now = time.time()
        expired = [sid for sid, item in self._sessions.items() if now - item["created_at"] > self._SESSION_TTL_SECONDS]
        for sid in expired:
            self._sessions.pop(sid, None)
        if len(self._sessions) > self._MAX_SESSIONS:
            ordered = sorted(self._sessions.items(), key=lambda kv: kv[1]["created_at"])
            for sid, _ in ordered[: len(self._sessions) - self._MAX_SESSIONS]:
                self._sessions.pop(sid, None)

    def start(self, email_hint: str = "") -> dict[str, str]:
        """Register a new PKCE session and return the session_id and an authorize_url for the user to open.

        state looks like "<session_id>.<nonce>", so the callback URL carries the session_id,
        letting finish() recover the correct verifier from the URL even if the frontend React state is overwritten.
        """
        verifier, challenge = self._generate_pkce()
        nonce = secrets.token_urlsafe(32)
        device_id = str(uuid.uuid4())
        session_id = uuid.uuid4().hex
        state = f"{session_id}.{secrets.token_urlsafe(16)}"

        params = {
            "issuer": auth_base,
            "client_id": platform_oauth_client_id,
            "audience": platform_oauth_audience,
            "redirect_uri": platform_oauth_redirect_uri,
            "device_id": device_id,
            "screen_hint": "login_or_signup",
            "max_age": "0",
            "scope": "openid profile email offline_access",
            "response_type": "code",
            "response_mode": "query",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "auth0Client": platform_auth0_client,
        }
        email_hint = str(email_hint or "").strip()
        if email_hint:
            params["login_hint"] = email_hint

        authorize_url = f"{auth_base}/api/accounts/authorize?{urlencode(params)}"

        with self._lock:
            self._purge_expired_locked()
            self._sessions[session_id] = {
                "code_verifier": verifier,
                "state": state,
                "created_at": time.time(),
                "redirect_uri": platform_oauth_redirect_uri,
            }

        return {
            "session_id": session_id,
            "authorize_url": authorize_url,
            "expires_in": str(self._SESSION_TTL_SECONDS),
            "redirect_uri_prefix": platform_oauth_redirect_uri,
        }

    @staticmethod
    def _extract_code_from_callback(value: str) -> tuple[str, str]:
        """Extract (code, state) from a callback URL or a raw code.

        Allows the user to paste a full platform.openai.com/auth/callback?code=...&state=... URL,
        or to paste just the code itself.
        """
        raw = str(value or "").strip()
        if not raw:
            return "", ""
        if raw.startswith("http://") or raw.startswith("https://"):
            try:
                parsed = parse_qs(urlparse(raw).query)
            except Exception as exc:
                raise OAuthLoginError(f"Failed to parse the callback URL: {exc}") from exc
            code = str((parsed.get("code") or [""])[0]).strip()
            state = str((parsed.get("state") or [""])[0]).strip()
            if not code:
                err = str((parsed.get("error_description") or parsed.get("error") or [""])[0]).strip()
                raise OAuthLoginError(err or "The callback URL has no code parameter")
            return code, state
        # The user may have pasted the code string directly
        return raw, ""

    def finish(self, session_id: str, callback: str) -> dict[str, str]:
        """Use the code_verifier paired with session_id to exchange the callback code for the token triplet.

        - Prefer the session_id embedded in the callback URL's state (more reliable),
          and only fall back to the session_id sent by the frontend;
        - On failure, do not immediately destroy the session (a mismatched OAuth code usually does not consume the code),
          only pop on a successful exchange, so the user can retry with the same verifier.
        """
        body_sid = str(session_id or "").strip()
        code, state = self._extract_code_from_callback(callback)
        if not code:
            raise OAuthLoginError("Missing code or callback URL")

        # The session_id embedded in state has the highest priority
        state_sid = state.split(".", 1)[0] if state else ""
        candidate_sids = [sid for sid in (state_sid, body_sid) if sid]
        if not candidate_sids:
            raise OAuthLoginError("Neither a session_id was provided nor did the callback URL carry a state")

        with self._lock:
            self._purge_expired_locked()
            session = None
            picked_sid = ""
            for sid in candidate_sids:
                cur = self._sessions.get(sid)
                if cur is not None:
                    session = cur
                    picked_sid = sid
                    break
        if session is None:
            raise OAuthLoginError(
                "The OAuth session has expired or does not exist; go back to the import dialog, click \"Regenerate\", and try again"
            )

        if state and session.get("state") and state != session["state"]:
            raise OAuthLoginError(
                "state mismatch. A common cause: you clicked \"Open authorization page\" twice, but the browser is still logged into the previous window. Click \"Regenerate\" and start over."
            )

        tokens = self._exchange_code(
            code,
            session["code_verifier"],
            session.get("redirect_uri") or platform_oauth_redirect_uri,
        )
        # Only consume the session after a successful exchange
        with self._lock:
            self._sessions.pop(picked_sid, None)
        return tokens

    @staticmethod
    def _exchange_code(code: str, code_verifier: str, redirect_uri: str) -> dict[str, str]:
        """Call /api/accounts/oauth/token to exchange code+verifier for the token triplet."""
        kwargs = proxy_settings.build_session_kwargs(impersonate="chrome", verify=False)
        session = requests.Session(**kwargs)
        try:
            response = session.post(
                f"{auth_base}/api/accounts/oauth/token",
                headers={
                    **common_headers,
                    "referer": f"{platform_base}/",
                    "origin": platform_base,
                    "auth0-client": platform_auth0_client,
                    "sec-ch-ua": sec_ch_ua,
                    "user-agent": user_agent,
                },
                json={
                    "client_id": platform_oauth_client_id,
                    "code_verifier": code_verifier,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                timeout=60,
            )
        except Exception as exc:
            raise OAuthLoginError(f"Network error during token exchange: {exc}") from exc
        finally:
            session.close()

        try:
            data = response.json() if response.text else {}
        except Exception:
            data = {}

        if response.status_code != 200 or not isinstance(data, dict) or not data.get("access_token"):
            detail = ""
            if isinstance(data, dict):
                detail = str(data.get("error_description") or data.get("error") or data.get("message") or "")
            if not detail:
                try:
                    detail = str(response.text or "")[:300]
                except Exception:
                    detail = ""
            # Log to docker logs for debugging — the reason an OAuth token exchange fails is often only visible here
            print(
                f"[oauth-login] /api/accounts/oauth/token rejected: "
                f"status={response.status_code} detail={detail!r} "
                f"raw_body={(getattr(response, 'text', '') or '')[:500]!r}",
                flush=True,
            )
            raise OAuthLoginError(
                f"OpenAI refused the token exchange (HTTP {response.status_code}){': ' + detail if detail else ''}"
            )

        access_token = str(data.get("access_token") or "").strip()
        refresh_token = str(data.get("refresh_token") or "").strip()
        id_token = str(data.get("id_token") or "").strip()

        if not access_token:
            raise OAuthLoginError("The access_token returned by OpenAI is empty")
        if not refresh_token:
            # When the scope includes offline_access a refresh_token is normally issued; give a clear hint here
            raise OAuthLoginError(
                "OpenAI did not return a refresh_token (the scope may not include offline_access, or the code was already used)"
            )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "id_token": id_token,
        }


oauth_login_service = OAuthLoginService()
