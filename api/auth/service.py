"""用户与会话业务逻辑（SQLite，沿用 api/db/database 的连接约定）。

对应 ZNCBZS `backend/api/routes/auth.py` 中的业务部分，抽成服务函数以便
路由层、测试与未来的 CLI 复用。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

from api.auth import rbac
from api.auth.passwords import (
    check_strength,
    generate_password,
    hash_password,
    needs_rehash,
    verify_password,
)
from config import settings

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


class AuthError(Exception):
    """认证/账号类错误（路由层转 HTTP 状态码）。"""

    def __init__(self, message: str, *, status_code: int = 401, code: str = "auth_error",
                 retry_after: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# 行 → 视图对象
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now()


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def public_user(row: dict) -> dict:
    """对外暴露的用户视图（绝不含 hashed_password）。"""
    role = rbac.normalize_role(row.get("role"))
    return {
        "id": row.get("id", ""),
        "username": row.get("username", ""),
        "email": row.get("email", "") or "",
        "role": role,
        "role_label": rbac.ROLE_LABELS.get(role, role),
        "permissions": rbac.permissions_for(role),
        "is_active": bool(row.get("is_active", 1)),
        "must_change_password": bool(row.get("must_change_password", 0)),
        "last_login_at": row.get("last_login_at", "") or "",
        "note": row.get("note", "") or "",
        "created_at": row.get("created_at", "") or "",
    }


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def get_by_id(user_id: str) -> dict | None:
    from api.db.database import query

    if not user_id:
        return None
    rows = query("SELECT * FROM user WHERE id = ?", (user_id,))
    return rows[0] if rows else None


def get_by_username(username: str) -> dict | None:
    from api.db.database import query

    if not username:
        return None
    rows = query("SELECT * FROM user WHERE username = ?", (username,))
    return rows[0] if rows else None


def list_users(keyword: str | None = None, role: str | None = None) -> dict:
    from api.db.database import query

    where: list[str] = []
    params: list = []
    if keyword:
        where.append("(username LIKE ? OR email LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if role and rbac.is_valid_role(role):
        where.append("role = ?")
        params.append(rbac.normalize_role(role))
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    rows = query(
        f"SELECT * FROM user{clause} ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END, username",
        tuple(params),
    )
    return {
        "total": len(rows),
        "items": [public_user(r) for r in rows],
        "roles": rbac.describe_roles(),
    }


def count_active_admins() -> int:
    from api.db.database import query

    rows = query("SELECT COUNT(*) AS n FROM user WHERE role = 'admin' AND is_active = 1")
    return int(rows[0]["n"]) if rows else 0


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def _validate_username(username: str) -> str:
    value = (username or "").strip()
    if not USERNAME_RE.match(value):
        raise AuthError("用户名需为 3-32 位字母/数字/下划线/点/横线", status_code=422,
                        code="invalid_username")
    return value


def _validate_password(password: str) -> str:
    problems = check_strength(password, min_length=settings.PASSWORD_MIN_LENGTH)
    if problems:
        raise AuthError("；".join(problems), status_code=422, code="weak_password")
    return password


def _validate_role(role: str) -> str:
    if not rbac.is_valid_role(role):
        raise AuthError(f"未知角色：{role}", status_code=422, code="invalid_role")
    return rbac.normalize_role(role)


# ---------------------------------------------------------------------------
# 创建 / 修改
# ---------------------------------------------------------------------------

def create_user(
    *,
    username: str,
    password: str,
    email: str = "",
    role: str = rbac.UserRole.VIEWER,
    note: str = "",
    must_change_password: bool = True,
) -> dict:
    from api.db.database import execute

    username = _validate_username(username)
    _validate_password(password)
    role = _validate_role(role)
    if get_by_username(username):
        raise AuthError("用户名已存在", status_code=409, code="username_taken")

    user_id = str(uuid.uuid4())
    execute(
        "INSERT INTO user (id, username, email, hashed_password, role, is_active,"
        " password_version, must_change_password, note) VALUES (?,?,?,?,?,1,1,?,?)",
        (user_id, username, (email or "").strip(), hash_password(password), role,
         1 if must_change_password else 0, note or ""),
    )
    row = get_by_id(user_id)
    if not row:
        raise AuthError("用户创建失败", status_code=500, code="create_failed")
    return public_user(row)


def update_user(
    user_id: str,
    *,
    email: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    note: str | None = None,
) -> dict:
    from api.db.database import execute

    row = get_by_id(user_id)
    if not row:
        raise AuthError("用户不存在", status_code=404, code="user_not_found")

    sets: list[str] = []
    params: list = []
    if email is not None:
        sets.append("email = ?")
        params.append(email.strip())
    if note is not None:
        sets.append("note = ?")
        params.append(note)
    if role is not None:
        new_role = _validate_role(role)
        if row["role"] == rbac.UserRole.ADMIN and new_role != rbac.UserRole.ADMIN:
            if count_active_admins() <= 1:
                raise AuthError("至少保留一个启用状态的管理员", status_code=409,
                                code="last_admin")
        sets.append("role = ?")
        params.append(new_role)
    if is_active is not None:
        if not is_active and row["role"] == rbac.UserRole.ADMIN and count_active_admins() <= 1:
            raise AuthError("至少保留一个启用状态的管理员", status_code=409, code="last_admin")
        sets.append("is_active = ?")
        params.append(1 if is_active else 0)

    if not sets:
        return public_user(row)

    sets.append("updated_at = datetime('now','localtime')")
    params.append(user_id)
    execute(f"UPDATE user SET {', '.join(sets)} WHERE id = ?", tuple(params))
    return public_user(get_by_id(user_id) or row)


def set_password(user_id: str, new_password: str, *, must_change: bool = False) -> dict:
    """重置/修改密码：password_version + 1，使该用户全部旧令牌立即失效。"""
    from api.db.database import execute

    row = get_by_id(user_id)
    if not row:
        raise AuthError("用户不存在", status_code=404, code="user_not_found")
    _validate_password(new_password)
    execute(
        "UPDATE user SET hashed_password = ?, password_version = password_version + 1,"
        " must_change_password = ?, failed_attempts = 0, locked_until = '',"
        " updated_at = datetime('now','localtime') WHERE id = ?",
        (hash_password(new_password), 1 if must_change else 0, user_id),
    )
    return public_user(get_by_id(user_id) or row)


def change_own_password(user_id: str, old_password: str, new_password: str) -> dict:
    row = get_by_id(user_id)
    if not row:
        raise AuthError("用户不存在", status_code=404, code="user_not_found")
    if not verify_password(old_password, row.get("hashed_password", "")):
        raise AuthError("原密码不正确", status_code=400, code="bad_old_password")
    if old_password == new_password:
        raise AuthError("新密码不能与原密码相同", status_code=422, code="same_password")
    return set_password(user_id, new_password, must_change=False)


def reset_password(user_id: str, new_password: str | None = None) -> dict:
    """管理员重置密码；未指定新密码时随机生成并一次性返回明文。"""
    generated = None
    if not new_password:
        generated = generate_password(12)
        new_password = generated
    user = set_password(user_id, new_password, must_change=True)
    return {"user": user, "password": generated}


def deactivate_user(user_id: str) -> dict:
    return update_user(user_id, is_active=False)


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------

def authenticate(username: str, password: str) -> dict:
    """校验账号密码，返回用户行（含 hashed_password，供路由签发令牌）。

    失败语义与 ZNCBZS 一致：不区分"用户不存在/密码错误"，防账号枚举；
    连续失败达阈值后锁定（默认 5 次 / 15 分钟）。
    """
    from api.db.database import execute

    row = get_by_username((username or "").strip())
    if not row:
        raise AuthError("用户名或密码错误", status_code=401, code="invalid_credentials")

    if not row.get("is_active", 1):
        raise AuthError("账户已被禁用，请联系管理员", status_code=403, code="user_disabled")

    locked_until = _parse_dt(row.get("locked_until"))
    if locked_until and locked_until > _now():
        remain = int((locked_until - _now()).total_seconds() // 60) + 1
        raise AuthError(f"账号已锁定，请 {remain} 分钟后重试", status_code=423,
                        code="account_locked", retry_after=remain * 60)

    if not verify_password(password, row.get("hashed_password", "")):
        attempts = int(row.get("failed_attempts") or 0) + 1
        lock_until = ""
        if attempts >= settings.LOGIN_MAX_ATTEMPTS:
            lock_until = _fmt(_now() + timedelta(minutes=settings.LOGIN_LOCK_MINUTES))
        execute(
            "UPDATE user SET failed_attempts = ?, locked_until = ? WHERE id = ?",
            (attempts, lock_until, row["id"]),
        )
        if lock_until:
            raise AuthError(
                f"密码错误次数过多，账号锁定 {settings.LOGIN_LOCK_MINUTES} 分钟",
                status_code=423, code="account_locked",
                retry_after=settings.LOGIN_LOCK_MINUTES * 60,
            )
        remain = max(1, settings.LOGIN_MAX_ATTEMPTS - attempts)
        raise AuthError(f"用户名或密码错误，还可尝试 {remain} 次", status_code=401,
                        code="invalid_credentials")

    # 登录成功：清空失败计数、记录时间；口令算法升级则顺手重哈希
    if needs_rehash(row.get("hashed_password", "")):
        execute(
            "UPDATE user SET hashed_password = ? WHERE id = ?",
            (hash_password(password), row["id"]),
        )
    execute(
        "UPDATE user SET failed_attempts = 0, locked_until = '',"
        " last_login_at = datetime('now','localtime') WHERE id = ?",
        (row["id"],),
    )
    refreshed = get_by_id(row["id"]) or row
    return refreshed


# ---------------------------------------------------------------------------
# 种子管理员
# ---------------------------------------------------------------------------

def ensure_admin() -> dict | None:
    """首启幂等播种管理员（移植 ZNCBZS main.py::_create_initial_admin）。

    RISK_ADMIN_PASSWORD 未配置时使用演示口令 ``admin12345`` 并强制首次改密，
    同时写一条启动告警日志——避免"未设密码就没人能登录"的死锁。
    """
    try:
        if get_by_username(settings.INITIAL_ADMIN_USERNAME):
            return None
        password = settings.INITIAL_ADMIN_PASSWORD or settings.DEMO_ADMIN_PASSWORD
        must_change = not bool(settings.INITIAL_ADMIN_PASSWORD)
        user = create_user(
            username=settings.INITIAL_ADMIN_USERNAME,
            password=password,
            email=settings.INITIAL_ADMIN_EMAIL,
            role=rbac.UserRole.ADMIN,
            note="系统初始化自动创建",
            must_change_password=must_change,
        )
        return {**user, "_demo_password": must_change, "_password": password}
    except AuthError:
        return None
    except Exception:  # noqa: BLE001 —— 建库异常不应阻断服务启动
        return None