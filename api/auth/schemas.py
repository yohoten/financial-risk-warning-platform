"""认证域请求/响应模型（Pydantic v2）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    remember: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class LogoutRequest(BaseModel):
    """注销请求体：refresh_token 可省略（前端可能只持有 access token）。"""

    refresh_token: str = ""


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=6, max_length=256)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=256)
    email: str = ""
    role: str = "viewer"
    note: str = ""


class UserUpdateRequest(BaseModel):
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None
    note: str | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class MessageResponse(BaseModel):
    ok: bool = True
    message: str = ""