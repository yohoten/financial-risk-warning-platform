"""技能库：可复用的任务指令模板（移植自旧项目，sqlite3 持久化）。

Agent 集成方式（保持 system 提示词静态 → 缓存友好）：
- system 提示词里只写一句"可用 list_skills / load_skill 获取专门方法"
- 技能全文通过工具结果注入，不污染静态前缀
"""

from __future__ import annotations

from api.db import execute, query

BUILTIN_SKILLS = [
    {
        "name": "企业风险评估报告",
        "description": "对指定企业输出一份结构化风险评估报告（含六维评分、证据链、结论与建议）",
        "content": """# 企业风险评估报告

按以下步骤执行：
1. 用 `search_enterprise` 定位企业，拿到 stock_code；
2. 用 `get_score_profile` 取六维评分与评级；
3. 用 `get_risk_facts` 取风险事实（至少覆盖得分最低的两个维度）；
4. 输出报告，结构固定：

## 一、企业概况
（名称、行业、数据来源）

## 二、风险评级
综合评分 / 评级（AAA~C）/ 风险等级，并说明数据完整度

## 三、六维评分
逐维列出分数与一句话依据（数据不足的维度要如实标注）

## 四、关键风险点
按严重程度排序，每条附证据来源与时间

## 五、处置建议
2~4 条可执行动作，区分"立即处理"与"持续监控"

要求：只使用工具返回的数据；结尾注明"数据来自公开信源，不构成投资建议"。""",
    },
    {
        "name": "多企业对比分析",
        "description": "对比 2~3 家企业的六维评分、风险等级与关键差异，给出选择建议",
        "content": """# 多企业对比分析

1. 对每家企业依次 `search_enterprise` → `get_score_profile`；
2. 用表格对比：企业 | 综合评分 | 评级 | 财务 | 法律 | 舆情 | 经营 | 信用 | 供应链；
3. 指出差异最大的两个维度，并解释原因（引用证据）；
4. 结论：哪家更稳健、哪家需要重点监控，各给一条建议。

注意：评分缺失（gray）的维度要标注"数据不足"，不要当成满分或零分。""",
    },
    {
        "name": "预警处置建议",
        "description": "针对预警工单给出处置方案与跟踪建议",
        "content": """# 预警处置建议

1. `list_alerts` 找到目标预警（按企业或状态筛选）；
2. 阅读该预警的证据链与处置流水；
3. 输出：
   - 风险性质判断（是实质性风险还是数据噪音）
   - 需要核实的 2~3 个关键事实
   - 处置动作建议（含责任岗位、时限）
   - 后续跟踪指标与复评时间点
4. 如用户确认要处置，调用 `handle_alert`（需授权）记录处置。""",
    },
    {
        "name": "舆情专项研判",
        "description": "聚焦舆情声誉维度，分析负面舆情来源、趋势与影响",
        "content": """# 舆情专项研判

1. `search_enterprise` → `get_risk_facts`（dimension=news）取舆情事实；
2. 归类负面舆情：合规监管 / 经营业绩 / 产品质量 / 劳资关系 / 资本市场；
3. 判断传播趋势（是否集中爆发、是否有权威媒体介入）；
4. 输出：舆情风险等级、需重点关注的 3 条报道（附来源）、对外沟通与应对建议。""",
    },
    {
        "name": "财务分析",
        "description": "用金融分析模块做财报分析：KPI、杜邦分解、Z/F/M 模型、同业对标、异常勾稽",
        "content": """# 财务分析

## 取数顺序
1. `search_enterprise` 定位企业，拿到 stock_code；
2. `get_financial_analysis(stock_code)` 一次拿全：KPI、杜邦分解、Altman Z/Z''、Piotroski F、Beneish M、同业分位、异常信号；
3. 若返回 `available=false`：说明该企业无公开财报（非上市或未采集），提示用户可用 `refresh_enterprise_data`（写操作，需授权）拉取，或确认股票代码；
4. 需要横向比较时用 `compare_financials`；需要按指标筛选用 `screen_by_financial_metric`。

## 输出结构（固定）
## 一、结论摘要
3~5 条，先给判断（健康/承压/高风险），每条附关键数字与年份。
## 二、盈利与成长
营收/归母净利润/毛利率/净利率/ROE 的水平值与同比方向，指出趋势拐点。
## 三、杜邦分解
ROE = 净利率 × 总资产周转率 × 权益乘数，说明最近一期变动主要由哪个因素驱动。
## 四、财务预警模型
- Altman Z''（账面口径）：分数 + 区间（>2.6 安全 / 1.1~2.6 灰色 / <1.1 困境）；
- Altman Z（市值口径）：如无市值数据则明确写"不可计算"；
- Piotroski F-Score：得分 x/9，列出未通过项；
- Beneish M-Score：分数 + 是否 > -1.78，并注明含近似项（若有）。
## 五、异常信号
逐条列 anomalies：标题 + 具体数字 + 可能原因 + 需核实材料。
## 六、同业对标
关键指标在可比企业中的分位（≥75% 为优势，≤25% 为劣势）。
## 七、数据说明
覆盖期数、缺失指标、口径提示。

## 硬性要求
- 数字必须来自工具返回，标注年份与单位（万元/%/倍/天）；
- 缺失数据写"数据不足"，不得用 0 或行业均值替代；
- 模型分数必须同时给阈值，避免只给结论；
- 结尾注明"数据来自公开信源，模型结果为规则化测算，不构成投资建议"。""",
    },
]


def seed_builtin() -> int:
    created = 0
    for item in BUILTIN_SKILLS:
        if query("SELECT id FROM skill WHERE name = ?", (item["name"],)):
            continue
        execute("INSERT INTO skill (name, description, content, builtin, enabled) VALUES (?, ?, ?, 1, 1)",
               (item["name"], item["description"], item["content"]))
        created += 1
    return created


def list_skills(enabled_only: bool = False) -> dict:
    sql = "SELECT * FROM skill" + (" WHERE enabled = 1" if enabled_only else "") + " ORDER BY builtin DESC, id"
    rows = query(sql)
    return {"total": len(rows), "items": [
        {"id": r["id"], "name": r["name"], "description": r["description"], "content": r["content"],
         "enabled": bool(r["enabled"]), "builtin": bool(r["builtin"]), "updated_at": r["updated_at"]}
        for r in rows
    ]}


def get_skill(skill_id: int) -> dict | None:
    rows = query("SELECT * FROM skill WHERE id = ?", (skill_id,))
    return rows[0] if rows else None


def get_by_name(name: str) -> dict | None:
    rows = query("SELECT * FROM skill WHERE name = ?", (name,))
    return rows[0] if rows else None


def create_skill(name: str, description: str, content: str) -> dict:
    name = (name or "").strip()
    if not name or not (content or "").strip():
        return {"error": "技能名称与内容不能为空"}
    if query("SELECT id FROM skill WHERE name = ?", (name,)):
        return {"error": f"技能已存在：{name}"}
    skill_id = execute("INSERT INTO skill (name, description, content) VALUES (?, ?, ?)",
                      (name, description or "", content))
    return {"skill_id": skill_id, "name": name}


def update_skill(skill_id: int, **fields) -> dict:
    row = get_skill(skill_id)
    if row is None:
        return {"error": f"技能不存在: {skill_id}"}
    vals = {
        "name": fields.get("name") or row["name"],
        "description": fields.get("description") if fields.get("description") is not None else row["description"],
        "content": fields.get("content") if fields.get("content") is not None else row["content"],
        "enabled": int(bool(fields["enabled"])) if fields.get("enabled") is not None else row["enabled"],
    }
    execute("UPDATE skill SET name=?, description=?, content=?, enabled=?, updated_at=datetime('now','localtime') WHERE id=?",
           (vals["name"], vals["description"], vals["content"], vals["enabled"], skill_id))
    return {"ok": True, "skill_id": skill_id}


def delete_skill(skill_id: int) -> dict:
    row = get_skill(skill_id)
    if row is None:
        return {"error": f"技能不存在: {skill_id}"}
    if row["builtin"]:
        return {"error": "内置技能不可删除，可将其停用"}
    execute("DELETE FROM skill WHERE id = ?", (skill_id,))
    return {"deleted": skill_id, "name": row["name"]}


def skills_for_tool() -> list[dict]:
    rows = query("SELECT name, description FROM skill WHERE enabled = 1 ORDER BY id")
    return [{"name": r["name"], "description": r["description"]} for r in rows]
