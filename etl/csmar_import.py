"""CSMAR 原始分表导出 → 项目 raw 契约（真实数据接入层）。

与 `etl.mapping` 的分工：`etl.mapping` 面向「已是合约列名」的合并表；
本模块面向 CSMAR 原始导出（科目代码 A001000000 这类），负责解码、过滤、合并、换算。

口径（与 docs/CSMAR手动下载清单.md 一致）：
1. 只保留合并报表（Typrep=A）+ 年报（Accper 以 -12-31 结尾）；
2. 金额 元 → 亿元（1e-8），股本 股 → 亿股；
3. 同一公司-年多条（追溯调整）保留最新公告日期；
4. 剔除 J/K/S 三个行业门类；
5. 缺失科目留空，由 ETL 统一插补，不在导入层臆造。

用法：
    python -m etl.csmar_import --step list             # 查看科目代码映射
    python -m etl.csmar_import --step financial        # 只演练，不写盘
    python -m etl.csmar_import --step all --write      # 写 data/raw 契约表
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from config import settings
from etl.io_utils import get_logger, write_table

logger = get_logger("csmar-import")

YEAR_MIN, YEAR_MAX = 2013, 2026
EXCLUDE_PREFIX = ("J", "K", "S")
KEY = ["stock_code", "year"]

# 沪深 A 股代码前缀；排除 B 股（200/900）与北交所（4/8/920）。
# 财务主表当前混有这些代码，标签阶段在这里统一收口，避免 B 股重复样本被误标为 0。
A_SHARE_PREFIXES = {
    "000", "001", "002", "003",
    "300", "301",
    "600", "601", "603", "605", "688", "689",
}
DEMO_BACKUP = settings.DATA_DIR / "demo_raw"

BALANCE_CODES = {
    "A001000000": "total_assets", "A002000000": "total_liabilities", "A003000000": "equity",
    "A001100000": "current_assets", "A002100000": "current_lia", "A001123000": "inventory",
    "A001101000": "cash", "A001111000": "receivables", "A002108000": "payable",
    "A001212000": "fixed_assets", "A002101000": "short_borrow", "A002201000": "lt_debt",
    "A002203000": "bonds_payable", "A002125000": "current_lt_debt",
    "A003101000": "paid_in_capital",
}

INCOME_CODES = {
    "B001101000": "revenue", "B001201000": "cost", "B001209000": "sell_exp",
    "B001210000": "admin_exp", "B001211000": "fin_exp", "B001211101": "interest_exp",
    "B001000000": "ebit", "B002000000": "net_profit", "B002000101": "net_profit_parent",
    "B001216000": "rd_expense",
}

CASHFLOW_FIELDS = ["ocf", "icf", "fcf_financing", "capex"]
INST_PREFIX = "P22"
BIG4_KEYWORDS = ("普华永道", "德勤", "安永", "毕马威", "PwC", "Deloitte", "Ernst", "KPMG")

AMOUNT_COLS = [
    "total_assets", "total_liabilities", "equity", "current_assets", "current_lia",
    "inventory", "cash", "receivables", "payable", "fixed_assets", "short_borrow",
    "lt_debt", "bonds_payable", "current_lt_debt", "revenue", "cost", "sell_exp",
    "admin_exp", "fin_exp", "interest_exp", "ebit", "net_profit", "net_profit_parent",
    "rd_expense", "opex", "interest_expense", "interest_debt", "ocf", "icf",
    "fcf_financing", "capex",
]


def _codes() -> dict[str, str]:
    """返回代码 → 项目字段的完整映射（用于 --list）。"""
    return {**BALANCE_CODES, **INCOME_CODES, **{c: c for c in CASHFLOW_FIELDS}}


def _read_statement(path: Path, code_map: dict[str, str]) -> pd.DataFrame:
    """读取财报 CSV：按代码取列 → 过滤合并报表/年报 → 去重 → 转数值。"""
    if not path.exists():
        raise FileNotFoundError(f"缺少源文件：{settings.rel(path)}")
    header = pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns
    wanted = [c for c in ["Stkcd", "ShortName", "Accper", "Typrep", "DeclareDate"] if c in header]
    usecols = wanted + [c for c in code_map if c in header]
    missing = [c for c in code_map if c not in header]
    if missing:
        logger.warning("%s 缺少科目 %d 个：%s", path.name, len(missing), missing[:5])

    frames = []
    for chunk in pd.read_csv(path, usecols=usecols, dtype=str, encoding="utf-8-sig",
                             chunksize=200_000, low_memory=False):
        chunk["Accper"] = chunk["Accper"].astype(str).str.strip()
        year = chunk["Accper"].str[:4]
        mask = (
            chunk["Typrep"].astype(str).str.upper().eq("A")
            & chunk["Accper"].str.endswith("-12-31")
            & year.str.isdigit() & year.astype(int).between(YEAR_MIN, YEAR_MAX)
        )
        sub = chunk.loc[mask].copy()
        if sub.empty:
            continue
        sub["year"] = year[mask].astype(int)
        frames.append(sub)

    if not frames:
        raise ValueError(f"{path.name} 过滤后为空")
    df = pd.concat(frames, ignore_index=True)
    df["stock_code"] = df["Stkcd"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    df["declare_date"] = pd.to_datetime(df.get("DeclareDate"), errors="coerce")
    df = df.rename(columns={k: v for k, v in code_map.items() if k in df.columns})
    value_cols = [c for c in code_map.values() if c in df.columns]
    for col in value_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = (df.sort_values([*KEY, "declare_date"])
            .drop_duplicates(KEY, keep="last"))
    keep = [c for c in ["stock_code", "year", "company_name", *value_cols] if c in df.columns]
    out = df[keep].reset_index(drop=True)
    logger.info("%s：%d 行，%d 家公司，年份 %d-%d", path.name, len(out),
                out["stock_code"].nunique(), out["year"].min(), out["year"].max())
    return out


def load_basic_info() -> pd.DataFrame:
    """基本信息年度表 → 公司简称 / 行业代码 / 上市日期。"""
    path = settings.RAW_DIR / "basic_info.csv"
    if not path.exists():
        logger.warning("缺少 basic_info.csv，行业字段将为空")
        return pd.DataFrame(columns=[*KEY, "company_name", "industry", "listing_date"])
    header = pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns
    usecols = [c for c in ["Symbol", "ShortName", "EndDate", "IndustryCodeC", "IndustryCode", "LISTINGDATE"] if c in header]
    frames = []
    for chunk in pd.read_csv(path, usecols=usecols, dtype=str, encoding="utf-8-sig",
                             chunksize=300_000, low_memory=False):
        chunk["year"] = pd.to_numeric(chunk["EndDate"].astype(str).str[:4], errors="coerce")
        frames.append(chunk[chunk["year"].between(YEAR_MIN - 3, YEAR_MAX + 1)])
    df = pd.concat(frames, ignore_index=True)
    df["stock_code"] = df["Symbol"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    df["year"] = df["year"].astype(int)
    industry = df.get("IndustryCodeC")
    df["industry"] = industry.where(industry.notna(), df.get("IndustryCode"))
    df = df.rename(columns={"ShortName": "company_name", "LISTINGDATE": "listing_date"})
    df = df.sort_values(KEY).drop_duplicates(KEY, keep="last")
    out = df[[c for c in [*KEY, "company_name", "industry", "listing_date"] if c in df.columns]].reset_index(drop=True)
    logger.info("基本信息：%d 行，%d 家公司，%d 个行业", len(out), out["stock_code"].nunique(),
                out["industry"].nunique())
    return out


def _load_cashflow() -> pd.DataFrame:
    """现金流量表：读取 XLSX 流式转换结果。

    兼容两种输出：
    - 新格式（9 列，csv 规范转义）：直接按列读取；
    - 旧格式（公司简称含逗号导致列数漂移）：按「前 3 列 + 后 4 列」容错解析，
      因为 ocf/icf/fcf_financing/capex 永远在行尾。
    """
    import csv

    for path in (settings.RAW_DIR / "FS_Comscfd_filtered.csv",
                 settings.DATA_DIR / "incoming" / "csmar" / "FS_Comscfd_filtered.csv"):
        if not path.exists():
            continue
        rows = []
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            next(reader, None)
            for fields in reader:
                if len(fields) < 7:
                    continue
                code, accper, typrep = fields[0].strip(), fields[1].strip(), fields[2].strip().upper()
                if typrep != "A" or not accper.endswith("-12-31"):
                    continue
                year = accper[:4]
                if not year.isdigit():
                    continue
                values = fields[-4:]
                rows.append([code, int(year), *values])
        df = pd.DataFrame(rows, columns=[*KEY, *CASHFLOW_FIELDS])
        df["stock_code"] = df["stock_code"].astype(str).str.zfill(6)
        # 注意：这里只做数值化，不做单位换算。
        # `build_financial` 会对 AMOUNT_COLS 统一执行一次 元→亿元（1e-8）；
        # 若此处再乘 1e-8，现金流量表会被缩放两次（历史 bug）。
        for col in CASHFLOW_FIELDS:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df[df["year"].between(YEAR_MIN, YEAR_MAX)].drop_duplicates(KEY, keep="last")
        logger.info("现金流量表：%d 行（%s）", len(df), path.name)
        return df
    logger.warning("未找到 FS_Comscfd_filtered.csv，ocf/icf/capex 留空")
    return pd.DataFrame(columns=[*KEY, *CASHFLOW_FIELDS])


def _safe_write(df: pd.DataFrame, target: Path) -> Path:
    """首次覆盖真实数据前，把演示数据备份到 data/demo_raw/。"""
    if target.exists() and not DEMO_BACKUP.exists():
        DEMO_BACKUP.mkdir(parents=True, exist_ok=True)
        for old in settings.RAW_DIR.glob("csmar_*.csv"):
            shutil.copy2(old, DEMO_BACKUP / old.name)
        logger.info("已备份原有 raw 文件到 %s", settings.rel(DEMO_BACKUP))
    return write_table(df, target)


def build_financial(write: bool = False) -> pd.DataFrame:
    bas = _read_statement(settings.RAW_DIR / "FS_Combas.csv", BALANCE_CODES)
    ins = _read_statement(settings.RAW_DIR / "FS_Comins.csv", INCOME_CODES)
    cf = _load_cashflow()
    basic = load_basic_info()

    merged = bas.merge(ins.drop(columns=["company_name"], errors="ignore"), on=KEY, how="outer")
    merged = merged.merge(cf, on=KEY, how="outer").merge(basic, on=KEY, how="left")

    # 行业/简称在基本信息表中个别年份缺行：先按公司前后向填充，再兜底为 UNKNOWN
    for col in ("industry", "company_name"):
        if col in merged.columns:
            merged[col] = merged.groupby("stock_code")[col].transform(lambda s: s.ffill().bfill())
    merged["industry"] = merged["industry"].fillna("UNKNOWN").astype(str)

    merged["opex"] = merged[["sell_exp", "admin_exp", "fin_exp"]].sum(axis=1, min_count=1)
    merged["interest_expense"] = merged["interest_exp"].where(
        merged["interest_exp"].notna(), merged["fin_exp"])
    merged["interest_debt"] = merged[["short_borrow", "lt_debt", "bonds_payable",
                                      "current_lt_debt"]].sum(axis=1, min_count=1)
    merged["total_shares"] = merged["paid_in_capital"] / 1e8       # 元 → 亿股
    merged["eps"] = merged["net_profit"] / merged["total_shares"]  # 元/股
    # 审计费用从审计意见表回填（特征 audit_fee_ratio 依赖该列）
    audit = _read_audit()
    if not audit.empty:
        merged = merged.merge(audit[[*KEY, "audit_fee"]], on=KEY, how="left")

    # 需 P1/P2 表补齐的字段，先留空
    for col in ("deducted_profit", "depreciation"):
        merged[col] = pd.NA
    if "audit_fee" not in merged.columns:
        merged["audit_fee"] = pd.NA

    for col in AMOUNT_COLS:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce") * 1e-8  # 元 → 亿元

    before = len(merged)
    merged = merged[~merged["industry"].astype(str).str[:1].isin(EXCLUDE_PREFIX)]
    logger.info("剔除 J/K/S 行业：%d → %d 行", before, len(merged))

    contract = [*KEY[:1], "company_name", "industry", "year", *AMOUNT_COLS, "total_shares",
                "eps", "deducted_profit", "depreciation", "audit_fee"]
    out = merged[[c for c in dict.fromkeys(contract) if c in merged.columns]]
    out = out.dropna(subset=KEY).sort_values(KEY).reset_index(drop=True)
    logger.info("财务主表：%d 行 × %d 列，%d 家公司，年份 %d-%d", len(out), out.shape[1],
                out["stock_code"].nunique(), out["year"].min(), out["year"].max())
    if write:
        _safe_write(out, settings.RAW_FINANCIAL)
    return out


def _read_top10() -> pd.DataFrame:
    """十大股东：三批文件合并（CSMAR 单次导出上限 100 万行）。"""
    frames = []
    for path in [settings.RAW_DIR / f"TOP10_holders_{s}.csv" for s in ("A", "B", "C")]:
        if not path.exists():
            continue
        for chunk in pd.read_csv(path, dtype=str, encoding="utf-8-sig", chunksize=300_000,
                                 low_memory=False):
            chunk["Reptdt"] = chunk["Reptdt"].astype(str).str.strip()
            year = chunk["Reptdt"].str[:4]
            mask = chunk["Reptdt"].str.endswith("-12-31") & year.str.isdigit() & year.astype(int).between(YEAR_MIN, YEAR_MAX)
            sub = chunk.loc[mask]
            if len(sub):
                sub = sub.assign(year=year[mask].astype(int))
                frames.append(sub)
        logger.info("已读取 %s（累计 %d 行）", path.name, sum(len(f) for f in frames))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["stock_code"] = df["Stkcd"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    df["ratio"] = pd.to_numeric(df["S0304a"], errors="coerce")
    df["shares"] = pd.to_numeric(df["S0302a"], errors="coerce")
    df["rank"] = pd.to_numeric(df["S0306a"], errors="coerce")
    return df


def _read_audit() -> pd.DataFrame:
    """读取审计意见表。

    CSMAR 该表存在字段内逗号未转义的脏行（C 引擎报 ragged line），
    因此用 csv 模块按列名取索引，逐行容错解析，坏行跳过并计数。
    """
    import csv

    path = settings.RAW_DIR / "AUD_opinion.csv"
    if not path.exists():
        logger.warning("缺少 AUD_opinion.csv")
        return pd.DataFrame()

    records, bad = [], 0
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        need = {k: idx[k] for k in ("Stkcd", "Accper", "Audittyp", "Auditor", "Annodt",
                                     "Dadtunit", "Iadtunit") if k in idx}
        need["Tcost"] = idx.get("Tcost", -1)
        width = max(v for v in need.values() if v >= 0) + 1
        for row in reader:
            if len(row) < width:
                bad += 1
                continue
            accper = row[need["Accper"]].strip()
            if not accper.endswith("-12-31"):
                continue
            year = accper[:4]
            if not year.isdigit() or not (YEAR_MIN <= int(year) <= YEAR_MAX):
                continue
            # 审计机构在 Dadtunit（境内）/ Iadtunit（境外），Auditor 是签字会计师，不能用来判四大
            firm = row[need["Dadtunit"]] if "Dadtunit" in need else ""
            if not firm and "Iadtunit" in need:
                firm = row[need["Iadtunit"]]
            records.append({
                "stock_code": row[need["Stkcd"]].strip(),
                "year": int(year),
                "Audittyp": row[need["Audittyp"]],
                "Auditor": row[need["Auditor"]],
                "Firm": firm,
                "Annodt": row[need["Annodt"]],
                "Tcost": row[need["Tcost"]] if need["Tcost"] >= 0 else None,
            })
    df = pd.DataFrame(records)
    if bad:
        logger.warning("审计意见表：%d 行字段数异常已跳过", bad)
    if df.empty:
        return df
    df["stock_code"] = df["stock_code"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    df["audit_opinion"] = (~df["Audittyp"].astype(str).str.contains("标准无保留", na=False)).astype(int)
    df["big4_audit"] = df["Firm"].astype(str).str.contains("|".join(BIG4_KEYWORDS), case=False, na=False).astype(int)
    df["audit_fee"] = pd.to_numeric(df.get("Tcost"), errors="coerce") * 1e-8
    df = df.sort_values([*KEY, "Annodt"]).drop_duplicates(KEY, keep="last")
    return df[[*KEY, "audit_opinion", "big4_audit", "audit_fee"]]


def _read_management_ability() -> pd.DataFrame:
    """管理层治理能力表（BDT_ManaGovAbil）→ 两职合一（ConcurrentPosition：0=否，1=是）。"""
    path = settings.RAW_DIR / "CG_management_ability.csv"
    if not path.exists():
        return pd.DataFrame(columns=[*KEY, "duality"])
    df = pd.read_csv(path, usecols=["Symbol", "Enddate", "ConcurrentPosition"],
                     dtype=str, encoding="utf-8-sig")
    year = df["Enddate"].astype(str).str[:4]
    year_num = pd.to_numeric(year, errors="coerce")
    mask = (df["Enddate"].astype(str).str.endswith("-12-31")
            & year_num.between(YEAR_MIN, YEAR_MAX).fillna(False))
    df = df.loc[mask].copy()
    df["year"] = year_num[mask].astype(int)
    df["stock_code"] = df["Symbol"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    df["duality"] = pd.to_numeric(df["ConcurrentPosition"], errors="coerce")
    df = df[df["duality"].isin([0, 1])]
    return df.sort_values(KEY).drop_duplicates(KEY, keep="last")[[*KEY, "duality"]]


def _read_board_duality() -> pd.DataFrame:
    """治理综合信息表（CG_Ybasic）→ 两职合一（Y1001b：1=同一人，2=不同一人）。"""
    path = settings.RAW_DIR / "CG_board.csv"
    if not path.exists():
        return pd.DataFrame(columns=[*KEY, "duality"])
    df = pd.read_csv(path, usecols=["Stkcd", "Reptdt", "Y1001b"], dtype=str, encoding="utf-8-sig")
    year = df["Reptdt"].astype(str).str[:4]
    year_num = pd.to_numeric(year, errors="coerce")
    mask = (df["Reptdt"].astype(str).str.endswith("-12-31")
            & year_num.between(YEAR_MIN, YEAR_MAX).fillna(False))
    df = df.loc[mask].copy()
    df["year"] = year_num[mask].astype(int)
    df["stock_code"] = df["Stkcd"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    df["duality"] = df["Y1001b"].astype(str).str.strip().map({"1": 1, "2": 0})
    df = df.dropna(subset=["duality"])
    return df.sort_values(KEY).drop_duplicates(KEY, keep="last")[[*KEY, "duality"]]


def build_governance(write: bool = False) -> pd.DataFrame:
    top10 = _read_top10()
    if top10.empty:
        logger.warning("无十大股东数据，跳过 governance")
        return pd.DataFrame()

    ratio_rank1 = top10[top10["rank"].eq(1)].groupby(KEY)["ratio"].max()
    top2_5 = top10[top10["rank"].between(2, 5)].groupby(KEY)["ratio"].sum()
    inst = top10[top10["CategoryID"].astype(str).str.startswith(INST_PREFIX)].groupby(KEY)["ratio"].sum()
    valid = top10[(top10["ratio"] > 0) & (top10["shares"] > 0)]
    implied = (valid["shares"] / (valid["ratio"] / 100)).groupby([valid["stock_code"], valid["year"]]).median()

    gov = pd.DataFrame({
        "top1_holding": ratio_rank1 / 100,
        "top2_5_holding": top2_5 / 100,
        "institutional_holding": inst / 100,
        "total_shares_implied": implied,
    }).reset_index()

    cg_path = settings.RAW_DIR / "CG_manager.csv"
    if cg_path.exists():
        frames = []
        for chunk in pd.read_csv(cg_path, dtype=str, encoding="utf-8-sig", chunksize=200_000, low_memory=False):
            chunk["Enddate"] = chunk["Enddate"].astype(str)
            year = chunk["Enddate"].str[:4]
            mask = (chunk["Enddate"].str.endswith("-12-31") & year.str.isdigit()
                    & year.astype(int).between(YEAR_MIN, YEAR_MAX)
                    & chunk.get("StatisticalCaliber", pd.Series("1", index=chunk.index)).astype(str).eq("1"))
            sub = chunk.loc[mask]
            if len(sub):
                frames.append(sub.assign(year=year[mask].astype(int)))
        if frames:
            cg = pd.concat(frames, ignore_index=True)
            cg["stock_code"] = cg["Symbol"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
            cg["board_size"] = pd.to_numeric(cg["DirectorNumber"], errors="coerce")
            cg["independent_directors"] = pd.to_numeric(cg["IndependentDirectorNumber"], errors="coerce")
            cg["manage_shares"] = pd.to_numeric(cg.get("ManageHoldshares"), errors="coerce")
            cg = cg.sort_values(KEY).drop_duplicates(KEY, keep="last")
            gov = gov.merge(cg[[*KEY, "board_size", "independent_directors", "manage_shares"]],
                            on=KEY, how="outer")
            logger.info("高管表：%d 个公司-年", len(cg))

    if {"manage_shares", "total_shares_implied"}.issubset(gov.columns):
        gov["management_holding"] = gov["manage_shares"] / gov["total_shares_implied"]
    audit = _read_audit()
    if not audit.empty:
        gov = gov.merge(audit[[*KEY, "big4_audit", "audit_fee"]], on=KEY, how="left")
    # 两职合一：优先管理层治理能力表（ConcurrentPosition），缺失用治理综合表（Y1001b）回填
    dual = _read_management_ability()
    board = _read_board_duality()
    if dual.empty:
        dual = board
    elif not board.empty:
        dual = dual.merge(board.rename(columns={"duality": "duality_board"}), on=KEY, how="outer")
        dual["duality"] = dual["duality"].fillna(dual["duality_board"])
        dual = dual[[*KEY, "duality"]]
    if not dual.empty:
        gov = gov.merge(dual, on=KEY, how="left")
        logger.info("两职合一：非空率 %.1f%%（BDT 优先，CG_board 回填）",
                    gov["duality"].notna().mean() * 100)
    else:
        gov["duality"] = pd.NA
    gov["audit_fee"] = gov.get("audit_fee")

    contract = [*KEY, "top1_holding", "top2_5_holding", "board_size", "independent_directors",
                "management_holding", "duality", "big4_audit", "institutional_holding"]
    out = gov[[c for c in contract if c in gov.columns]]
    out = out.dropna(subset=KEY).sort_values(KEY).reset_index(drop=True)
    logger.info("治理表：%d 行，top1 非空率 %.1f%%，董事会人数非空率 %.1f%%", len(out),
                out["top1_holding"].notna().mean() * 100, out.get("board_size", pd.Series(dtype=float)).notna().mean() * 100)
    if write:
        _safe_write(out, settings.RAW_GOVERNANCE)
    return out


def build_market(write: bool = False) -> pd.DataFrame:
    """审计 + CSMAR 日行情公司-年特征。

    annual_turnover 统一为小数倍数（日换手率求和）；stock_volatility 为
    日收益率样本标准差 ×sqrt(252)。保留 trading_days 和覆盖率辅助列，
    极端值在特征层仅用训练窗口分位点缩尾。
    """
    audit = _read_audit()
    if audit.empty:
        return pd.DataFrame()
    out = audit.copy()
    trd_path = settings.RAW_DIR / "candidates" / "TRD_Dly_company_year_2013_2026.csv"
    if trd_path.exists():
        trd = pd.read_csv(trd_path, dtype={"Stkcd": str}, encoding="utf-8-sig")
        trd = trd.rename(columns={"Stkcd": "stock_code"})
        trd["stock_code"] = trd["stock_code"].str.zfill(6)
        trd["year"] = pd.to_numeric(trd["year"], errors="coerce").astype(int)
        trd["annual_turnover"] = pd.to_numeric(trd["annual_turnover"], errors="coerce")
        trd["stock_volatility"] = pd.to_numeric(trd["stock_volatility"], errors="coerce")
        valid = ((trd["trading_days"] > 0) & (trd["turnover_coverage"] >= 0.8)
                 & (trd["return_coverage"] >= 0.8) & trd["year"].between(YEAR_MIN, YEAR_MAX))
        trd["market_available"] = valid.astype(int)
        trd.loc[~valid, ["annual_turnover", "stock_volatility"]] = pd.NA
        cols = [*KEY, "annual_turnover", "stock_volatility", "market_available",
                "trading_days", "turnover_coverage", "return_coverage"]
        out = out.merge(trd[cols].drop_duplicates(KEY, keep="last"), on=KEY, how="left")
    for col in ("annual_turnover", "stock_volatility"):
        if col not in out.columns:
            out[col] = pd.NA
    if "market_available" not in out.columns:
        out["market_available"] = 0
    out["market_available"] = out["market_available"].fillna(0).astype(int)
    logger.info("市场/审计表：%d 行，非标意见 %.2f%%，有效行情覆盖 %.2f%%", len(out),
                out["audit_opinion"].mean() * 100, out["market_available"].mean() * 100)
    if write:
        _safe_write(out, settings.RAW_MARKET)
    return out


def _read_lawsuit_counts() -> pd.DataFrame:
    """LA_DETAIL → 首次公告年 distinct EventID 数。

    同一事件先取全历史最早 DeclareDate，再归属公司-年；后续进展/年报公告
    不重复计数。该表 EventContent 含未转义逗号，所需字段位于前5列，按位置解析。
    """
    import csv

    path = settings.RAW_DIR / "LAW_lawsuit.csv"
    if not path.exists():
        logger.warning("缺少 LAW_lawsuit.csv，litigation_count 留空")
        return pd.DataFrame(columns=[*KEY, "litigation_count"])
    records, bad = [], 0
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)
        for fields in reader:
            if len(fields) < 5:
                bad += 1
                continue
            code, event_id, date = fields[0].strip(), fields[2].strip(), fields[4].strip()
            year = date[:4]
            if not year.isdigit() or not (YEAR_MIN <= int(year) <= YEAR_MAX):
                continue
            records.append((code, int(year), event_id))
    if bad:
        logger.warning("诉讼仲裁表：%d 行字段数不足已跳过", bad)
    df = pd.DataFrame(records, columns=["stock_code", "year", "EventID"])
    df["stock_code"] = df["stock_code"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    df = df.dropna(subset=["stock_code", "EventID"]).drop_duplicates(["stock_code", "EventID", "year"])
    first = df.groupby(["stock_code", "EventID"], as_index=False)["year"].min()
    out = first.groupby(KEY).size().rename("litigation_count").reset_index()
    logger.info("诉讼仲裁：%d 个公司-年有涉诉，合计 %d 起事件", len(out), int(out["litigation_count"].sum()))
    return out


def _read_violation_counts() -> pd.DataFrame:
    """违规信息总表（STK_Violation_Main）→ 公司-年处罚次数。

    口径：IsViolated=Y（上市公司自身违规），按处理文件日期 DisposalDate 所在年，
    ViolationID 去重（同一事件的后续进展不重复计数）。
    """
    path = settings.RAW_DIR / "VIO_penalty.csv"
    if not path.exists():
        logger.warning("缺少 VIO_penalty.csv，penalty_count 留空")
        return pd.DataFrame(columns=[*KEY, "penalty_count"])
    df = pd.read_csv(path, usecols=["ViolationID", "Symbol", "DisposalDate", "IsViolated"],
                     dtype=str, encoding="utf-8-sig")
    df = df[df["IsViolated"].astype(str).str.strip().str.upper().eq("Y")]
    year = df["DisposalDate"].astype(str).str[:4]
    mask = year.str.isdigit() & year.astype(int).between(YEAR_MIN, YEAR_MAX)
    df = df.loc[mask].copy()
    df["year"] = year[mask].astype(int)
    df["stock_code"] = df["Symbol"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    df = df.drop_duplicates(["stock_code", "year", "ViolationID"])
    out = df.groupby(KEY).size().rename("penalty_count").reset_index()
    logger.info("违规处罚：%d 个公司-年有处罚，合计 %d 起", len(out), int(out["penalty_count"].sum()))
    return out


def build_legal(write: bool = False) -> pd.DataFrame:
    """司法/合规公司-年全网格。

    诉讼：全历史首次 DeclareDate 年内按 EventID 去重，后续进展不重复；
    处罚：DisposalDate 年内按 ViolationID 去重。与 candidates/legal_events.csv
    的“事件最终公告年”及旧在线表“年度公告活动”均不同，禁止混用。
    """
    law = _read_lawsuit_counts()
    vio = _read_violation_counts()
    events = law.merge(vio, on=KEY, how="outer")
    fin = pd.read_csv(settings.RAW_FINANCIAL, dtype={"stock_code": str},
                      usecols=["stock_code", "year"], encoding="utf-8-sig")
    fin["stock_code"] = fin["stock_code"].str.zfill(6)
    fin["year"] = pd.to_numeric(fin["year"], errors="coerce")
    fin = fin.dropna(subset=KEY)
    fin["year"] = fin["year"].astype(int)
    fin = fin[fin["stock_code"].str[:3].isin(A_SHARE_PREFIXES) & fin["year"].between(YEAR_MIN, YEAR_MAX)]
    # 2026 仅保留实际有事件的键，不用 2025 公司集外推，且标记为未完整。
    keys = pd.concat([fin[KEY], events.loc[events["year"].eq(YEAR_MAX), KEY]], ignore_index=True).drop_duplicates(KEY)
    out = keys.merge(events, on=KEY, how="left", validate="one_to_one")
    for col in ("litigation_count", "penalty_count"):
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["legal_event_count"] = out["litigation_count"] + out["penalty_count"]
    out["has_lawsuit"] = out["litigation_count"].gt(0).astype(int)
    out["has_penalty"] = out["penalty_count"].gt(0).astype(int)
    out["legal_available"] = out["year"].lt(YEAR_MAX).astype(int)
    out["legal_source"] = "CSMAR.LA_DETAIL first announcement year + STK_Violation_Main disposal year"
    out = out.sort_values(KEY).reset_index(drop=True)
    logger.info("司法全网格：%d 行；诉讼合计 %d，处罚合计 %d；完整年度覆盖标记 %.1f%%",
                len(out), out["litigation_count"].sum(), out["penalty_count"].sum(),
                out["legal_available"].mean() * 100)
    if write:
        _safe_write(out, settings.RAW_LEGAL)
    return out


def build_digital(write: bool = False) -> pd.DataFrame:
    """数字化转型词频（年报口径 + MD&A 口径）→ digital_features.csv。

    源表为已清洗的 DT_digital_transform.csv / DT_mda_orientation.csv
    （CSMAR 数字化转型库，吴非等 2021 词频法）。词频右偏严重，统一 log(1+x)。
    """
    path = settings.RAW_DIR / "DT_digital_transform.csv"
    if not path.exists():
        logger.warning("缺少 DT_digital_transform.csv，数字化转型特征留空")
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"Symbol": str, "SgnYear": str}, encoding="utf-8-sig")
    out = pd.DataFrame({
        "stock_code": df["Symbol"].astype(str).str.zfill(6),
        "year": pd.to_numeric(df["SgnYear"], errors="coerce"),
    })
    out = out[out["year"].between(YEAR_MIN, YEAR_MAX)].copy()
    df = df.loc[out.index]
    freq_map = {
        "DTTotal": "dt_wordfreq", "AITechnology": "dt_ai", "BlockChainTechnology": "dt_blockchain",
        "CloudComputingTech": "dt_cloud", "BigDataTechnology": "dt_bigdata",
        "DigitalTechApplication": "dt_application",
    }
    for src, dst in freq_map.items():
        out[dst] = np.log1p(pd.to_numeric(df[src], errors="coerce").fillna(0))
    out = out.dropna(subset=["year"])
    out["year"] = out["year"].astype(int)
    out = out.drop_duplicates(KEY, keep="last")
    out["digital_available"] = 1  # 年报源表有记录；DTTotal=0 仍是有效观测

    mda_path = settings.RAW_DIR / "DT_mda_orientation.csv"
    if mda_path.exists():
        mda = pd.read_csv(mda_path, dtype={"Symbol": str, "SgnYear": str}, encoding="utf-8-sig")
        mda = pd.DataFrame({
            "stock_code": mda["Symbol"].astype(str).str.zfill(6),
            "year": pd.to_numeric(mda["SgnYear"], errors="coerce"),
            "dt_mda_wordfreq": np.log1p(pd.to_numeric(mda["DTTotal"], errors="coerce").fillna(0)),
        }).dropna(subset=["year"])
        mda["year"] = mda["year"].astype(int)
        mda = mda.drop_duplicates(KEY, keep="last")
        out["year"] = out["year"].astype(int)
        out = out.merge(mda, on=KEY, how="outer")
        out["digital_available"] = out["digital_available"].fillna(0).astype(int)
    else:
        logger.warning("缺少 DT_mda_orientation.csv，dt_mda_wordfreq 留空")
        out["dt_mda_wordfreq"] = pd.NA
        out["year"] = out["year"].astype(int)
    out = out.sort_values(KEY).reset_index(drop=True)
    logger.info("数字化转型：%d 个公司-年，dt_wordfreq 非零率 %.1f%%", len(out),
                (out["dt_wordfreq"] > 0).mean() * 100)
    if write:
        _safe_write(out, settings.RAW_DIGITAL)
    return out


def _event_year(series: pd.Series) -> pd.Series:
    """从 `2019-04-30` / `2019/04/30` / `2019年` 中提取年份。"""
    return pd.to_numeric(series.astype(str).str.extract(r"(\d{4})", expand=False), errors="coerce")


def build_labels(write: bool = False) -> pd.DataFrame | None:
    """ST 事件表 → 完整 0/1 公司-年标签；缺表时返回 None（阻断建模）。

    关键口径：
    - 标签全集取财务主表的公司-年，未命中任何 ST 事件的公司-年显式记为 0；
      不能只输出正样本，否则 `add_features` 的 `notna()` 会把负样本全部丢掉。
    - 事件区间为 [实施日期所在年, 撤销日期所在年]；撤销日期缺失视为仍在 ST，
      一直标记到 YEAR_MAX。这样既保留 ST 期间，也不会在撤销后继续误标。
    """
    path = settings.RAW_DIR / "ST_events.csv"
    if not path.exists():
        logger.warning("缺少 ST_events.csv（P0 表），无法生成 is_st 标签——建模被阻断")
        return None
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    cols = {str(c).lower(): c for c in df.columns}
    code_col = next((c for k, c in cols.items() if "code" in k or "代码" in k), None)
    start_col = next((c for k, c in cols.items() if "实施" in k or "start" in k), None)
    if start_col is None:
        start_col = next((c for k, c in cols.items() if "date" in k or "日期" in k), None)
    end_col = next((c for k, c in cols.items() if "撤销" in k or "取消" in k or "end" in k), None)
    if code_col is None or start_col is None:
        raise ValueError("ST_events.csv 至少需要「证券代码」和「实施日期」两列")

    df["stock_code"] = df[code_col].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    df["start_year"] = _event_year(df[start_col])
    df["end_year"] = _event_year(df[end_col]) if end_col else YEAR_MAX
    df["end_year"] = df["end_year"].fillna(YEAR_MAX).clip(upper=YEAR_MAX)
    df = df.dropna(subset=["start_year"]).copy()
    df["start_year"] = df["start_year"].astype(int)
    df["end_year"] = df["end_year"].astype(int)

    # 标签全集：财务主表出现过的公司-年；缺失财务表时退化为事件表覆盖的年份
    if settings.RAW_FINANCIAL.exists():
        fin = pd.read_csv(settings.RAW_FINANCIAL, dtype={"stock_code": str},
                          usecols=["stock_code", "year"])
        keys = fin.drop_duplicates().copy()
        keys["stock_code"] = keys["stock_code"].astype(str).str.zfill(6)
        keys["year"] = pd.to_numeric(keys["year"], errors="coerce")
        keys = keys.dropna(subset=["year"])
        keys["year"] = keys["year"].astype(int)
        keys = keys[keys["stock_code"].str[:3].isin(A_SHARE_PREFIXES)]
        keys = keys[keys["year"].between(YEAR_MIN, YEAR_MAX)]
    else:
        keys = pd.DataFrame(
            [(code, y) for code in df["stock_code"].unique()
             for y in range(YEAR_MIN, YEAR_MAX + 1)],
            columns=KEY,
        )

    positive: set[tuple[str, int]] = set()
    for code, start, end in df[["stock_code", "start_year", "end_year"]].itertuples(index=False, name=None):
        for year in range(max(int(start), YEAR_MIN), min(int(end), YEAR_MAX) + 1):
            positive.add((str(code), year))

    out = keys.drop_duplicates(KEY).reset_index(drop=True)
    out["is_st"] = [1 if (c, y) in positive else 0 for c, y in zip(out["stock_code"], out["year"])]
    out["label_source"] = (df["数据来源"].dropna().iloc[0]
                           if "数据来源" in df.columns and df["数据来源"].notna().any()
                           else "ST_events.csv")
    logger.info("ST 标签：%d 个公司-年，正样本 %d（%.2f%%），覆盖 %d-%d",
                len(out), int(out["is_st"].sum()), out["is_st"].mean() * 100,
                int(out["year"].min()), int(out["year"].max()))
    if write:
        _safe_write(out, settings.RAW_LABELS)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="CSMAR 原始导出 → raw 契约")
    parser.add_argument("--step", default="all",
                        choices=["all", "basic", "financial", "governance", "market",
                                 "legal", "digital", "labels", "list"])
    parser.add_argument("--write", action="store_true", help="写入 data/raw（默认只演练）")
    args = parser.parse_args()

    if args.step == "list":
        for code, field in _codes().items():
            print(f"{code} → {field}")
        return

    settings.ensure_dirs()
    if args.step in {"all", "basic"}:
        load_basic_info()
    if args.step in {"all", "financial"}:
        build_financial(args.write)
    if args.step in {"all", "governance"}:
        build_governance(args.write)
    if args.step in {"all", "market"}:
        build_market(args.write)
    if args.step in {"all", "legal"}:
        build_legal(args.write)
    if args.step in {"all", "digital"}:
        build_digital(args.write)
    if args.step in {"all", "labels"}:
        build_labels(args.write)


if __name__ == "__main__":
    main()
