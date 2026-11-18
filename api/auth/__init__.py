"""认证与权限域（P1）。

移植自 ZNCBZS `backend/core/auth.py` + `backend/api/routes/auth.py` 的设计，
按本项目"零额外运行时依赖 + SQLite 单文件库"的既有约定重写：

- 密码哈希：PBKDF2-HMAC-SHA256（标准库），兼容校验历史 bcrypt 哈希；
- 令牌：HS256 JWT（标准库 hmac 实现），access/refresh 双令牌 + jti 撤销；
- 权限：内置四角色 RBAC（admin / analyst / auditor / viewer）+ 权限点矩阵；
- 免登录形态：RISK_AUTH_MODE=local 时以 local-admin 放行，服务桌面端与演示。
"""

from __future__ import annotations

from api.auth.rbac import (
    ALL_PERMISSIONS,
    PERMISSIONS,
    ROLE_LABELS,
    UserRole,
    permissions_for,
    role_has,
)

__all__ = [
    "ALL_PERMISSIONS",
    "PERMISSIONS",
    "ROLE_LABELS",
    "UserRole",
    "permissions_for",
    "role_has",
]