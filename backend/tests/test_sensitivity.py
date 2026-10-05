"""单切点敏感性预览测试：核心函数 + API 端到端。"""
from __future__ import annotations

import pytest

from app.curve import prepare_curve
from app.density import prepare_density
from app.planning import evaluate_plan
from app.sensitivity import sensitivity_preview


def pc(ts, rs):
    return prepare_curve([{"temp_c": t, "recovered_pct": r} for t, r in zip(ts, rs)])


def dens(rows):
    return prepare_density(
        [{"temp_c": t, "density_g_cm3": d} for t, d in rows]
    )


def _full_curve():
    return pc([10, 50, 100, 150, 200], [0, 25, 50, 75, 100])


def _make_evaluator(curve, d=None, feed=0.8, residue=0.95, loss=0.0, basis="mass"):
    def ev(cuts):
        return evaluate_plan(curve, cuts, loss_pct=loss, basis=basis,
                             density=d, feed_density=feed, residue_density=residue)
    return ev


# ---------- 扰动只影响相关馏分 ----------
def test_perturbation_only_affects_related_cuts():
    c = _full_curve()
    ev = _make_evaluator(c, dens([(10, 0.7), (200, 0.9)]))
    # 馏分间留缺口 => 没有共享物理切点，扰动只落到被选馏分
    cuts = [
        {"name": "a", "start_temp_c": 10, "end_temp_c": 80},
        {"name": "b", "start_temp_c": 100, "end_temp_c": 150},
        {"name": "cc", "start_temp_c": 160, "end_temp_c": 200},
    ]
    r = sensitivity_preview(
        evaluate=ev, cuts=cuts, cut_index=0, endpoint="end",
        step_c=10, temp_range=(c.t_min, c.t_max),
    )
    rows = {row["index"]: row for row in r["cuts"]}
    # 只有被扰动馏分 a 变化；其他馏分端点不共享该测温点，产率不动
    assert rows[0]["yield_changed"]
    assert rows[0]["delta_up_volume_pct"] > 0
    assert rows[0]["delta_down_volume_pct"] < 0
    assert rows[0]["delta_up_mass_pct"] is not None
    assert not rows[1]["shares_endpoint"] and not rows[1]["yield_changed"]
    assert not rows[2]["shares_endpoint"] and not rows[2]["yield_changed"]
    assert rows[1]["delta_up_volume_pct"] == 0
    assert rows[2]["delta_down_volume_pct"] == 0


def test_physical_cutpoint_moves_all_sharing_endpoints():
    # 连续切割 e_a == s_b == 100：同一测温点，成员端点整体平移
    c = _full_curve()
    ev = _make_evaluator(c, dens([(10, 0.7), (200, 0.9)]))
    cuts = [
        {"name": "a", "start_temp_c": 10, "end_temp_c": 100},
        {"name": "b", "start_temp_c": 100, "end_temp_c": 150},
        {"name": "cc", "start_temp_c": 150, "end_temp_c": 200},
    ]
    r = sensitivity_preview(
        evaluate=ev, cuts=cuts, cut_index=0, endpoint="end",
        step_c=10, temp_range=(c.t_min, c.t_max),
    )
    member_ids = {(m["cut_index"], m["endpoint"])
                  for m in r["selection"]["member_endpoints"]}
    assert member_ids == {(0, "end"), (1, "start")}
    rows = {row["index"]: row for row in r["cuts"]}
    assert rows[0]["yield_changed"] and rows[1]["yield_changed"]
    assert rows[1]["shares_endpoint"]
    # 第三个馏分与该切点无关
    assert not rows[2]["yield_changed"]
    # 连续关系不变：无重叠/缺口新出现；总量不变
    assert r["overlaps"] == []
    assert [g for g in r["gaps"] if g["appears_or_disappears"]] == []


def test_shared_endpoint_moves_neighbor_when_its_own_endpoint_perturbed():
    # 连续切割 e_a == s_b == 100；扰动 b 的“初馏点”即同一物理点：a 与 b 都变
    c = _full_curve()
    ev = _make_evaluator(c, dens([(10, 0.7), (200, 0.9)]))
    cuts = [
        {"name": "a", "start_temp_c": 10, "end_temp_c": 100},
        {"name": "b", "start_temp_c": 100, "end_temp_c": 200},
    ]
    r = sensitivity_preview(
        evaluate=ev, cuts=cuts, cut_index=1, endpoint="start",
        step_c=10, temp_range=(c.t_min, c.t_max),
    )
    rows = {row["index"]: row for row in r["cuts"]}
    assert rows[0]["shares_endpoint"] and rows[0]["yield_changed"]
    assert rows[1]["is_perturbed"] and rows[1]["yield_changed"]
    # b 初馏点上调 => b 产率减小、a 产率增大（同一测温点整体平移，
    # 连续切割关系不变：不产生重叠、也不产生缺口）
    assert rows[1]["delta_up_volume_pct"] < 0
    assert rows[0]["delta_up_volume_pct"] > 0
    assert r["overlaps"] == []
    assert r["gaps"] == []
    # 同一点两侧产率一增一减，名义合计与并集均不变
    t = r["totals"]
    assert t["up"]["nominal_yield_pct"] == t["base"]["nominal_yield_pct"]
    assert t["up"]["union_yield_pct"] == t["base"]["union_yield_pct"]
    assert t["down"]["nominal_yield_pct"] == t["base"]["nominal_yield_pct"]


# ---------- 重叠 / 缺口 / 闭合随情景变化 ----------
def test_overlap_appears_on_up_perturbation_decoupled_points():
    c = _full_curve()
    ev = _make_evaluator(c, None, basis="volume")
    # a.end=90 与 b.start=110 不是同一测温点：基准情景有中间缺口，
    # a 终点上调 30℃ 越过 110℃ => 重叠出现
    cuts = [
        {"name": "a", "start_temp_c": 10, "end_temp_c": 90},
        {"name": "b", "start_temp_c": 110, "end_temp_c": 200},
    ]
    r = sensitivity_preview(
        evaluate=ev, cuts=cuts, cut_index=0, endpoint="end",
        step_c=30, temp_range=(c.t_min, c.t_max),
    )
    # 成员只有 a.end 自己（90℃ 无其他端点共享）
    assert r["selection"]["member_endpoints"] == [
        {"cut_index": 0, "endpoint": "end", "cut_name": "a"}
    ]
    assert len(r["overlaps"]) == 1
    ov = r["overlaps"][0]
    assert ov["appears_or_disappears"]
    assert ov["scenarios"]["base"] is None and ov["scenarios"]["down"] is None
    assert ov["scenarios"]["up"]["volume_pct"] > 0
    # 中间缺口随收窄、在 up 情景被重叠取代
    inter = [g for g in r["gaps"] if g["kind"] == "inter"][0]
    assert inter["scenarios"]["down"]["volume_pct"] > inter["scenarios"]["base"]["volume_pct"]
    assert inter["scenarios"]["up"] is None
    t = r["totals"]
    assert t["up"]["overlap_pct"] > 0
    assert t["base"]["overlap_pct"] == 0
    # 体积闭合恒等式三情景始终成立
    assert all(t[s]["identity_ok"] for s in ("down", "base", "up"))
    assert all(t[s]["identity_sum_pct"] == pytest.approx(100.0, abs=1e-6)
               for s in ("down", "base", "up"))


def test_front_gap_disappears_when_cutpoint_moves_to_boundary():
    c = _full_curve()  # tmin=10
    ev = _make_evaluator(c, None, basis="volume")
    cuts = [{"name": "a", "start_temp_c": 20, "end_temp_c": 200}]
    r = sensitivity_preview(
        evaluate=ev, cuts=cuts, cut_index=0, endpoint="start",
        step_c=10, temp_range=(c.t_min, c.t_max),
    )
    front = [g for g in r["gaps"] if g["kind"] == "front"][0]
    assert front["appears_or_disappears"]
    # 下调试到 10℃（实测起点）=> 前缺口消失；基准/上调仍有
    assert front["scenarios"]["down"] is None
    assert front["scenarios"]["base"]["volume_pct"] > 0
    assert front["scenarios"]["up"]["volume_pct"] > front["scenarios"]["base"]["volume_pct"]


def test_continuous_cuts_perturb_together_no_new_overlap_or_gap():
    # 连续切割共享测温点时整体平移：不凭空产生重叠/缺口（物理一致性）
    c = _full_curve()
    ev = _make_evaluator(c, None, basis="volume")
    cuts = [
        {"name": "a", "start_temp_c": 10, "end_temp_c": 100},
        {"name": "b", "start_temp_c": 100, "end_temp_c": 200},
    ]
    r = sensitivity_preview(
        evaluate=ev, cuts=cuts, cut_index=0, endpoint="end",
        step_c=20, temp_range=(c.t_min, c.t_max),
    )
    assert r["overlaps"] == []
    assert [g for g in r["gaps"] if g["appears_or_disappears"]] == []


# ---------- 靠近测温边界：越界被标明而非虚构 ----------
def test_perturbation_beyond_range_is_marked_and_clipped():
    c = _full_curve()  # 10~200℃
    ev = _make_evaluator(c, None, basis="volume")
    cuts = [{"name": "a", "start_temp_c": 150, "end_temp_c": 200}]
    r = sensitivity_preview(
        evaluate=ev, cuts=cuts, cut_index=0, endpoint="end",
        step_c=30, temp_range=(c.t_min, c.t_max),
    )
    temps = r["scenario_temps_c"]
    assert temps == {"down": 170.0, "base": 200.0, "up": 230.0}
    up = r["boundary"]["scenarios"]["up"]
    assert not up["in_range"]
    assert up["exceeds"] == "above"
    assert up["out_of_range_width_c"] == 30.0
    assert "out_of_range" in up["cut_flags"]
    assert "clipped_to_range" in up["cut_flags"]
    # 越界情景的产率仍是范围内截断值（150~200℃），未虚构 200~230℃ 数值
    row = r["cuts"][0]
    assert row["scenarios"]["up"]["volume_yield_pct"] == pytest.approx(25.0, abs=1e-9)
    assert row["scenarios"]["base"]["volume_yield_pct"] == pytest.approx(25.0, abs=1e-9)
    # 尾缺口出现在 up 情景且完全范围外（无数据）
    tail = [g for g in r["gaps"] if g["kind"] == "tail"][0]
    assert tail["scenarios"]["up"]["fully_outside_range"]
    assert tail["scenarios"]["up"]["volume_pct"] is None
    # down/base 在界内
    assert r["boundary"]["scenarios"]["down"]["in_range"]
    assert r["boundary"]["scenarios"]["base"]["in_range"]
    # 适用范围声明不外推
    assert r["applicable_range"]["extrapolation"] == "none"


def test_perturbation_below_low_boundary_marked():
    c = pc([50, 100, 200], [5, 40, 90])  # 首点 50℃
    ev = _make_evaluator(c, None, basis="volume")
    cuts = [{"name": "a", "start_temp_c": 50, "end_temp_c": 100}]
    r = sensitivity_preview(
        evaluate=ev, cuts=cuts, cut_index=0, endpoint="start",
        step_c=15, temp_range=(c.t_min, c.t_max),
    )
    down = r["boundary"]["scenarios"]["down"]
    assert down["exceeds"] == "below"
    assert down["out_of_range_width_c"] == 15.0
    front = [g for g in r["gaps"] if g["kind"] == "front"][0]
    assert front["scenarios"]["down"]["fully_outside_range"]


# ---------- 候选值：带回后与正式 evaluate 一致 ----------
def test_apply_candidate_matches_fresh_evaluation():
    c = _full_curve()
    d = dens([(10, 0.7), (200, 0.9)])
    ev = _make_evaluator(c, d)
    cuts = [
        {"name": "a", "start_temp_c": 10, "end_temp_c": 100},
        {"name": "b", "start_temp_c": 100, "end_temp_c": 200},
    ]
    r = sensitivity_preview(
        evaluate=ev, cuts=cuts, cut_index=0, endpoint="end",
        step_c=20, temp_range=(c.t_min, c.t_max),
    )
    # 模拟前端把 up 候选温度带回编辑器：同一物理切点的全部成员端点一起采用
    applied = [dict(x) for x in cuts]
    new_temp = r["apply"]["candidate_temps_c"]["up"]
    for m in r["apply"]["member_endpoints"]:
        key = "end_temp_c" if m["endpoint"] == "end" else "start_temp_c"
        applied[m["cut_index"]][key] = new_temp
    fresh = ev(applied)
    # a.end 与 b.start 都到 120℃
    assert applied[0]["end_temp_c"] == 120.0
    assert applied[1]["start_temp_c"] == 120.0
    # 重新计算与 up 情景逐馏分一致
    for i in range(len(cuts)):
        pr = r["cuts"][i]["scenarios"]["up"]
        fr = fresh["cuts"][i]
        assert fr["volume_yield_pct"] == pr["volume_yield_pct"]
        assert fr["mass_yield_pct"] == pr["mass_yield_pct"]
    assert fresh["totals"]["identity_ok"]


# ---------- 不修改入参 ----------
def test_preview_does_not_mutate_input_cuts():
    c = _full_curve()
    ev = _make_evaluator(c, None, basis="volume")
    cuts = [{"name": "a", "start_temp_c": 10, "end_temp_c": 200}]
    import copy
    snapshot = copy.deepcopy(cuts)
    sensitivity_preview(
        evaluate=ev, cuts=cuts, cut_index=0, endpoint="end",
        step_c=20, temp_range=(c.t_min, c.t_max),
    )
    assert cuts == snapshot


# ---------- API ----------
def test_sensitivity_api_endpoint(client):
    client.post("/api/seed")
    exps = client.get("/api/experiments").json()
    # 示例A：范围 55~340℃，末切点 370 已越界
    aid = exps[0]["id"]
    payload = {
        "plan": {
            "name": "t", "basis": "volume", "loss_pct": 1.5,
            "cuts": [
                {"name": "轻石脑油", "start_temp_c": 55, "end_temp_c": 110},
                {"name": "重石脑油", "start_temp_c": 110, "end_temp_c": 185},
                {"name": "航煤", "start_temp_c": 185, "end_temp_c": 265},
                {"name": "柴油", "start_temp_c": 265, "end_temp_c": 370},
            ],
        },
        "cut_index": 0,
        "endpoint": "end",
        "step_c": 10,
    }
    r = client.post(f"/api/experiments/{aid}/sensitivity", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scenario_temps_c"] == {"down": 100.0, "base": 110.0, "up": 120.0}
    rows = {x["index"]: x for x in body["cuts"]}
    assert rows[0]["is_perturbed"] and rows[0]["yield_changed"]
    # 共享 110℃ 的重石脑油被标记相关
    assert rows[1]["shares_endpoint"]
    assert body["applicable_range"]["temp_c"] == [55.0, 340.0]
    # 所有情景体积闭合
    assert all(body["totals"][s]["identity_ok"] for s in ("down", "base", "up"))
    # apply 候选温度齐备
    assert body["apply"]["candidate_temps_c"]["up"] == 120.0


def test_sensitivity_api_boundary_case_example_a_last_cut(client):
    client.post("/api/seed")
    exps = client.get("/api/experiments").json()
    aid = exps[0]["id"]
    payload = {
        "plan": {
            "name": "t", "basis": "volume", "loss_pct": 0,
            "cuts": [{"name": "柴油", "start_temp_c": 265, "end_temp_c": 340}],
        },
        "cut_index": 0, "endpoint": "end", "step_c": 20,
    }
    body = client.post(f"/api/experiments/{aid}/sensitivity", json=payload).json()
    up = body["boundary"]["scenarios"]["up"]
    assert up["exceeds"] == "above" and up["out_of_range_width_c"] == 20
    # 越界不虚构：up 与 base 的范围内截断产率相同
    rows = body["cuts"][0]["scenarios"]
    assert rows["up"]["volume_yield_pct"] == rows["base"]["volume_yield_pct"]


def test_sensitivity_api_validates_cut_index(client):
    client.post("/api/seed")
    aid = client.get("/api/experiments").json()[0]["id"]
    payload = {
        "plan": {"name": "t", "basis": "volume", "loss_pct": 0,
                 "cuts": [{"name": "f", "start_temp_c": 55, "end_temp_c": 110}]},
        "cut_index": 5, "endpoint": "end", "step_c": 10,
    }
    assert client.post(f"/api/experiments/{aid}/sensitivity", json=payload).status_code == 422


def test_sensitivity_api_does_not_create_plan(client):
    client.post("/api/seed")
    exp = client.get("/api/experiments").json()[0]
    before = len(client.get(f"/api/experiments/{exp['id']}").json().get("plans", []))
    payload = {
        "plan": {"name": "t", "basis": "volume", "loss_pct": 0,
                 "cuts": [{"name": "f", "start_temp_c": 55, "end_temp_c": 110}]},
        "cut_index": 0, "endpoint": "end", "step_c": 10,
    }
    client.post(f"/api/experiments/{exp['id']}/sensitivity", json=payload)
    after = client.get(f"/api/experiments/{exp['id']}").json()["plans"]
    assert len(after) == before
