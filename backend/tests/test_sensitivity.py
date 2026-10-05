"""切点敏感性预览测试：扰动局部性、越界标记、预览-重算一致性。"""
from __future__ import annotations

import pytest

from app.curve import prepare_curve
from app.density import prepare_density
from app.planning import evaluate_plan
from app.sensitivity import evaluate_sensitivity


def pc(ts, rs):
    return prepare_curve([{"temp_c": t, "recovered_pct": r} for t, r in zip(ts, rs)])


def dens(rows):
    return prepare_density([{"temp_c": t, "density_g_cm3": d} for t, d in rows])


def sens(curve, cuts, cut_index, endpoint, step, **kw):
    return evaluate_sensitivity(
        curve=curve,
        density=kw.get("density"),
        feed_density=kw.get("feed_density"),
        residue_density=kw.get("residue_density"),
        cuts=cuts,
        loss_pct=kw.get("loss_pct", 0.0),
        basis=kw.get("basis", "volume"),
        cut_index=cut_index,
        endpoint=endpoint,
        step_c=step,
    )


def _full_curve():
    # 线性曲线 10~200℃，每 10℃ = 5 个体积点
    return pc([10, 60, 110, 160, 200], [0, 25, 50, 75, 95])


CUTS3 = [
    {"name": "轻", "start_temp_c": 10, "end_temp_c": 80},
    {"name": "中", "start_temp_c": 80, "end_temp_c": 150},
    {"name": "重", "start_temp_c": 150, "end_temp_c": 200},
]


# ---------- 结构 ----------
def test_three_scenarios_down_base_up():
    r = sens(_full_curve(), CUTS3, 1, "end", 10.0)
    assert [s["key"] for s in r["scenarios"]] == ["down", "base", "up"]
    assert [s["temp_c"] for s in r["scenarios"]] == [140.0, 150.0, 160.0]
    assert r["original_temp_c"] == 150.0
    assert r["endpoint_label"] == "终馏点"
    assert r["applicable_range"]["extrapolation"] == "none"
    base = r["scenarios"][1]
    assert all(
        d["volume_delta_pct"] == 0 for d in base["cut_deltas"]
    )
    assert base["most_affected_cut_index"] is None


# ---------- 验收 1：扰动只影响相关馏分 ----------
def test_perturbation_only_affects_related_cut():
    curve = _full_curve()
    r = sens(curve, CUTS3, 1, "end", 10.0)  # 扰动「中」的终馏点
    base = r["scenarios"][1]["result"]
    for s in (r["scenarios"][0], r["scenarios"][2]):
        res = s["result"]
        # 未扰动馏分产率完全不变
        for j in (0, 2):
            assert res["cuts"][j]["volume_yield_pct"] == base["cuts"][j]["volume_yield_pct"]
            assert res["cuts"][j]["mass_yield_pct"] == base["cuts"][j]["mass_yield_pct"]
        # 被扰动馏分按曲线增量变化（线性曲线：10℃ = 5 个体积点）
        delta = s["cut_deltas"][1]
        expect = -5.0 if s["key"] == "down" else 5.0
        assert delta["volume_delta_pct"] == pytest.approx(expect)
        assert s["most_affected_cut_index"] == 1
    # 终馏点上移侵入「重」馏分 => 出现重叠；下移 => 出现中间缺口
    up, down = r["scenarios"][2]["result"], r["scenarios"][0]["result"]
    assert up["totals"]["overlap_pct"] == pytest.approx(5.0)
    assert up["overlaps"][0]["cut_a"] == 1 and up["overlaps"][0]["cut_b"] == 2
    assert down["totals"]["inter_gap_pct"] == pytest.approx(5.0)
    # 三种情景闭合恒等式都成立
    for s in r["scenarios"]:
        assert s["result"]["totals"]["identity_ok"]


def test_perturb_start_endpoint():
    r = sens(_full_curve(), CUTS3, 1, "start", 10.0)
    down, up = r["scenarios"][0], r["scenarios"][2]
    # 初馏点下移 10℃：「中」多拿 5 个体积点，与「轻」重叠 5
    assert down["cut_deltas"][1]["volume_delta_pct"] == pytest.approx(5.0)
    assert down["result"]["totals"]["overlap_pct"] == pytest.approx(5.0)
    # 初馏点上移 10℃：「中」少 5 个，出现缺口
    assert up["cut_deltas"][1]["volume_delta_pct"] == pytest.approx(-5.0)
    assert up["result"]["totals"]["inter_gap_pct"] == pytest.approx(5.0)
    # 其它馏分不变
    assert up["cut_deltas"][0]["volume_delta_pct"] == 0
    assert up["cut_deltas"][2]["volume_delta_pct"] == 0


# ---------- 验收 2：越界情景被标明而非虚构数值 ----------
def test_out_of_range_scenario_marked_not_fabricated():
    curve = _full_curve()  # 实测 10~200℃
    cuts = [{"name": "尾", "start_temp_c": 150, "end_temp_c": 200}]
    r = sens(curve, cuts, 0, "end", 10.0)
    down, base, up = r["scenarios"]
    assert not down["out_of_range"] and not base["out_of_range"]
    assert up["out_of_range"] and up["range_note"]
    assert "不外推" in up["range_note"]
    row = up["result"]["cuts"][0]
    # 越界端点不给回收率数值（不虚构 R(210℃)）
    assert row["end_recovery_pct"] is None
    assert "out_of_range" in row["flags"] and "clipped_to_range" in row["flags"]
    # 产率只算到实测边界 200℃：与原值情景相同，没有任何外推增量
    assert row["volume_yield_pct"] == base["result"]["cuts"][0]["volume_yield_pct"]
    assert up["cut_deltas"][0]["volume_delta_pct"] == 0
    assert any(i["code"] == "out_of_range" for i in up["result"]["issues"])
    # 低温侧同理
    r2 = sens(curve, [{"name": "头", "start_temp_c": 10, "end_temp_c": 100}], 0, "start", 5.0)
    assert r2["scenarios"][0]["out_of_range"]
    assert r2["scenarios"][0]["result"]["cuts"][0]["start_recovery_pct"] is None


# ---------- 验收 3：预览值带回后重算与预览一致 ----------
def test_apply_back_recompute_matches_preview():
    curve = _full_curve()
    r = sens(curve, CUTS3, 1, "end", 10.0)
    for s in (r["scenarios"][0], r["scenarios"][2]):
        reapplied = [dict(c) for c in CUTS3]
        reapplied[1]["end_temp_c"] = s["temp_c"]
        again = evaluate_plan(curve=curve, cuts=reapplied, loss_pct=0.0, basis="volume")
        assert [c["volume_yield_pct"] for c in again["cuts"]] == [
            c["volume_yield_pct"] for c in s["result"]["cuts"]
        ]
        assert again["totals"] == s["result"]["totals"]


# ---------- 密度覆盖规则在预览中同样生效 ----------
def test_mass_deltas_follow_density_coverage():
    curve = _full_curve()
    d = dens([(10, 0.7), (110, 0.8), (200, 0.9)])
    r = sens(
        curve, CUTS3, 1, "end", 10.0,
        density=d, feed_density=0.8, residue_density=1.0, basis="mass",
    )
    up = r["scenarios"][2]
    # 质量增量 = 情景质量产率差，且与体积增量不同（密度 ≠ 进料密度）
    dm = up["cut_deltas"][1]["mass_delta_pct"]
    assert dm is not None and dm != pytest.approx(up["cut_deltas"][1]["volume_delta_pct"])
    row_up = up["result"]["cuts"][1]["mass_yield_pct"]
    row_base = r["scenarios"][1]["result"]["cuts"][1]["mass_yield_pct"]
    assert dm == pytest.approx(row_up - row_base, abs=1e-4)


def test_mass_delta_none_when_density_missing():
    curve = _full_curve()
    d = dens([(10, 0.7), (60, 0.75)])  # 密度表只覆盖低温段
    cuts = [{"name": "重", "start_temp_c": 150, "end_temp_c": 200}]
    r = sens(
        curve, cuts, 0, "start", 10.0,
        density=d, feed_density=0.8, residue_density=1.0, basis="mass",
    )
    # 扰动段完全缺密度 => 质量产率与增量都为 None，不猜密度
    for s in r["scenarios"]:
        assert s["result"]["cuts"][0]["mass_yield_pct"] is None
        assert s["cut_deltas"][0]["mass_delta_pct"] is None
        # 体积基准不受影响
        assert s["result"]["cuts"][0]["volume_yield_pct"] is not None


def test_invalid_cut_index_raises():
    with pytest.raises(ValueError):
        sens(_full_curve(), CUTS3, 5, "end", 10.0)
