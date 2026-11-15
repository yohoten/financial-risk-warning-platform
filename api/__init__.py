"""FastAPI 服务层：评分、解释、监控的 HTTP 接口。

薄封装：不复制业务逻辑，直接调用 ``models.predict`` / ``models.shap_analysis``
等领域模块；无状态、进程内缓存模型，见 ``services.py``。
"""
