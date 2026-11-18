"""首次运行灌入内置技能与 Agent 预设（幂等）。

上市企业清单由金融分析面板（panel_clean.parquet）提供，本模块只负责
「技能库 + 预设」这类平台配置数据；非上市企业由用户经 P6 表格手动建档。
"""

from __future__ import annotations

from api.db import init_db


def seed_builtin() -> dict:
    """灌入内置技能与预设；幂等。"""
    init_db()
    from api.services import plugins, skills

    created_skills = skills.seed_builtin()
    created_presets = plugins.seed_builtin_presets()
    return {"skills": created_skills, "presets": created_presets}


if __name__ == "__main__":
    print(seed_builtin())
