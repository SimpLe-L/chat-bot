import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status

from nebulai.core.config import settings
from nebulai.stores.postgres import postgres_store


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None
    name: str
    avatar_url: str | None
    workspace_id: str


def issue_session_cookie(response: Response, user: AuthUser) -> None:
    response.set_cookie(
        settings.auth_cookie_name,
        _sign_session({"user_id": user.id, "workspace_id": user.workspace_id}),
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=60 * 60 * 24 * 30,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.auth_cookie_name, path="/")


async def get_current_user(request: Request) -> AuthUser:
    pg = getattr(request.app.state, "postgres_store", postgres_store)
    token = request.cookies.get(settings.auth_cookie_name)
    payload = _verify_session(token) if token else None

    if payload is None:
        if settings.testing or not settings.auth_required:
            return AuthUser(
                id="local-user",
                email="local@nebulai.dev",
                name="Local User",
                avatar_url=None,
                workspace_id="local-workspace",
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    user = await pg.get_user_with_default_workspace(str(payload["user_id"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session.")
    return AuthUser(
        id=user["id"],
        email=user["email"],
        name=user["name"],
        avatar_url=user["avatar_url"],
        workspace_id=user["workspace_id"],
    )


CurrentUser = Depends(get_current_user)


def make_email_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_email_code(code: str) -> str:
    return hmac.new(
        settings.auth_session_secret.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _sign_session(payload: dict[str, Any]) -> str:
    body = {**payload, "iat": int(time.time())}
    encoded = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode("utf-8")).decode("ascii")
    signature = hmac.new(
        settings.auth_session_secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


def _verify_session(token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    encoded, signature = token.rsplit(".", 1)
    expected = hmac.new(
        settings.auth_session_secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("user_id") or not payload.get("workspace_id"):
        return None
    return payload
