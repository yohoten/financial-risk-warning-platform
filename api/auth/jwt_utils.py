"""HS256 JWT 签发与校验（标准库实现，零额外依赖）。

为什么不引 PyJWT / python-jose：
- 本项目需 PyInstaller 冻结成 Electron 后端，依赖越少越稳；
- HS256 只需 hmac + hashlib，实现 40 行即可完全符合 RFC 7519 的必需字段。

令牌载荷：
    sub  username
    uid  用户 id
    role 角色
    pv   密码版本（改密后 +1，旧令牌立即失效）
    jti  令牌唯一 id（撤销用）
    kind access | refresh
    iat / exp

与 ZNCBZS 的差异：新增 ``jti`` + ``pv``，解决其注释里"内存黑名单无法按用户批量
撤销令牌"的遗留问题。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

from config import settings

_HEADER = {"alg": "HS256", "typ": "JWT"}
_CLOCK_SKEW_SECONDS = 5


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(signing_input: bytes) -> bytes:
    return hmac.new(settings.auth_secret().encode("utf-8"), signing_input, hashlib.sha256).digest()


def encode(payload: dict) -> str:
    """把载荷编码并签名成 JWT 字符串。"""
    header_part = _b64u(json.dumps(_HEADER, separators=(",", ":"), sort_keys=True).encode())
    body_part = _b64u(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{header_part}.{body_part}".encode("ascii")
    return f"{header_part}.{body_part}.{_b64u(_sign(signing_input))}"


def decode(token: str, *, expected_kind: str | None = None, verify_exp: bool = True) -> dict | None:
    """校验并解析令牌；任何异常一律返回 None（调用方按 401 处理）。"""
    if not token or token.count(".") != 2:
        return None
    header_part, body_part, signature_part = token.split(".")
    try:
        signing_input = f"{header_part}.{body_part}".encode("ascii")
        expected_sig = _sign(signing_input)
        provided_sig = _b64u_decode(signature_part)
    except (ValueError, UnicodeEncodeError):
        return None
    if not hmac.compare_digest(expected_sig, provided_sig):
        return None
    try:
        payload = json.loads(_b64u_decode(body_part))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if expected_kind and payload.get("kind") != expected_kind:
        return None
    if verify_exp:
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)) or time.time() > float(exp) + _CLOCK_SKEW_SECONDS:
            return None
    return payload


def create_access_token(
    *,
    subject: str,
    user_id: str,
    role: str,
    password_version: int = 1,
    expires_minutes: int | None = None,
) -> tuple[str, str, int]:
    """签发 access token，返回 (token, jti, expires_at_epoch)。"""
    minutes = expires_minutes if expires_minutes is not None else settings.ACCESS_TOKEN_MINUTES
    now = int(time.time())
    exp = now + max(1, int(minutes)) * 60
    jti = uuid.uuid4().hex
    token = encode({
        "sub": subject,
        "uid": user_id,
        "role": role,
        "pv": int(password_version),
        "jti": jti,
        "kind": "access",
        "iat": now,
        "exp": exp,
    })
    return token, jti, exp


def create_refresh_token(
    *,
    subject: str,
    user_id: str,
    role: str,
    password_version: int = 1,
    expires_days: int | None = None,
) -> tuple[str, str, int]:
    """签发 refresh token，返回 (token, jti, expires_at_epoch)。"""
    days = expires_days if expires_days is not None else settings.REFRESH_TOKEN_DAYS
    now = int(time.time())
    exp = now + max(1, int(days)) * 86400
    jti = uuid.uuid4().hex
    token = encode({
        "sub": subject,
        "uid": user_id,
        "role": role,
        "pv": int(password_version),
        "jti": jti,
        "kind": "refresh",
        "iat": now,
        "exp": exp,
    })
    return token, jti, exp


def bearer_token(authorization: str | None) -> str | None:
    """从 Authorization 头提取 Bearer 令牌。"""
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.strip().lower() != "bearer" or not value.strip():
        return None
    return value.strip()