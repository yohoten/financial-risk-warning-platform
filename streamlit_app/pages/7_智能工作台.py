"""🧠 智能工作台：Agent 对话 / 技能库 / 预设 / MCP / 表格对象 概览与配置。

完整流式对话请使用 Vue 大屏的「智能工作台」（支持 SSE 流式 + 工具调用 + 动作授权）。
本页提供 Streamlit 侧的只读概览与 LLM 配置入口，方便离线演示与快速体检。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from streamlit_app.components.layout import page_header
from streamlit_app.utils.styles import footer, setup_page

setup_page("智能工作台", "🧠")
page_header("智能工作台", "Agent 对话 · 技能库 · Agent 预设 · MCP 服务 · 表格对象", "🧠")

from api.db import init_db, query  # noqa: E402
from api.services import skills, plugins, settings_store  # noqa: E402

init_db()

st.caption("提示：流式对话请在 Web 大屏「智能工作台」中使用；本页为 Streamlit 侧概览与配置。")

t1, t2, t3 = st.tabs(["🤖 配置", "🧩 技能与预设", "🔌 MCP 与表格"])

with t1:
    view = settings_store.get_view()
    runtime = view["runtime"]
    st.markdown(f"**当前模型**：`{runtime['model'] or '未配置'}` · 端点 `{runtime['base_url'] or '未配置'}`")
    st.caption("在 Web 工作台「设置」面板配置 API 地址 / Key / 模型，保存即热生效。")
    with st.expander("提供商预设"):
        for p in view["providers"]:
            st.markdown(f"- **{p['label']}**：`{p['base_url']}`（默认模型 `{p['default_model']}`）")

with t2:
    sk = skills.list_skills()
    st.markdown(f"**技能库（{sk['total']}）**")
    for s in sk["items"]:
        st.markdown(f"- **{s['name']}**：{s['description']}" + ("（内置）" if s["builtin"] else ""))
    pr = plugins.list_presets()
    st.markdown(f"**Agent 预设（{pr['total']}）**")
    for p in pr["items"]:
        st.markdown(f"- **{p['name']}**：{p['description']}" + ("（内置）" if p["builtin"] else ""))

with t3:
    try:
        from api.mcp import service as mcp_svc
        servers = mcp_svc.list_servers()
        st.markdown(f"**MCP 服务（{servers['total']}）**")
        for s in servers["items"]:
            st.markdown(f"- **{s['name']}**：{s['url']}（{s['status']}，{s['tool_count']} 工具）")
    except Exception as exc:  # noqa: BLE001
        st.caption(f"MCP 读取失败：{exc}")

    tabs = query("SELECT id, stock_code, title, kind, unit, status FROM table_doc ORDER BY updated_at DESC LIMIT 20")
    st.markdown(f"**表格对象（{len(tabs)}）**")
    for t in tabs:
        st.markdown(f"- #{t['id']} **{t['title']}** · `{t['stock_code'] or '未绑定'}` · {t['unit']} · {t['status']}")

footer()
