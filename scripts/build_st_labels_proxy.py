"""从《上市公司基本信息年度表》的历年证券简称生成 ST 代理标签。

背景
----
CSMAR 镜像站当前账号能检索到《特殊处理变动文件》，但数据库返回“暂无数据”，
没有 P0-5《特别处理表》的下载权限。为了先跑通 ETL 与训练链路，本脚本用
`data/raw/basic_info.csv` 中每个公司-年末的 `ShortName` 是否以 `ST` / `*ST`
开头，构造“年末 ST 状态”代理标签，并同时输出一份可审计的代理事件表。

这不是官方 ST 事件表：
- 只反映**年末**状态，年内实施又在年内撤销的公司会漏标；
- 首次实施日期被近似为“首次观测到 ST 简称的年末”，不是交易所公告日；
- 数据截止 2025-12-31，因此 T-2 标签只能覆盖到 2025 年（特征年份到 2023）；
- 拿到 CSMAR《特别处理表》后，应直接用官方 `ST_events.csv` 覆盖本代理。

输出
----
- `data/incoming/csmar/ST_events_proxy.csv`：代理事件表（保留在 incoming，便于审计）
- `data/raw/ST_events.csv`：供 `etl.csmar_import --step labels` 读取的契约文件
- `data/raw/labels_st.csv`：完整 0/1 公司-年标签（覆盖财务主表全部 A 股键）

用法
----
    python -m scripts.build_st_labels_proxy --write
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

from config import settings
from etl.io_utils import get_logger, write_table

logger = get_logger("st-proxy")

# 沪深 A 股代码前缀；排除 B 股（200/900）、北交所（4/8/920）
A_SHARE_PREFIXES = {
    "000", "001", "002", "003",
    "300", "301",
    "600", "601", "603", "605", "688", "689",
}

# 2025 年报是当前数据截止点；代理标签不延伸到 2026
DATA_END_YEAR = 2025
RECORD_RE = re.compile(
    r'^\s*"?(?P<code>\d{6})"?\s*,\s*"?(?P<name>[^",]*)"?\s*,\s*"?(?P<date>\d{4}-\d{2}-\d{2})"?'
)


def _norm_name(value: str) -> str:
    """去掉简称中的空格，兼容 `*ST 国华` / `*ST国华`。"""
    return re.sub(r"\s+", "", str(value or "")).upper()


def _st_type(name: str) -> str:
    n = _norm_name(name)
    if n.startswith("*ST"):
        return "*ST"
    if n.startswith("ST"):
        return "ST"
    return ""


def read_basic_info(path: Path) -> pd.DataFrame:
    """逐行解析基本信息表。

    该 CSV 的 `BusinessScope` 等长文本字段含未转义换行，pandas 默认解析会把
    一条记录拆成多行；这里只取每条物理行开头的 `"代码","简称","日期"`，
    足以构造 ST 标签，且不会受后续字段错位影响。
    """
    rows: list[dict] = []
    bad = 0
    with path.open(encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            m = RECORD_RE.match(line)
            if not m:
                bad += 1
                continue
            code = m.group("code")
            if code[:3] not in A_SHARE_PREFIXES:
                continue
            rows.append({
                "stock_code": code,
                "company_name": m.group("name").strip(),
                "end_date": m.group("date"),
                "year": int(m.group("date")[:4]),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"{path} 未解析出任何 A 股年度记录")
    df = df.drop_duplicates(["stock_code", "year"], keep="last")
    logger.info("基本信息：解析 %d 条 A 股年度记录（跳过 %d 行非记录行），%d 家公司，%d-%d",
                len(df), bad, df["stock_code"].nunique(), df["year"].min(), df["year"].max())
    return df


def build_events(basic: pd.DataFrame) -> pd.DataFrame:
    """把年度 ST 状态压缩成 [实施年, 撤销年] 的连续区间。"""
    basic = basic.sort_values(["stock_code", "year"]).copy()
    basic["st_type"] = basic["company_name"].map(_st_type)
    basic["is_st"] = basic["st_type"].ne("")

    events: list[dict] = []
    for code, part in basic.groupby("stock_code", sort=True):
        part = part.sort_values("year")
        years = part["year"].tolist()
        flags = part["is_st"].tolist()
        names = part["company_name"].tolist()
        types = part["st_type"].tolist()
        i = 0
        while i < len(part):
            if not flags[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(part) and flags[j + 1] and years[j + 1] == years[j] + 1:
                j += 1
            start_year, end_year = years[i], years[j]
            spell_types = [t for t in types[i:j + 1] if t]
            st_type = "*ST" if "*ST" in spell_types else "ST"
            # 代理的撤销日取“最后一个观测到 ST 的年末”，避免把下一年误标为 ST
            revoke = f"{end_year}-12-31"
            if end_year >= DATA_END_YEAR:
                revoke = f"{DATA_END_YEAR}-12-31"
            events.append({
                "证券代码": code,
                "证券简称": names[i],
                "实施日期": f"{start_year}-12-31",
                "特别处理类型": st_type,
                "撤销日期": revoke,
                "公告日期": "",
                "数据来源": "CSMAR上市公司基本信息年度表-ShortName年末快照（代理）",
                "备注": "非官方ST事件表；实施/撤销日期为年末近似，拿到《特别处理表》后替换",
            })
            i = j + 1

    out = pd.DataFrame(events)
    logger.info("代理 ST 事件：%d 段，%d 家公司，%d-%d",
                len(out), out["证券代码"].nunique(),
                int(out["实施日期"].str[:4].min()), int(out["撤销日期"].str[:4].max()))
    return out


def build_labels(events: pd.DataFrame) -> pd.DataFrame:
    """以财务主表的公司-年为全集，生成完整 0/1 标签。"""
    fin = pd.read_csv(settings.RAW_FINANCIAL, dtype={"stock_code": str}, usecols=["stock_code", "year"])
    keys = fin.drop_duplicates().copy()
    keys["stock_code"] = keys["stock_code"].astype(str).str.zfill(6)
    keys["year"] = pd.to_numeric(keys["year"], errors="coerce").astype("Int64")
    keys = keys.dropna(subset=["year"])
    keys = keys[keys["stock_code"].str[:3].isin(A_SHARE_PREFIXES)]
    keys["year"] = keys["year"].astype(int)
    keys = keys[keys["year"].between(settings.RAW_YEAR_MIN if hasattr(settings, "RAW_YEAR_MIN") else 2013,
                                     DATA_END_YEAR)]
    keys = keys.drop_duplicates(["stock_code", "year"]).reset_index(drop=True)

    positive: set[tuple[str, int]] = set()
    for row in events.itertuples(index=False):
        code = str(getattr(row, "证券代码")).zfill(6)
        start = int(str(getattr(row, "实施日期"))[:4])
        end_raw = str(getattr(row, "撤销日期"))
        end = int(end_raw[:4]) if re.match(r"^\d{4}", end_raw) else DATA_END_YEAR
        end = min(end, DATA_END_YEAR)
        for year in range(start, end + 1):
            positive.add((code, year))

    keys["is_st"] = [1 if (c, y) in positive else 0 for c, y in zip(keys["stock_code"], keys["year"])]
    keys["label_source"] = "ST_events_proxy_shortname_yearend"
    logger.info("标签：%d 个公司-年，正样本 %d（%.2f%%），覆盖 %d-%d",
                len(keys), int(keys["is_st"].sum()), keys["is_st"].mean() * 100,
                int(keys["year"].min()), int(keys["year"].max()))
    return keys


def main() -> None:
    parser = argparse.ArgumentParser(description="用基本信息表证券简称生成 ST 代理标签")
    parser.add_argument("--write", action="store_true", help="写入 data/raw 与 data/incoming")
    parser.add_argument("--basic", default=str(settings.RAW_DIR / "basic_info.csv"))
    args = parser.parse_args()

    basic = read_basic_info(Path(args.basic))
    events = build_events(basic)
    labels = build_labels(events)

    if args.write:
        incoming = settings.DATA_DIR / "incoming" / "csmar"
        incoming.mkdir(parents=True, exist_ok=True)
        write_table(events, incoming / "ST_events_proxy.csv")
        write_table(events, settings.RAW_DIR / "ST_events.csv")
        write_table(labels, settings.RAW_LABELS)
        logger.info("已写入：%s、%s、%s",
                    settings.rel(incoming / "ST_events_proxy.csv"),
                    settings.rel(settings.RAW_DIR / "ST_events.csv"),
                    settings.rel(settings.RAW_LABELS))
    else:
        print(events.head(10).to_string())
        print(labels.groupby("year")["is_st"].agg(["size", "sum", "mean"]).to_string())


if __name__ == "__main__":
    main()
