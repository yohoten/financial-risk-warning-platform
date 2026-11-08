"""页面级布局组件。"""

from __future__ import annotations

import streamlit as st


def page_header(title: str, subtitle: str, icon: str = "") -> None:
    st.markdown(f"### {icon} {title}".strip())
    st.caption(subtitle)
    st.markdown("")


def kpi_row(items: list[dict]) -> None:
    """一行 KPI 卡片。items 支持 label/value/delta/help。"""
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        col.metric(
            label=item["label"],
            value=item["value"],
            delta=item.get("delta"),
            help=item.get("help"),
        )


def download_button(label: str, data: bytes, filename: str, mime: str, key: str | None = None) -> None:
    st.download_button(label, data=data, file_name=filename, mime=mime, key=key, use_container_width=False)
