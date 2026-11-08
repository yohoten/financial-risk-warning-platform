# 财务风险预警研究资源批量下载工具

## 概述

本工具读取 [`resources_catalog.csv`](./resources_catalog.csv) 资源清单（**49 条**），
按资源类型自动选择最优获取策略，把文献、代码与数据入口一次性备齐。

| 资源类型 | 数量 | 自动处理方式 |
|---------|-----|-------------|
| `paper_en` 英文论文 | 22 | arXiv / NeurIPS / PMC 直链自动下载 PDF；付费文献打开浏览器下载页 |
| `paper_cn` 中文论文 | 11 | 生成手动清单（知网/万方需登录），并在浏览器中打开检索页 |
| `repo` 开源项目 | 6 | `git clone --depth 1` 浅克隆 |
| `blog` 技术文档 | 4 | 浏览器打开 |
| `data_platform` 数据平台 | 6 | 记入 `manual_download_list.md`（注册/订阅类） |

## 文件说明

| 文件 | 说明 |
|------|------|
| `batch_download_resources.py` | 主脚本（清单解析、URL 推导、下载、校验、报告） |
| `resources_catalog.csv` | 资源清单（10 字段：id / type / title / authors / year / journal_or_platform / url / download_channel / access_difficulty / notes） |
| `文献与资料调研清单.md` | 调研过程、优先级、获取状态与缺口说明 |
| `README_资源批量下载工具.md` | 本说明 |

## 环境要求

- Python ≥ 3.10
- `pip install requests tqdm`
- Git（克隆仓库时需要）

## 使用方法

```bash
cd docs

# 0. 先看清单（不联网，确认 49 条与分类是否正确）
python batch_download_resources.py --list

# 1. 预览：只打印将执行的操作
python batch_download_resources.py --dry-run

# 2. 下载全部开放获取论文
python batch_download_resources.py --type paper

# 3. 克隆参考实现（约 500 MB-1 GB）
python batch_download_resources.py --type repo --output-dir ./downloads

# 4. 只取答辩必引的几篇
python batch_download_resources.py --only-ids P01 P13 P14 P27 P28

# 5. 自定义输出目录与清单
python batch_download_resources.py --catalog my_catalog.csv --output-dir ../refs
```

### 参数一览

| 参数 | 可选值 | 默认 | 说明 |
|------|--------|------|------|
| `--type` | paper / blog / repo / data / all | all | 资源类型筛选（paper 含中英文） |
| `--output-dir` | 任意路径 | ./downloads | 输出目录 |
| `--catalog` | CSV 路径 | resources_catalog.csv | 资源清单 |
| `--dry-run` | flag | 关闭 | 预览模式，不发起下载与克隆 |
| `--list` | flag | 关闭 | 只打印清单概览后退出 |
| `--only-ids` | ID 列表 | 空 | 只处理指定 ID，如 `P13 P14 R05` |

## 输出结构

```
downloads/
├── papers/                      # 自动下载的 PDF（命名：{ID}_{标题}.pdf）
│   ├── P09_Financial Distress Prediction for SME.pdf
│   ├── P10_Why Do Tree-Based Models Still Outperform.pdf
│   ├── P13_A Unified Approach to Interpreting Model.pdf
│   └── ...
├── repos/                       # 浅克隆仓库
│   ├── shap/  streamlit/  BankruptcyPrediction/  ...
├── blogs/                       # 预留（博客以浏览器阅读为主）
├── manual_download_list.md      # 待手动获取清单（含推荐渠道）
└── download_log.txt             # 完整日志（时间/成功/失败/原因）
```

## 实现要点

1. **URL 推导**：arXiv `abs` → `pdf`；NeurIPS `hash/*-Abstract-Conference.html` → `file/*-Paper-Conference.pdf`；DOI 通过 HEAD 重定向探测是否为直链 PDF。
2. **有效性校验**：下载完成后检查文件头是否为 `%PDF-` 且体积 > 10 KB，否则判定为"登录页/反爬页"并删除，计入失败。
3. **断点续传**：目标文件已存在且体积合理则跳过，重复运行不会重复下载。
4. **失败重试**：指数退避重试 3 次，仍失败进入手动清单。
5. **日志可追溯**：控制台 + 文件双通道；Windows 控制台已强制 UTF-8，避免 emoji 乱码报错。

## 常见问题

**Q：部分论文下载失败？**
A：出版商页面需要登录。失败项会自动进入 `manual_download_list.md`，通过学校图书馆、SSRN 预印本或作者主页获取。

**Q：下载到的 PDF 只有几 KB？**
A：多为付费墙返回的登录页。脚本已做文件头校验并自动删除，不会留下坏文件。

**Q：`--list` 的中文显示乱码？**
A：Windows 终端需 UTF-8。使用 `chcp 65001` 或 Windows Terminal；脚本已主动 `reconfigure` 标准输出。

**Q：中文论文能自动下载吗？**
A：不能。知网/万方需登录认证，脚本只生成清单并打开检索页。建议校园网 VPN 访问。

**Q：克隆仓库太大？**
A：`--depth 1` 已裁剪历史；也可用 `--only-ids R05 R06` 只取 SHAP 与 Streamlit 两个核心仓库。

**Q：如何新增资源？**
A：在 `resources_catalog.csv` 追加一行（字段顺序不变），运行 `--list` 校验后即可被自动处理；同时建议在 `文献与资料调研清单.md` 登记用途与获取状态。

## 合规声明

本工具仅辅助获取**合法开放获取**的学术资源；付费文献请通过学校图书馆或正规渠道获取。
脚本不绕过任何付费墙、不模拟登录、不采集个人隐私数据。第三方仓库代码仅供参考，
直接复用前请核对其许可证。
