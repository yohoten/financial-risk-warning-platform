"""密码哈希与强度校验（PBKDF2-HMAC-SHA256，标准库实现）。

存储格式：``pbkdf2_sha256$<iterations>$<salt_b64>$<digest_b64>``

为什么不用 bcrypt：
1. bcrypt 需额外二进制依赖，Electron 打包（PyInstaller）与离线环境易出问题；
2. passlib 1.7.x 与 bcrypt>=4.1 存在已知兼容告警；
3. OWASP 2023 起明确接受 PBKDF2-SHA256（>=600k 迭代）作为口令哈希方案。

为兼容从 ZNCBZS 等 bcrypt 项目迁移的账号库，``verify_password`` 在有 bcrypt
可用时会校验 ``$2a$/$2b$/$2y$`` 前缀的历史哈希；``needs_rehash`` 提示升级。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000
SALT_BYTES = 16


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    """生成口令哈希。"""
    if not isinstance(password, str) or not password:
        raise ValueError("password 不能为空")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """校验口令；格式非法或算法不支持时返回 False（不抛异常）。"""
    if not password or not stored:
        return False
    if stored.startswith(("$2a$", "$2b$", "$2y$")):
        return _verify_bcrypt(password, stored)
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = stored.split("$")
    except ValueError:
        return False
    if algorithm != ALGORITHM:
        return False
    try:
        iterations = int(iterations_raw)
        salt = _unb64(salt_raw)
        expected = _unb64(digest_raw)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _verify_bcrypt(password: str, stored: str) -> bool:
    """历史 bcrypt 哈希兼容校验（bcrypt 未安装时直接判定失败）。"""
    try:
        import bcrypt  # type: ignore
    except ImportError:
        return False
    try:
        return bool(bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8")))
    except (ValueError, TypeError):
        return False


def needs_rehash(stored: str) -> bool:
    """是否应升级哈希（bcrypt 迁移或迭代次数落后）。"""
    if not stored:
        return True
    if stored.startswith(("$2a$", "$2b$", "$2y$")):
        return True
    parts = stored.split("$")
    if len(parts) != 4 or parts[0] != ALGORITHM:
        return True
    try:
        return int(parts[1]) < ITERATIONS
    except ValueError:
        return True


def check_strength(password: str, *, min_length: int = 8) -> list[str]:
    """返回不满足的规则描述列表；空列表代表通过。"""
    problems: list[str] = []
    if len(password or "") < min_length:
        problems.append(f"长度至少 {min_length} 位")
    if not any(ch.isdigit() for ch in password or ""):
        problems.append("需包含数字")
    if not any(ch.isalpha() for ch in password or ""):
        problems.append("需包含字母")
    return problems


def generate_password(length: int = 12) -> str:
    """生成随机初始口令（管理员重置密码时使用）。"""
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(max(8, length)))


def hash_token(raw: str) -> str:
    """API Key 等长字符串凭证的不可逆摘要（P3 推送通道复用）。"""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()