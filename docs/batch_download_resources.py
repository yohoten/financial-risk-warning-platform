#!/usr/bin/env python3
"""
batch_download_resources.py
===========================
批量下载"上市公司财务风险智能预警平台"调研报告中引用的学术文献、
技术博客和GitHub开源项目。

功能：
  1. 读取 resources_catalog.csv 资源清单
  2. 按类型筛选（paper / blog / repo / data_platform / all）
  3. 对可直接下载的PDF执行批量下载（带进度条和重试）
  4. 对GitHub仓库执行 git clone
  5. 对需登录的平台生成待手动下载清单
  6. 完整日志记录（成功/失败/需手动）
  7. 支持 --dry-run 预览模式

用法：
  python batch_download_resources.py --type all --output-dir ./downloads
  python batch_download_resources.py --type paper --output-dir ./papers --dry-run
  python batch_download_resources.py --type repo --output-dir ./repos
"""

import argparse
import csv
import json
import logging
import os
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
    from tqdm import tqdm
except ImportError:
    print("=" * 60)
    print("缺少必要依赖，请先安装：")
    print("  pip install requests tqdm")
    print("=" * 60)
    sys.exit(1)


# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------
DEFAULT_CATALOG = "resources_catalog.csv"
DEFAULT_OUTPUT_DIR = "./downloads"
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
REQUEST_TIMEOUT = 30  # seconds
CHUNK_SIZE = 8192  # bytes

# arXiv PDF直链模板
ARXIV_PDF_TEMPLATE = "https://arxiv.org/pdf/{arxiv_id}.pdf"

# NeurIPS PDF直链模板（从abstract页面推导）
NEURIPS_PDF_BASE = "https://proceedings.neurips.cc/paper_files/paper/"

# DOI解析服务
DOI_RESOLVER = "https://doi.org/"

# 需要手动下载的平台关键词
MANUAL_PLATFORMS = ["cnki", "wanfang", "知网", "万方", "ScienceDirect",
                    "CFA Institute", "SSRN", "JSTOR", "Oxford Academic",
                    "Nature", "PubMed", "AAA Digital Library"]


# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
def setup_logging(output_dir: str) -> logging.Logger:
    """配置日志：同时输出到控制台和文件。"""
    log_dir = Path(output_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "download_log.txt"

    logger = logging.getLogger("resource_downloader")
    logger.setLevel(logging.DEBUG)

    # 控制台handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_fmt)

    # 文件handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(file_fmt)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


# ---------------------------------------------------------------------------
# CSV读取
# ---------------------------------------------------------------------------
def load_catalog(catalog_path: str) -> list[dict]:
    """读取资源清单CSV文件。"""
    records = []
    with open(catalog_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)
    return records


def filter_records(records: list[dict], resource_type: str) -> list[dict]:
    """按资源类型筛选记录。"""
    if resource_type == "all":
        return records
    type_map = {
        "paper": ["paper_en", "paper_cn"],
        "blog": ["blog"],
        "repo": ["repo"],
        "data": ["data_platform"],
    }
    target_types = type_map.get(resource_type, [])
    if not target_types:
        raise ValueError(f"未知资源类型: {resource_type}，可选: paper/blog/repo/data/all")
    return [r for r in records if r["type"] in target_types]


# ---------------------------------------------------------------------------
# URL工具函数
# ---------------------------------------------------------------------------
def extract_arxiv_id(url: str) -> str | None:
    """从arXiv URL中提取论文ID。"""
    match = re.search(r"arxiv\.org/(abs|pdf)/(\d+\.\d+)", url)
    return match.group(2) if match else None


def is_direct_pdf_url(url: str) -> bool:
    """判断URL是否直接指向PDF文件。"""
    parsed = urlparse(url)
    return parsed.path.lower().endswith(".pdf")


def resolve_doi_to_pdf(doi_url: str) -> str | None:
    """尝试通过DOI解析获取PDF直链（best-effort）。"""
    try:
        resp = requests.head(doi_url, allow_redirects=True, timeout=10,
                             headers={"User-Agent": "ResourceDownloader/1.0"})
        final_url = resp.url
        if final_url.lower().endswith(".pdf"):
            return final_url
        # 某些出版商在HTML页面中嵌入PDF链接，这里不做深度解析
        return None
    except Exception:
        return None


def build_download_url(record: dict) -> str | None:
    """根据记录构建可下载的URL。返回None表示需要手动下载。"""
    url = record.get("url", "").strip()
    if not url:
        return None

    # arXiv → 直接PDF链接
    arxiv_id = extract_arxiv_id(url)
    if arxiv_id:
        return ARXIV_PDF_TEMPLATE.format(arxiv_id=arxiv_id)

    # NeurIPS proceedings → 尝试构建PDF链接
    if "neurips.cc" in url and "Abstract" in url:
        pdf_url = url.replace("-Abstract-Conference.html", ".pdf")
        return pdf_url

    # 直接PDF链接
    if is_direct_pdf_url(url):
        return url

    # DOI链接 → 尝试解析
    if "doi.org" in url:
        resolved = resolve_doi_to_pdf(url)
        if resolved:
            return resolved

    return None


def needs_manual_download(record: dict) -> bool:
    """判断该资源是否需要手动下载。"""
    channel = record.get("download_channel", "")
    notes = record.get("notes", "")
    combined = f"{channel} {notes}".lower()
    for platform in MANUAL_PLATFORMS:
        if platform.lower() in combined:
            return True
    return False


# ---------------------------------------------------------------------------
# 下载器
# ---------------------------------------------------------------------------
def download_pdf(url: str, save_path: Path, logger: logging.Logger,
                 dry_run: bool = False) -> bool:
    """下载单个PDF文件，带进度条和重试机制。"""
    if dry_run:
        logger.info(f"[DRY-RUN] 将下载: {url} → {save_path}")
        return True

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT,
                                headers={"User-Agent": "ResourceDownloader/1.0"})
            resp.raise_for_status()

            total_size = int(resp.headers.get("content-length", 0))
            save_path.parent.mkdir(parents=True, exist_ok=True)

            with open(save_path, "wb") as f:
                with tqdm(total=total_size, unit="B", unit_scale=True,
                          desc=save_path.name[:40], leave=False) as pbar:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))

            logger.info(f"✅ 下载成功: {save_path.name} ({save_path.stat().st_size:,} bytes)")
            return True

        except requests.exceptions.HTTPError as e:
            logger.warning(f"⚠️ HTTP错误 (尝试 {attempt}/{MAX_RETRIES}): {e}")
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"⚠️ 连接错误 (尝试 {attempt}/{MAX_RETRIES}): {e}")
        except requests.exceptions.Timeout:
            logger.warning(f"⚠️ 请求超时 (尝试 {attempt}/{MAX_RETRIES})")
        except Exception as e:
            logger.error(f"❌ 未知错误 (尝试 {attempt}/{MAX_RETRIES}): {e}")

        if attempt < MAX_RETRIES:
            logger.info(f"   {RETRY_DELAY}秒后重试...")
            time.sleep(RETRY_DELAY)

    logger.error(f"❌ 下载失败（已达最大重试次数）: {url}")
    return False


def clone_repo(repo_url: str, save_dir: Path, logger: logging.Logger,
               dry_run: bool = False) -> bool:
    """克隆GitHub仓库。"""
    repo_name = repo_url.rstrip("/").split("/")[-1]
    target_path = save_dir / repo_name

    if target_path.exists():
        logger.info(f"⏭️ 仓库已存在，跳过: {repo_name}")
        return True

    if dry_run:
        logger.info(f"[DRY-RUN] 将克隆: {repo_url} → {target_path}")
        return True

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(target_path)],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            logger.info(f"✅ 克隆成功: {repo_name}")
            return True
        else:
            logger.error(f"❌ 克隆失败: {result.stderr.strip()}")
            return False
    except FileNotFoundError:
        logger.error("❌ git未安装或不在PATH中，请安装Git")
        return False
    except subprocess.TimeoutExpired:
        logger.error(f"❌ 克隆超时: {repo_url}")
        return False
    except Exception as e:
        logger.error(f"❌ 克隆异常: {e}")
        return False


def open_in_browser(url: str, logger: logging.Logger,
                    dry_run: bool = False) -> bool:
    """在浏览器中打开URL（用于需手动下载的资源）。"""
    if dry_run:
        logger.info(f"[DRY-RUN] 将打开浏览器: {url}")
        return True
    try:
        webbrowser.open(url)
        logger.info(f"🌐 已在浏览器中打开: {url}")
        return True
    except Exception as e:
        logger.error(f"❌ 无法打开浏览器: {e}")
        return False


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def sanitize_filename(name: str, max_len: int = 80) -> str:
    """清理文件名中的非法字符。"""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:max_len]


def process_records(records: list[dict], output_dir: str,
                    logger: logging.Logger, dry_run: bool = False) -> dict:
    """处理所有资源记录，返回统计结果。"""
    stats = {"success": 0, "failed": 0, "manual": 0, "skipped": 0}
    manual_list = []
    paper_dir = Path(output_dir) / "papers"
    repo_dir = Path(output_dir) / "repos"
    blog_dir = Path(output_dir) / "blogs"

    for i, record in enumerate(records, 1):
        rid = record.get("id", f"#{i}")
        title = record.get("title", "Unknown")
        rtype = record.get("type", "unknown")
        url = record.get("url", "").strip()

        logger.info(f"\n{'='*60}")
        logger.info(f"[{i}/{len(records)}] {rid}: {title[:60]}")
        logger.info(f"  类型: {rtype} | URL: {url[:80]}")

        # --- GitHub仓库 ---
        if rtype == "repo":
            if not url:
                logger.warning("  ⚠️ 无URL，跳过")
                stats["skipped"] += 1
                continue
            ok = clone_repo(url, repo_dir, logger, dry_run)
            stats["success" if ok else "failed"] += 1
            continue

        # --- 数据平台（仅记录） ---
        if rtype == "data_platform":
            logger.info("  📋 数据平台资源，已记录到手动清单")
            manual_list.append(record)
            stats["manual"] += 1
            continue

        # --- 博客（打开浏览器） ---
        if rtype == "blog":
            if not url:
                logger.warning("  ⚠️ 无URL，跳过")
                stats["skipped"] += 1
                continue
            logger.info("  📖 博客文章，将在浏览器中打开")
            open_in_browser(url, logger, dry_run)
            manual_list.append(record)
            stats["manual"] += 1
            continue

        # --- 学术论文 ---
        if rtype in ("paper_en", "paper_cn"):
            # 检查是否需要手动下载
            if needs_manual_download(record):
                logger.info(f"  🔒 需手动下载 ({record.get('download_channel', '')})")
                manual_list.append(record)
                stats["manual"] += 1
                # 如果有URL，尝试在浏览器中打开
                if url and not dry_run:
                    open_in_browser(url, logger, dry_run)
                continue

            # 尝试自动下载
            download_url = build_download_url(record)
            if download_url:
                filename = sanitize_filename(f"{rid}_{title}") + ".pdf"
                save_path = paper_dir / filename
                ok = download_pdf(download_url, save_path, logger, dry_run)
                stats["success" if ok else "failed"] += 1
            else:
                logger.info("  🔒 无法构建直接下载链接，加入手动清单")
                manual_list.append(record)
                stats["manual"] += 1
                if url and not dry_run:
                    open_in_browser(url, logger, dry_run)
            continue

        # --- 未知类型 ---
        logger.warning(f"  ⚠️ 未知类型 '{rtype}'，跳过")
        stats["skipped"] += 1

    return stats, manual_list


def generate_manual_report(manual_list: list[dict], output_dir: str,
                           logger: logging.Logger):
    """生成待手动下载清单文件。"""
    if not manual_list:
        logger.info("\n📋 无需手动下载的资源")
        return

    report_path = Path(output_dir) / "manual_download_list.md"
    lines = [
        "# 待手动下载资源清单\n",
        f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"共计 {len(manual_list)} 项资源需要手动获取。\n",
        "---\n",
    ]

    papers = [r for r in manual_list if r["type"] in ("paper_en", "paper_cn")]
    blogs = [r for r in manual_list if r["type"] == "blog"]
    platforms = [r for r in manual_list if r["type"] == "data_platform"]

    if papers:
        lines.append("\n## 学术论文\n")
        lines.append("| 序号 | ID | 标题 | 推荐渠道 | 链接 |")
        lines.append("|------|-----|------|---------|------|")
        for i, r in enumerate(papers, 1):
            title_short = r["title"][:50]
            lines.append(
                f"| {i} | {r['id']} | {title_short} | "
                f"{r.get('download_channel', '')} | {r.get('url', '')} |"
            )

    if blogs:
        lines.append("\n## 技术博客\n")
        lines.append("| 序号 | ID | 标题 | 链接 |")
        lines.append("|------|-----|------|------|")
        for i, r in enumerate(blogs, 1):
            lines.append(f"| {i} | {r['id']} | {r['title'][:50]} | {r.get('url', '')} |")

    if platforms:
        lines.append("\n## 数据平台\n")
        lines.append("| 序号 | ID | 名称 | 链接 |")
        lines.append("|------|-----|------|------|")
        for i, r in enumerate(platforms, 1):
            lines.append(f"| {i} | {r['id']} | {r['title'][:50]} | {r.get('url', '')} |")

    lines.append("\n---\n")
    lines.append("*提示：中文论文可通过学校图书馆VPN访问知网/万方下载；")
    lines.append("英文论文可通过Sci-Hub、SSRN预印本或学校数据库获取。*\n")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"\n📋 手动下载清单已保存: {report_path}")


def print_summary(stats: dict, logger: logging.Logger):
    """打印下载统计摘要。"""
    logger.info(f"\n{'='*60}")
    logger.info("📊 下载统计摘要")
    logger.info(f"{'='*60}")
    logger.info(f"  ✅ 成功: {stats['success']}")
    logger.info(f"  ❌ 失败: {stats['failed']}")
    logger.info(f"  🔒 需手动: {stats['manual']}")
    logger.info(f"  ⏭️ 跳过: {stats['skipped']}")
    total = sum(stats.values())
    logger.info(f"  📦 总计: {total}")
    logger.info(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI入口
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="批量下载财务风险预警研究资源",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 下载所有资源
  python batch_download_resources.py --type all --output-dir ./downloads

  # 仅预览（不实际下载）
  python batch_download_resources.py --type all --dry-run

  # 仅下载学术论文
  python batch_download_resources.py --type paper --output-dir ./papers

  # 仅克隆GitHub仓库
  python batch_download_resources.py --type repo --output-dir ./repos

  # 使用自定义清单文件
  python batch_download_resources.py --catalog my_resources.csv --type all
        """
    )
    parser.add_argument(
        "--type", choices=["paper", "blog", "repo", "data", "all"],
        default="all", help="资源类型筛选 (默认: all)"
    )
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录 (默认: {DEFAULT_OUTPUT_DIR})"
    )
    parser.add_argument(
        "--catalog", default=DEFAULT_CATALOG,
        help=f"资源清单CSV路径 (默认: {DEFAULT_CATALOG})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式：仅显示将要执行的操作，不实际下载"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 初始化日志
    logger = setup_logging(args.output_dir)
    logger.info("🚀 财务风险预警研究资源批量下载工具 v1.0")
    logger.info(f"   清单文件: {args.catalog}")
    logger.info(f"   资源类型: {args.type}")
    logger.info(f"   输出目录: {args.output_dir}")
    logger.info(f"   预览模式: {'是' if args.dry_run else '否'}")

    # 读取并筛选资源清单
    try:
        all_records = load_catalog(args.catalog)
        logger.info(f"   清单记录数: {len(all_records)}")
    except FileNotFoundError:
        logger.error(f"❌ 清单文件不存在: {args.catalog}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 读取清单失败: {e}")
        sys.exit(1)

    records = filter_records(all_records, args.type)
    logger.info(f"   筛选后记录数: {len(records)}")

    if not records:
        logger.info("⚠️ 没有匹配的资源记录，退出")
        sys.exit(0)

    # 创建输出目录
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    # 执行下载
    stats, manual_list = process_records(records, args.output_dir, logger, args.dry_run)

    # 生成手动下载清单
    generate_manual_report(manual_list, args.output_dir, logger)

    # 打印统计摘要
    print_summary(stats, logger)

    logger.info("\n✨ 任务完成！")


if __name__ == "__main__":
    main()
