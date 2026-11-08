# 财务风险预警研究资源批量下载工具

## 概述

本工具用于批量获取"上市公司财务风险智能预警平台"调研报告中引用的全部学术文献、技术博客和GitHub开源项目。它读取 `resources_catalog.csv` 资源清单，根据资源类型自动选择最优获取策略：

- **开放获取论文**（arXiv/NeurIPS/JSTOR等）→ 自动下载PDF
- **付费论文**（Elsevier/Springer等）→ 在浏览器中打开下载页面
- **中文论文**（知网/万方）→ 生成手动下载清单
- **GitHub仓库** → `git clone --depth 1` 浅克隆
- **技术博客** → 在浏览器中打开
- **数据平台** → 记录到手动清单

## 文件说明

| 文件 | 说明 |
|------|------|
| `batch_download_resources.py` | 主脚本，约350行Python代码 |
| `resources_catalog.csv` | 资源清单（32条记录，10个字段） |
| `requirements.txt` | Python依赖清单 |
| `README_资源批量下载工具.md` | 本使用说明 |

## 环境要求

- Python ≥ 3.10
- Git（用于克隆GitHub仓库）
- 网络连接

## 安装

```bash
# 1. 安装Python依赖
pip install -r requirements.txt

# 2. 确认Git已安装
git --version

# 3. 确认资源清单存在
ls resources_catalog.csv
```

## 使用方法

### 基本用法

```bash
# 下载所有资源到默认目录 ./downloads
python batch_download_resources.py

# 指定输出目录
python batch_download_resources.py --output-dir ./my_resources

# 预览模式（不实际下载，仅显示将执行的操作）
python batch_download_resources.py --dry-run
```

### 按类型筛选

```bash
# 仅下载学术论文（英文+中文）
python batch_download_resources.py --type paper

# 仅克隆GitHub仓库
python batch_download_resources.py --type repo

# 仅处理技术博客
python batch_download_resources.py --type blog

# 仅查看数据平台信息
python batch_download_resources.py --type data
```

### 使用自定义清单

```bash
# 使用自己的资源清单文件
python batch_download_resources.py --catalog my_custom_catalog.csv --type all
```

### 命令行参数一览

| 参数 | 可选值 | 默认值 | 说明 |
|------|--------|--------|------|
| `--type` | paper / blog / repo / data / all | all | 资源类型筛选 |
| `--output-dir` | 任意路径 | ./downloads | 输出目录 |
| `--catalog` | CSV文件路径 | resources_catalog.csv | 资源清单文件 |
| `--dry-run` | (flag) | 关闭 | 预览模式 |

## 输出结构

运行后生成的目录结构：

```
downloads/
├── papers/              # 自动下载的PDF论文
│   ├── P09_Financial Distress Prediction for SME.pdf
│   ├── P13_A Unified Approach to Interpreting Model.pdf
│   └── ...
├── repos/               # 克隆的GitHub仓库
│   ├── BankruptcyPrediction/
│   ├── Bankruptcy-Prediction/
│   ├── Financial_Dashboard/
│   └── FinBERT/
├── blogs/               # (预留) 博客保存目录
├── manual_download_list.md  # 待手动下载清单
└── download_log.txt     # 完整下载日志
```

## 资源清单格式

`resources_catalog.csv` 包含以下10个字段：

| 字段 | 说明 | 示例 |
|------|------|------|
| id | 资源唯一标识 | P01, B01, R01 |
| type | 资源类型 | paper_en / paper_cn / blog / repo / data_platform |
| title | 标题 | Financial Ratios, Discriminant Analysis... |
| authors | 作者 | Altman, E. I. |
| year | 年份 | 1968 |
| journal_or_platform | 期刊/平台 | The Journal of Finance |
| url | 链接 | https://doi.org/10.1111/... |
| download_channel | 推荐下载渠道 | Google Scholar / Sci-Hub |
| access_difficulty | 获取难度 | Easy / Medium / Hard |
| notes | 备注 | Classic Z-Score paper; open access |

## 常见问题

### Q: 部分论文下载失败怎么办？
A: 脚本会自动重试3次。仍失败的论文会被加入 `manual_download_list.md`，可通过Sci-Hub、学校数据库或SSRN预印本手动获取。

### Q: git clone失败？
A: 检查Git是否安装、网络是否通畅。国内用户可能需要配置代理或使用镜像站。

### Q: 如何添加新的资源？
A: 编辑 `resources_catalog.csv`，按相同格式添加新行即可。脚本会自动识别并处理。

### Q: 中文论文能自动下载吗？
A: 不能。知网/万方需要登录认证，脚本会将其加入手动清单并在浏览器中打开对应页面。建议通过学校图书馆VPN访问下载。

### Q: dry-run模式有什么用？
A: 预览模式下不会实际下载任何文件或克隆仓库，仅显示将要执行的操作。建议首次运行时先用 `--dry-run` 确认清单和参数正确。

## 注意事项

1. **版权合规**：本工具仅辅助获取合法开放获取的学术资源。付费论文请通过学校图书馆或正规渠道获取。
2. **请求频率**：脚本内置了请求间隔和重试延迟，请勿修改以避免触发反爬机制。
3. **网络环境**：部分资源（如arXiv、NeurIPS）在国内可能需要科学上网。
4. **磁盘空间**：4个GitHub仓库约需500MB-1GB空间；PDF论文总计约100-200MB。

## 许可证

本工具仅供学术研究使用。引用的学术论文版权归原作者和出版商所有。
