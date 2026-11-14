"""从 CSMAR《特殊处理变动文件》SPT_Trdchg 生成官方 ST 事件与 0/1 标签。

输入（原始导出，不改列名/不改单位）：
    data/incoming/csmar/**/_unzip_ST_*/SPT_Trdchg.csv

输出（默认只写 incoming，不覆盖当前代理标签）：
    data/incoming/csmar/ST_events_official.csv
    data/incoming/csmar/labels_st_official.csv
    data/incoming/csmar/st_official_summary.json

字段口径（CSMAR 数据库说明书）：
    Chgtype: A=正常上市, B=ST, D=*ST, C=PT, S=暂停上市, T=退市整理期, X=终止上市
    两个字符分别表示变动前/变动后状态；例如 AB = 正常 -> ST。

标签口径：
    以财务主表出现的 A 股公司-年为全集；事件区间 [实施日期所在年, 撤销日期所在年]
    内标 1，区间外标 0。开放区间（尚未撤销）截至 LABEL_END_YEAR。
    这与 etl.csmar_import.build_labels 的区间口径一致，便于直接替换。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from config import settings
from etl.csmar_import import A_SHARE_PREFIXES, YEAR_MAX, YEAR_MIN

ST_STATES = {"B", "D"}
STATE_TYPE = {"B": "ST", "D": "*ST"}


def read_events(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    need = {"Stkcd", "Stknmebc", "Stknmeac", "Chgtype", "Annoudt", "Execudt"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"缺少字段: {sorted(missing)}")
    df = df.rename(columns={
        "Stkcd": "stock_code", "Stknmebc": "name_before", "Stknmeac": "name_after",
        "Chgtype": "chgtype", "Annoudt": "announce_date", "Execudt": "exec_date",
    })
    df["stock_code"] = df["stock_code"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    df["chgtype"] = df["chgtype"].astype(str).str.strip().str.upper()
    df["announce_date"] = pd.to_datetime(df["announce_date"], errors="coerce")
    df["exec_date"] = pd.to_datetime(df["exec_date"], errors="coerce")
    df = df[df["stock_code"].str[:3].isin(A_SHARE_PREFIXES)]
    df = df[df["chgtype"].str.len().eq(2) & df["chgtype"].str[0].isin(set("ABDCT SX".replace(" ", "")))]
    df = df.dropna(subset=["exec_date"]).copy()
    df["state_before"] = df["chgtype"].str[0]
    df["state_after"] = df["chgtype"].str[1]
    df = df.sort_values(["stock_code", "exec_date", "announce_date"], kind="mergesort")
    return df.reset_index(drop=True)


def build_spells(events: pd.DataFrame) -> pd.DataFrame:
    """把逐次状态变动压缩为 ST/*ST 连续区间。"""
    spells: list[dict] = []
    for code, part in events.groupby("stock_code", sort=True):
        part = part.sort_values(["exec_date", "announce_date"], kind="mergesort")
        open_spell: dict | None = None
        for row in part.itertuples(index=False):
            after = row.state_after
            if after in ST_STATES:
                if open_spell is None:
                    open_spell = {
                        "证券代码": code,
                        "证券简称": row.name_after or row.name_before or "",
                        "实施日期": row.exec_date,
                        "特别处理类型": STATE_TYPE[after],
                        "撤销日期": pd.NaT,
                        "公告日期": row.announce_date,
                        "变动类型": row.chgtype,
                        "_last_state": after,
                    }
                else:
                    open_spell["特别处理类型"] = "*ST" if after == "D" else open_spell["特别处理类型"]
                    open_spell["_last_state"] = after
            elif open_spell is not None:
                open_spell["撤销日期"] = row.exec_date
                open_spell["撤销公告日期"] = row.announce_date
                open_spell["撤销变动类型"] = row.chgtype
                spells.append(open_spell)
                open_spell = None
        if open_spell is not None:
            open_spell["撤销日期"] = pd.NaT
            open_spell["撤销公告日期"] = pd.NaT
            open_spell["撤销变动类型"] = ""
            spells.append(open_spell)

    out = pd.DataFrame(spells)
    if out.empty:
        raise ValueError("未生成任何 ST 区间")
    out["实施日期"] = pd.to_datetime(out["实施日期"]).dt.strftime("%Y-%m-%d")
    out["撤销日期"] = pd.to_datetime(out["撤销日期"]).dt.strftime("%Y-%m-%d")
    out["公告日期"] = pd.to_datetime(out["公告日期"]).dt.strftime("%Y-%m-%d")
    out["撤销公告日期"] = pd.to_datetime(out["撤销公告日期"]).dt.strftime("%Y-%m-%d")
    out["数据来源"] = "CSMAR 特殊处理与特别转让-特殊处理变动文件 SPT_Trdchg"
    out["备注"] = "由逐次 Chgtype 状态变动压缩；ST/*ST 连续区间，撤销日期缺失表示截至导出日仍处于特殊处理"
    out = out.drop(columns=["_last_state"]).sort_values(["证券代码", "实施日期"]).reset_index(drop=True)
    return out


def build_labels(events: pd.DataFrame, end_year: int = YEAR_MAX) -> pd.DataFrame:
    fin = pd.read_csv(settings.RAW_FINANCIAL, dtype={"stock_code": str}, usecols=["stock_code", "year"])
    keys = fin.drop_duplicates().copy()
    keys["stock_code"] = keys["stock_code"].astype(str).str.zfill(6)
    keys["year"] = pd.to_numeric(keys["year"], errors="coerce")
    keys = keys.dropna(subset=["year"])
    keys["year"] = keys["year"].astype(int)
    keys = keys[keys["stock_code"].str[:3].isin(A_SHARE_PREFIXES)]
    keys = keys[keys["year"].between(YEAR_MIN, end_year)].drop_duplicates(["stock_code", "year"])

    positive: set[tuple[str, int]] = set()
    for row in events.itertuples(index=False):
        code = str(getattr(row, "证券代码")).zfill(6)
        start = int(str(getattr(row, "实施日期"))[:4])
        end_raw = str(getattr(row, "撤销日期"))
        end = int(end_raw[:4]) if end_raw[:4].isdigit() else end_year
        for year in range(max(start, YEAR_MIN), min(end, end_year) + 1):
            positive.add((code, year))
    keys["is_st"] = [1 if (c, y) in positive else 0 for c, y in zip(keys["stock_code"], keys["year"])]
    keys["label_source"] = "ST_events_official_SPT_Trdchg"
    return keys.reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="从 CSMAR SPT_Trdchg 生成官方 ST 事件/标签")
    parser.add_argument("--input", default="",
                        help="SPT_Trdchg.csv 路径；默认在 data/incoming/csmar/ 下递归找 _unzip_ST_*")
    parser.add_argument("--write", action="store_true", help="写入 incoming")
    parser.add_argument("--end-year", type=int, default=YEAR_MAX)
    args = parser.parse_args()

    if args.input:
        path = Path(args.input)
    else:
        # 暂存区已按批次归档（raw/_unzip_* → 20261113/_unzip/_unzip_*），递归查找兼容两种布局
        candidates = sorted(settings.STAGING_DIR.glob("**/_unzip_ST_*/SPT_Trdchg.csv"))
        if not candidates:
            raise FileNotFoundError("未找到 SPT_Trdchg.csv，请用 --input 指定")
        path = candidates[-1]

    events = read_events(path)
    spells = build_spells(events)
    labels = build_labels(spells, args.end_year)

    print(f"输入: {path}")
    print(f"状态变动: {len(events):,} 行；ST 区间: {len(spells):,} 段；公司: {spells['证券代码'].nunique():,}")
    print(f"区间年份: {spells['实施日期'].str[:4].min()} - {spells['实施日期'].str[:4].max()}")
    print("\n标签年度分布：")
    print(labels.groupby("year")["is_st"].agg(["size", "sum", "mean"]).to_string())

    # 与当前代理标签对照（仅重叠年份）
    proxy_path = settings.RAW_LABELS
    if proxy_path.exists():
        proxy = pd.read_csv(proxy_path, dtype={"stock_code": str})
        merged = labels.merge(proxy[["stock_code", "year", "is_st"]], on=["stock_code", "year"],
                              how="inner", suffixes=("_official", "_proxy"))
        both = merged.dropna(subset=["is_st_official", "is_st_proxy"])
        if len(both):
            agree = (both["is_st_official"].astype(int) == both["is_st_proxy"].astype(int)).mean()
            print(f"\n与代理标签重叠 {len(both):,} 公司-年；一致率 {agree:.2%}")
            print(pd.crosstab(both["is_st_proxy"], both["is_st_official"], rownames=["proxy"], colnames=["official"]).to_string())

    if args.write:
        out_dir = settings.DATA_DIR / "incoming" / "csmar"
        out_dir.mkdir(parents=True, exist_ok=True)
        spells.to_csv(out_dir / "ST_events_official.csv", index=False, encoding="utf-8-sig")
        labels.to_csv(out_dir / "labels_st_official.csv", index=False, encoding="utf-8-sig")
        summary = {
            "source": str(path),
            "transition_rows": int(len(events)),
            "spell_rows": int(len(spells)),
            "companies": int(spells["证券代码"].nunique()),
            "label_rows": int(len(labels)),
            "positive_rows": int(labels["is_st"].sum()),
            "positive_rate": float(labels["is_st"].mean()),
            "year_min": int(labels["year"].min()),
            "year_max": int(labels["year"].max()),
            "by_year": {str(k): {"n": int(v["size"]), "pos": int(v["sum"]), "rate": float(v["mean"])}
                        for k, v in labels.groupby("year")["is_st"].agg(["size", "sum", "mean"]).iterrows()},
        }
        (out_dir / "st_official_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入: {out_dir / 'ST_events_official.csv'}")
        print(f"已写入: {out_dir / 'labels_st_official.csv'}")
        print(f"已写入: {out_dir / 'st_official_summary.json'}")


if __name__ == "__main__":
    main()
