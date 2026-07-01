import hashlib
import json
import smtplib
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, field_validator

from nebulai.core.auth import (
    AuthUser,
    clear_session_cookie,
    get_current_user,
    hash_email_code,
    issue_session_cookie,
    make_email_code,
)
from nebulai.core.config import settings
from nebulai.stores.postgres import postgres_store

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthUserResponse(BaseModel):
    id: str
    email: str | None
    name: str
    avatar_url: str | None = None
    workspace_id: str


class EmailCodeRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_email(value)


class EmailCodeResponse(BaseModel):
    status: str
    message: str
    dev_code: str | None = None


class EmailLoginRequest(BaseModel):
    email: str
    code: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_email(value)


class OAuthProviderResponse(BaseModel):
    provider: str
    configured: bool
    url: str | None = None
    message: str


@router.get("/me", response_model=AuthUserResponse)
async def me(user: AuthUser = Depends(get_current_user)) -> AuthUserResponse:
    return _user_response(user)


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    clear_session_cookie(response)
    return {"status": "logged_out"}


@router.post("/email/request-code", response_model=EmailCodeResponse)
async def request_email_code(payload: EmailCodeRequest, request: Request) -> EmailCodeResponse:
    pg = getattr(request.app.state, "postgres_store", postgres_store)
    code = make_email_code()
    await pg.create_email_code(str(uuid4()), payload.email, hash_email_code(code))
    if not settings.email_login_dev_mode:
        _send_email_code(payload.email, code)
    return EmailCodeResponse(
        status="sent",
        message="验证码已发送，请检查邮箱。",
        dev_code=code if settings.email_login_dev_mode else None,
    )


@router.post("/email/login", response_model=AuthUserResponse)
async def login_with_email(payload: EmailLoginRequest, request: Request, response: Response) -> AuthUserResponse:
    pg = getattr(request.app.state, "postgres_store", postgres_store)
    ok = await pg.consume_email_code(payload.email, hash_email_code(payload.code))
    if not ok:
        raise HTTPException(status_code=400, detail="验证码无效或已过期。")
    user = await _upsert_auth_user(
        pg,
        provider="email",
        subject=payload.email.lower(),
        email=payload.email.lower(),
        name=payload.email.split("@", 1)[0],
        avatar_url=None,
    )
    issue_session_cookie(response, user)
    return _user_response(user)


@router.post("/dev-login", response_model=AuthUserResponse)
async def dev_login(request: Request, response: Response) -> AuthUserResponse:
    if not settings.email_login_dev_mode and not settings.testing:
        raise HTTPException(status_code=404, detail="Dev login is disabled.")

    pg = getattr(request.app.state, "postgres_store", postgres_store)
    user = await _upsert_auth_user(
        pg,
        provider="internal",
        subject="test@nebulai.local",
        email="test@nebulai.local",
        name="内部测试账号",
        avatar_url=None,
    )
    issue_session_cookie(response, user)
    return _user_response(user)


@router.get("/oauth/{provider}", response_model=OAuthProviderResponse)
async def oauth_start(provider: str) -> OAuthProviderResponse:
    url = _oauth_authorize_url(provider)
    if url is None:
        return OAuthProviderResponse(
            provider=provider,
            configured=False,
            message=f"{provider} OAuth 未配置 client id/secret。",
        )
    return OAuthProviderResponse(provider=provider, configured=True, url=url, message="OAuth provider configured.")


@router.get("/oauth/{provider}/redirect")
async def oauth_redirect(provider: str) -> RedirectResponse:
    url = _oauth_authorize_url(provider)
    if url is None:
        raise HTTPException(status_code=400, detail=f"{provider} OAuth 未配置。")
    return RedirectResponse(url)


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str, request: Request) -> RedirectResponse:
    pg = getattr(request.app.state, "postgres_store", postgres_store)
    profile = _fetch_oauth_profile(provider, code)
    user = await _upsert_auth_user(
        pg,
        provider=provider,
        subject=profile["subject"],
        email=profile.get("email"),
        name=profile.get("name") or profile.get("email") or f"{provider} user",
        avatar_url=profile.get("avatar_url"),
    )
    redirect = RedirectResponse(settings.app_base_url)
    issue_session_cookie(redirect, user)
    return redirect


async def _upsert_auth_user(
    pg: Any,
    *,
    provider: str,
    subject: str,
    email: str | None,
    name: str,
    avatar_url: str | None,
) -> AuthUser:
    user_id = f"{provider}-{hashlib.sha256(subject.encode('utf-8')).hexdigest()[:24]}"
    await pg.upsert_user(user_id, email, name, avatar_url, provider, subject)
    workspace_id = await pg.ensure_personal_workspace(user_id, name)
    return AuthUser(id=user_id, email=email, name=name, avatar_url=avatar_url, workspace_id=workspace_id)


def _oauth_authorize_url(provider: str) -> str | None:
    if provider == "github":
        if not settings.github_client_id or not settings.github_client_secret:
            return None
        params = urllib.parse.urlencode(
            {
                "client_id": settings.github_client_id,
                "redirect_uri": f"{settings.api_base_url}/api/auth/oauth/github/callback",
                "scope": "read:user user:email",
            }
        )
        return f"https://github.com/login/oauth/authorize?{params}"
    if provider == "google":
        if not settings.google_client_id or not settings.google_client_secret:
            return None
        params = urllib.parse.urlencode(
            {
                "client_id": settings.google_client_id,
                "redirect_uri": f"{settings.api_base_url}/api/auth/oauth/google/callback",
                "response_type": "code",
                "scope": "openid email profile",
                "access_type": "online",
            }
        )
        return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    return None


def _fetch_oauth_profile(provider: str, code: str) -> dict[str, str | None]:
    if provider == "github":
        token = _post_form(
            "https://github.com/login/oauth/access_token",
            {
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": f"{settings.api_base_url}/api/auth/oauth/github/callback",
            },
            accept="application/json",
        )
        profile = _get_json("https://api.github.com/user", token=str(token["access_token"]))
        email = profile.get("email")
        if not email:
            emails = _get_json("https://api.github.com/user/emails", token=str(token["access_token"]))
            if isinstance(emails, list):
                primary = next((item for item in emails if item.get("primary")), None)
                email = primary.get("email") if primary else None
        return {
            "subject": str(profile["id"]),
            "email": str(email) if email else None,
            "name": str(profile.get("name") or profile.get("login") or "GitHub User"),
            "avatar_url": str(profile.get("avatar_url")) if profile.get("avatar_url") else None,
        }
    if provider == "google":
        token = _post_form(
            "https://oauth2.googleapis.com/token",
            {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "redirect_uri": f"{settings.api_base_url}/api/auth/oauth/google/callback",
                "grant_type": "authorization_code",
            },
        )
        profile = _get_json(f"https://oauth2.googleapis.com/tokeninfo?id_token={token['id_token']}")
        return {
            "subject": str(profile["sub"]),
            "email": str(profile.get("email")) if profile.get("email") else None,
            "name": str(profile.get("name") or profile.get("email") or "Google User"),
            "avatar_url": str(profile.get("picture")) if profile.get("picture") else None,
        }
    raise HTTPException(status_code=404, detail="OAuth provider not supported.")


def _post_form(url: str, data: dict[str, str], accept: str = "application/json") -> dict[str, Any]:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, headers={"Accept": accept})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str, token: str | None = None) -> Any:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _send_email_code(email: str, code: str) -> None:
    if not settings.smtp_host:
        raise HTTPException(status_code=500, detail="SMTP 未配置，无法发送邮箱验证码。")

    message = EmailMessage()
    message["Subject"] = "nebulai bot 登录验证码"
    message["From"] = settings.email_login_from
    message["To"] = email
    message.set_content(f"你的 nebulai bot 登录验证码是：{code}\n\n验证码 10 分钟内有效。")

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
            if settings.smtp_use_tls:
                client.starttls()
            if settings.smtp_username or settings.smtp_password:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"邮箱验证码发送失败：{exc}") from exc


def _user_response(user: AuthUser) -> AuthUserResponse:
    return AuthUserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        workspace_id=user.workspace_id,
    )


def _validate_email(value: str) -> str:
    normalized = value.strip().lower()
    if "@" not in normalized or "." not in normalized.rsplit("@", 1)[-1]:
        raise ValueError("Invalid email address.")
    return normalized
