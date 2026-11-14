# 版本快照目录

每次**口径变更、候选激活或论文定稿**前，把当前"特征层 + 模型层"的关键产物整批复制到这里，
用于回滚与答辩复核。目录本身被 `.gitignore` 排除（`data/versioned/*`），只保留本说明。

## 命名

```
<阶段>_<YYYYMMDD>/
```

| 阶段 | 含义 | 示例 |
|---|---|---|
| `pre_thesis` | 论文/答辩定稿前的可用版本 | `pre_thesis_20261114/` |
| `pre_fix` | 口径修正前（用于对比"改前/改后"） | `pre_fix_20261120/` |
| `release` | 对外交付/演示版本 | `release_20261130/` |

同一天多次快照可加序号：`pre_fix_20261120_b/`。

## 内容（建议最小集）

| 文件 | 说明 |
|---|---|
| `selected_features.json` | 入选特征清单（与模型强绑定） |
| `panel_model_input.parquet` | 建模输入（含 ID/标签/特征） |
| `panel_features.parquet` | 全量特征面板（可选，体积较大） |
| `labels_st.csv` / `legal_events.csv` / `digital_features.csv` | 本轮使用的关键契约表 |
| `xgboost_final.json` | 模型权重 |
| `calibrator.pkl` | 概率校准器 |
| `model_meta.json` / `metrics.json` | 元信息与指标 |

单份约 40 MB（parquet 占大头），保留 2–3 份即可。

## 保留策略

1. **至少保留两代**：最近一次 `release` 与上一代 `pre_*`，确保可回滚；
2. 每次口径/数据变更前必须新建快照，**不得覆盖**已有目录；
3. 超过 3 代且确认无需回滚的旧快照可删除（先确认 `runs/<run_id>/` 里仍有对应模型与指标）；
4. 快照只读：恢复时复制回 `data/feature_store/` 与 `models/artifacts/`，然后重跑
   `models.evaluate` / `models.shap_analysis`，**不要**在快照目录里直接训练。

## 恢复示例

```bash
cp data/versioned/pre_thesis_20261114/selected_features.json data/feature_store/
cp data/versioned/pre_thesis_20261114/panel_model_input.parquet data/feature_store/
cp data/versioned/pre_thesis_20261114/xgboost_final.json models/artifacts/
cp data/versioned/pre_thesis_20261114/calibrator.pkl models/artifacts/
cp data/versioned/pre_thesis_20261114/model_meta.json models/artifacts/
cp data/versioned/pre_thesis_20261114/metrics.json models/artifacts/
python -m scripts.check_data_readiness     # 必须 0 BLOCK
python -m models.evaluate && python -m models.shap_analysis
```

## 当前快照

| 目录 | 内容 | 备注 |
|---|---|---|
| `pre_thesis_20261114/` | 11 个文件：特征清单/面板/标签/司法/数字化/模型/校准器/指标 | 口径修正（官方折旧 + 带息债务）前的版本 |
