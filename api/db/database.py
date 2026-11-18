"""平台业务库（标准库 sqlite3，stock_code 主键）。

设计约定（沿用 api/services/alerts.py 的做法，不引入 SQLAlchemy）：
- 单库文件落在可写目录 ``settings.CACHE_DIR / "platform.db"``；
  桌面端打包形态下 CACHE_DIR 已被重定向到用户数据目录，避免写只读安装目录。
- 每操作独立连接 + ``sqlite3.Row``，不持有全局 session；WAL 模式提升并发读。
- 主键统一 6 位字符串 ``stock_code``（非上市企业使用 ``M`` 前缀合成码）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from config import settings

DB_PATH: Path = settings.CACHE_DIR / "platform.db"

_SCHEMA: tuple[str, ...] = (
    # 企业档案（用户添加 + 数据状态快照）
    """
    CREATE TABLE IF NOT EXISTS enterprise (
        stock_code      TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        industry        TEXT DEFAULT '',
        unified_code    TEXT DEFAULT '',
        legal_rep       TEXT DEFAULT '',
        reg_capital_wan REAL DEFAULT 0,
        reg_date        TEXT DEFAULT '',
        address         TEXT DEFAULT '',
        data_note       TEXT DEFAULT '',
        data_status_json TEXT DEFAULT '{}',
        created_at      TEXT DEFAULT (datetime('now','localtime')),
        updated_at      TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
    # 手工导入/表格入库的财务数据（与 finance.py 面板数据互补）
    """
    CREATE TABLE IF NOT EXISTS finance (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code    TEXT NOT NULL,
        year          TEXT DEFAULT '',
        report_type   TEXT DEFAULT '',
        total_assets  REAL DEFAULT 0,
        total_liabilities REAL DEFAULT 0,
        revenue       REAL DEFAULT 0,
        net_profit    REAL DEFAULT 0,
        debt_ratio    REAL DEFAULT 0,
        source        TEXT DEFAULT '',
        metrics_json  TEXT DEFAULT '{}'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_code ON finance(stock_code)
    """,
    """
    CREATE TABLE IF NOT EXISTS legal_record (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code TEXT NOT NULL,
        case_no TEXT DEFAULT '',
        doc_type TEXT DEFAULT '',
        title TEXT DEFAULT '',
        court TEXT DEFAULT '',
        cause TEXT DEFAULT '',
        amount REAL DEFAULT 0,
        status TEXT DEFAULT '',
        judgment_date TEXT DEFAULT '',
        source TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code TEXT NOT NULL,
        title TEXT DEFAULT '',
        content TEXT DEFAULT '',
        source TEXT DEFAULT '',
        url TEXT DEFAULT '',
        published_at TEXT DEFAULT '',
        sentiment TEXT DEFAULT 'neutral'
    )
    """,
    # 风险信号事实（LLM 研判/规则产出，供证据引用）
    """
    CREATE TABLE IF NOT EXISTS risk_fact (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code TEXT NOT NULL,
        dimension TEXT DEFAULT '',
        text TEXT NOT NULL,
        evidence_json TEXT DEFAULT '',
        confidence REAL DEFAULT 0,
        ts TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
    # 对话会话与消息
    """
    CREATE TABLE IF NOT EXISTS chat_session (
        id TEXT PRIMARY KEY,
        title TEXT DEFAULT '新对话',
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime')),
        summary TEXT DEFAULT '',
        compacted_until INTEGER DEFAULT 0,
        compact_count INTEGER DEFAULT 0,
        pinned INTEGER DEFAULT 0,
        share_token TEXT DEFAULT '',
        share_created_at TEXT DEFAULT '',
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        cache_hit_tokens INTEGER DEFAULT 0,
        cache_miss_tokens INTEGER DEFAULT 0,
        llm_calls INTEGER DEFAULT 0,
        est_cost REAL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_message (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT DEFAULT '',
        tool_calls_json TEXT DEFAULT '',
        tool_call_id TEXT DEFAULT '',
        tool_name TEXT DEFAULT '',
        ts TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chat_message_session ON chat_message(session_id)
    """,
    # 外部 MCP 服务
    """
    CREATE TABLE IF NOT EXISTS mcp_server (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        url TEXT NOT NULL,
        auth_header TEXT DEFAULT '',
        enabled INTEGER DEFAULT 1,
        require_approval INTEGER DEFAULT 0,
        status TEXT DEFAULT 'unknown',
        status_detail TEXT DEFAULT '',
        tools_json TEXT DEFAULT '[]',
        tool_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        synced_at TEXT DEFAULT ''
    )
    """,
    # 技能库
    """
    CREATE TABLE IF NOT EXISTS skill (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT DEFAULT '',
        content TEXT DEFAULT '',
        enabled INTEGER DEFAULT 1,
        builtin INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
    # 手搓插件（声明式 HTTP 工具）
    """
    CREATE TABLE IF NOT EXISTS custom_tool (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT DEFAULT '',
        parameters_json TEXT DEFAULT '{}',
        method TEXT DEFAULT 'GET',
        url TEXT DEFAULT '',
        headers_json TEXT DEFAULT '{}',
        body_template TEXT DEFAULT '',
        enabled INTEGER DEFAULT 1,
        require_approval INTEGER DEFAULT 0,
        builtin INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
    # Agent 预设
    """
    CREATE TABLE IF NOT EXISTS agent_preset (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT DEFAULT '',
        prompt_extra TEXT DEFAULT '',
        tools_json TEXT DEFAULT '[]',
        skills_json TEXT DEFAULT '[]',
        model_override TEXT DEFAULT '',
        enabled INTEGER DEFAULT 1,
        builtin INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
    # 设置面板覆盖（DB 覆盖热生效）
    """
    CREATE TABLE IF NOT EXISTS app_setting (
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT '',
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
    # P6 表格对象（draft → confirmed → ingested），整表以 JSON 存储（对齐 Rust table_doc）
    """
    CREATE TABLE IF NOT EXISTS table_doc (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code TEXT DEFAULT '',
        title TEXT DEFAULT '',
        kind TEXT DEFAULT 'blank',
        unit TEXT DEFAULT '万元',
        scope TEXT DEFAULT '合并报表',
        period_type TEXT DEFAULT '年报',
        currency TEXT DEFAULT 'CNY',
        sheet_json TEXT DEFAULT '{}',
        mapping_json TEXT DEFAULT '{}',
        macro_json TEXT DEFAULT '[]',
        status TEXT DEFAULT 'draft',
        version INTEGER DEFAULT 1,
        origin TEXT DEFAULT 'manual',
        note TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_table_doc_stock ON table_doc(stock_code)
    """,
    # P6 多模态附件（内容寻址去重）
    """
    CREATE TABLE IF NOT EXISTS attachment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sha256 TEXT UNIQUE NOT NULL,
        name TEXT DEFAULT '',
        mime TEXT DEFAULT '',
        size INTEGER DEFAULT 0,
        path TEXT DEFAULT '',
        kind TEXT DEFAULT 'image',
        reading_json TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
)


# ---------------------------------------------------------------------------
# P1 认证与权限域（对齐设计稿 §4.2；服务端 PostgreSQL 形态同构，P2 由 Alembic 接管）
# ---------------------------------------------------------------------------
AUTH_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS user (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        email TEXT DEFAULT '',
        hashed_password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'viewer',
        is_active INTEGER NOT NULL DEFAULT 1,
        password_version INTEGER NOT NULL DEFAULT 1,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT DEFAULT '',
        last_login_at TEXT DEFAULT '',
        must_change_password INTEGER NOT NULL DEFAULT 0,
        note TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_role ON user(role)
    """,
    # 令牌撤销表（单机 SQLite 形态；服务端 P4 换 Redis，此表作持久兜底）
    """
    CREATE TABLE IF NOT EXISTS revoked_token (
        jti TEXT PRIMARY KEY,
        user_id TEXT DEFAULT '',
        kind TEXT DEFAULT 'access',
        expires_at INTEGER NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_revoked_exp ON revoked_token(expires_at)
    """,
    # 审计日志（移植 ZNCBZS core/security.log_operation + models/operation_log）
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT DEFAULT '',
        username TEXT DEFAULT '',
        action TEXT NOT NULL,
        resource TEXT DEFAULT '',
        method TEXT DEFAULT '',
        path TEXT DEFAULT '',
        ip TEXT DEFAULT '',
        ua TEXT DEFAULT '',
        status INTEGER DEFAULT 0,
        latency_ms INTEGER DEFAULT 0,
        detail_json TEXT DEFAULT '{}',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)
    """,
    # 关注清单（数据范围隔离：自选企业归属）
    """
    CREATE TABLE IF NOT EXISTS user_enterprise (
        user_id TEXT NOT NULL,
        stock_code TEXT NOT NULL,
        note TEXT DEFAULT '',
        added_at TEXT DEFAULT (datetime('now','localtime')),
        PRIMARY KEY (user_id, stock_code)
    )
    """,
)


# ---------------------------------------------------------------------------
# P3 数据实时接入域（对齐设计稿 §4.2；机器推送 / API Key / 接入日志 / 暂存）
# ---------------------------------------------------------------------------
INGEST_SCHEMA: tuple[str, ...] = (
    # 数据源配置（把 datasources.py 硬编码注册表变为可管理配置）
    """
    CREATE TABLE IF NOT EXISTS data_source_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dimension TEXT NOT NULL,
        source_name TEXT NOT NULL,
        label TEXT DEFAULT '',
        enabled INTEGER DEFAULT 1,
        priority INTEGER DEFAULT 0,
        merge_mode TEXT DEFAULT 'fallback',
        schedule_cron TEXT DEFAULT '',
        config_json TEXT DEFAULT '{}',
        updated_by TEXT DEFAULT '',
        updated_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(dimension, source_name)
    )
    """,
    # API Key（机器推送通道凭证；只存 SHA256，明文仅签发时返回一次）
    """
    CREATE TABLE IF NOT EXISTS api_key (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        key_hash TEXT UNIQUE NOT NULL,
        scopes TEXT NOT NULL DEFAULT 'ingest:*',
        created_by TEXT DEFAULT '',
        expires_at TEXT DEFAULT '',
        last_used_at TEXT DEFAULT '',
        revoked INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
    # 接入日志（移植 ZNCBZS TaskExecutionLog 落库语义）
    """
    CREATE TABLE IF NOT EXISTS ingest_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task TEXT DEFAULT '',
        channel TEXT DEFAULT 'push',
        trigger_by TEXT DEFAULT '',
        dimension TEXT DEFAULT '',
        stock_code TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        inserted INTEGER DEFAULT 0,
        updated INTEGER DEFAULT 0,
        error TEXT DEFAULT '',
        detail_json TEXT DEFAULT '{}',
        started_at TEXT DEFAULT (datetime('now','localtime')),
        finished_at TEXT DEFAULT ''
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ingest_log_status ON ingest_log(status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ingest_log_started ON ingest_log(started_at)
    """,
    # 推送暂存区（落地-暂存-契约 三层治理；幂等键 batch_id+dimension+stock_code）
    """
    CREATE TABLE IF NOT EXISTS ingest_staging (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT NOT NULL,
        dimension TEXT NOT NULL,
        stock_code TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        quality_pass INTEGER DEFAULT 0,
        quality_msg TEXT DEFAULT '',
        consumed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(batch_id, dimension, stock_code)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_staging_consumed ON ingest_staging(consumed, dimension)
    """,
)


def get_conn() -> sqlite3.Connection:
    """新建一个连接（WAL + 外键关闭，事务由调用方控制）。"""
    settings.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db() -> None:
    """建表（幂等）。"""
    conn = get_conn()
    try:
        with conn:
            for ddl in (*_SCHEMA, *AUTH_SCHEMA, *INGEST_SCHEMA):
                conn.execute(ddl)
    finally:
        conn.close()


def query(sql: str, params: tuple = ()) -> list[dict]:
    """执行查询，返回 dict 列表。"""
    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()) -> int:
    """执行写操作，返回 lastrowid。"""
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(sql, params)
            return int(cur.lastrowid or 0)
    finally:
        conn.close()
