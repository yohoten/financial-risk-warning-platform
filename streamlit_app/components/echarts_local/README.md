# ECharts 本地组件（离线可用）

本目录是一个 **Streamlit 无构建自定义组件**，通过 `declare_component(path=...)` 加载，
前端用本地 `echarts.min.js` 渲染，**不依赖 CDN**，答辩断网也能用。

## 使用前：放入 echarts.min.js

仓库不包含 `echarts.min.js`（约 1 MB，第三方产物）。请任选一种方式：

```bash
# 联网机器下载 ECharts 5.5.1（固定版本，避免线上变更）
curl -L -o echarts.min.js \
  https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js
```

或从 https://echarts.apache.org/zh/download.html 下载后放到本目录，文件名必须为
`echarts.min.js`。

未放入该文件时，组件会显示红色提示，Python 侧的 `has_echarts()` 返回 `False`，
看板自动退回 Plotly 渲染，不影响其它功能。

## Python 侧调用

```python
from streamlit_app.utils import echarts_options as E

if E.has_echarts():
    E.render_echarts(E.industry_year_heatmap_option(scored), height=420, key="heatmap")
```

## 事件

组件会把 ECharts 事件（默认 `click`）回传为
`{"event": "<事件名>", "params": {...}}`，在 `st.session_state`/返回值中取用。
