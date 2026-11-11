"""运行清单测试：数据/特征/参数/指标必须可追溯。"""

from __future__ import annotations

import json

from models.run_manifest import record_run


def test_manifest_records_provenance(tmp_path):
    manifest = record_run(
        run_type="test",
        params={"trials": 1},
        metrics={"auc": 0.9},
        threshold={"high": 0.2, "medium": 0.1},
        features=["roa", "debt_to_asset"],
        out_dir=tmp_path,
    )

    assert manifest["run_id"]
    assert manifest["features"]["n"] == 2
    assert manifest["threshold"] == {"high": 0.2, "medium": 0.1}
    assert manifest["git"]["commit"]
    assert (tmp_path / "run_manifest.json").exists()
    assert (tmp_path / "runs" / f"{manifest['run_id']}.json").exists()

    history = (tmp_path / "run_history.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(history[-1])["run_id"] == manifest["run_id"]
