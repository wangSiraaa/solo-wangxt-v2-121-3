"""单个切点温度扰动的敏感性预览（教学演示用）。

在**不改写、不保存**任何方案的前提下，对指定馏分的一个端点（初馏点 / 终馏点）
分别施加 −ΔT（下调）/ 0（原值）/ +ΔT（上调），用与正式计算**完全相同**的
``planning.evaluate_plan`` 计算三个情景，并整理为便于前端对比的结构：

* 逐馏分体积/质量产率的三情景值与差量，并标出受该切点影响的馏分
  （被扰动馏分本身，以及与其共享同一物理端点的相邻馏分）；
* 重叠 / 缺口明细的三情景对比（可能因扰动而新出现或消失，缺项记 None）；
* 总量与闭合结果的三情景对比（体积恒等式始终成立，质量闭合随密度覆盖变化）；
* **越界标注**：扰动后切点越过实测温度边界时，仍沿用不外推规则——范围内
  截断计产率，越界方向与越界宽度明确标出，绝不虚构范围外数值。

响应同时给出三个候选切点温度，供前端把其中一个预览值带回编辑器；带回后由
``/evaluate`` 按同一规则重新计算，结果与对应情景完全一致。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Callable

# (情景键, 扰动方向系数)
_SCENARIOS = (("down", -1.0), ("base", 0.0), ("up", 1.0))
_ENDPOINT_KEY = {"start": "start_temp_c", "end": "end_temp_c"}
_TOL = 1e-9


def _delta(a: float | None, b: float | None) -> float | None:
    """差量 a−b；任一缺数（None，如越界/缺密度）则不可比。"""
    if a is None or b is None:
        return None
    return round(a - b, 4)


def _row_brief(row: dict) -> dict:
    return {
        "start_temp_c": row["start_temp_c"],
        "end_temp_c": row["end_temp_c"],
        "flags": list(row["flags"]),
        "volume_yield_pct": row["volume_yield_pct"],
        "mass_yield_pct": row["mass_yield_pct"],
        "start_recovery_pct": row["start_recovery_pct"],
        "end_recovery_pct": row["end_recovery_pct"],
    }


def _gap_key(g: dict) -> tuple:
    """缺口在三情景间的同一标识：类型 + 两侧馏分名（预览中名称不被扰动）。"""
    return (g["kind"], g.get("after_cut"), g.get("before_cut"))


def _gap_brief(g: dict) -> dict:
    return {
        "from_temp_c": g["from_temp_c"],
        "to_temp_c": g["to_temp_c"],
        "width_c": g["width_c"],
        "volume_pct": g["volume_pct"],
        "mass_pct": g.get("mass_pct"),
        "partial_outside_range": g["partial_outside_range"],
        "fully_outside_range": g["fully_outside_range"],
    }


def _overlap_key(o: dict) -> tuple:
    return (o["cut_a"], o["cut_b"])


def _overlap_brief(o: dict) -> dict:
    return {
        "from_temp_c": o["from_temp_c"],
        "to_temp_c": o["to_temp_c"],
        "width_c": o["width_c"],
        "volume_pct": o["volume_pct"],
        "mass_pct": o.get("mass_pct"),
        "partial_outside_range": o["partial_outside_range"],
        "fully_outside_range": o["fully_outside_range"],
    }


# 总量中参与三情景对比的字段（体积基准）
_VOL_TOTAL_FIELDS = (
    "nominal_yield_pct", "union_yield_pct", "overlap_pct",
    "front_gap_pct", "inter_gap_pct", "tail_gap_pct",
    "uncut_distillate_pct", "light_unassigned_pct",
    "residue_bottoms_pct", "residue_bottoms_gross_pct", "residual_total_pct",
    "identity_sum_pct", "identity_residual_pct", "identity_ok",
)
_MASS_TOTAL_FIELDS = (
    "nominal_yield_pct", "union_yield_pct", "overlap_pct",
    "front_gap_pct", "inter_gap_pct", "tail_gap_pct",
    "uncut_distillate_pct", "light_unassigned_pct",
    "residue_bottoms_pct", "residue_bottoms_gross_pct", "residual_total_pct",
    "identity_sum_pct", "identity_ok", "identity_note",
)


def _totals_brief(totals: dict) -> dict:
    out = {k: totals.get(k) for k in _VOL_TOTAL_FIELDS}
    m = totals.get("mass")
    out["mass"] = None if m is None else {k: m.get(k) for k in _MASS_TOTAL_FIELDS}
    return out


def _find_members(cuts: list[dict], cut_index: int, endpoint: str
                  ) -> tuple[float, list[tuple[int, str]]]:
    """找出与被选端点处于**同一物理切点温度**的全部馏分端点。

    连续切割中相邻馏分共享端点（如 e_i == s_j == T）是同一测温点：
    该点的测温误差会同时移动这些端点，因此扰动作用于整个成员集合，
    而不是只改一个输入框（否则会凭空造出重叠/缺口）。零宽馏分
    （start == end）的两端天然是同一点，也一并纳入。
    返回 (原温度, [(馏分下标, 'start'|'end'), ...])。
    """
    orig = float(cuts[cut_index][_ENDPOINT_KEY[endpoint]])
    members: list[tuple[int, str]] = []
    for j, c in enumerate(cuts):
        for ep in ("start", "end"):
            if abs(float(c[_ENDPOINT_KEY[ep]]) - orig) <= _TOL:
                members.append((j, ep))
    # 被选端点必然在集合中；去重保序
    seen: set[tuple[int, str]] = set()
    uniq = [m for m in members if not (m in seen or seen.add(m))]
    return orig, uniq


def sensitivity_preview(
    *,
    evaluate: Callable[[list[dict]], dict],
    cuts: list[dict],
    cut_index: int,
    endpoint: str,
    step_c: float,
    temp_range: tuple[float, float],
) -> dict:
    """计算单切点扰动三情景预览。

    参数
    ~~~~
    evaluate: 给定切点列表返回完整 evaluate_plan 结果的闭包（曲线/密度/损失/
              口径均由调用方固定，保证与正式计算同规则）。
    cuts:     当前编辑器中的切点（不会被修改）。
    """
    tmin, tmax = temp_range
    orig_temp, members = _find_members(cuts, cut_index, endpoint)
    member_cuts = sorted({j for j, _ in members})
    other_key = _ENDPOINT_KEY["end" if endpoint == "start" else "start"]

    # ---- 三情景：同一物理切点的全部端点整体平移（严格不外推、密度规则不变）----
    results: dict[str, dict] = {}
    scenario_temps: dict[str, float] = {}
    for name, direction in _SCENARIOS:
        new_cuts = deepcopy(cuts)
        new_temp = orig_temp + direction * step_c
        for j, ep in members:
            new_cuts[j][_ENDPOINT_KEY[ep]] = new_temp
        scenario_temps[name] = new_temp
        results[name] = evaluate(new_cuts)

    # ---- 逐馏分产率对比 ----
    base_rows = results["base"]["cuts"]
    cut_compare: list[dict] = []
    for i, b in enumerate(base_rows):
        rows_by_s = {s: results[s]["cuts"][i] for s, _ in _SCENARIOS}
        dv_down = _delta(rows_by_s["down"]["volume_yield_pct"], b["volume_yield_pct"])
        dv_up = _delta(rows_by_s["up"]["volume_yield_pct"], b["volume_yield_pct"])
        dm_down = _delta(rows_by_s["down"]["mass_yield_pct"], b["mass_yield_pct"])
        dm_up = _delta(rows_by_s["up"]["mass_yield_pct"], b["mass_yield_pct"])
        changed_vol = any(x for x in (dv_down, dv_up) if x is not None and abs(x) > _TOL)
        changed_mass = any(x for x in (dm_down, dm_up) if x is not None and abs(x) > _TOL)
        cut_compare.append({
            "index": i,
            "name": b["name"],
            "is_perturbed": i == cut_index,
            "shares_endpoint": i in member_cuts and i != cut_index,
            "yield_changed": changed_vol or changed_mass,
            "max_abs_volume_delta": round(max(
                abs(x) for x in (dv_down, dv_up) if x is not None
            ), 4) if any(x is not None for x in (dv_down, dv_up)) else 0.0,
            "max_abs_mass_delta": round(max(
                abs(x) for x in (dm_down, dm_up) if x is not None
            ), 4) if any(x is not None for x in (dm_down, dm_up)) else 0.0,
            "scenarios": {
                s: _row_brief(rows_by_s[s])
                for s, _ in _SCENARIOS
            },
            "delta_down_volume_pct": dv_down,
            "delta_up_volume_pct": dv_up,
            "delta_down_mass_pct": dm_down,
            "delta_up_mass_pct": dm_up,
        })

    # ---- 重叠对比（按馏分对配对；扰动可能使重叠出现/消失）----
    overlap_map: dict[tuple, dict] = {}
    for s, _ in _SCENARIOS:
        for o in results[s]["overlaps"]:
            entry = overlap_map.setdefault(_overlap_key(o), {
                "cut_a": o["cut_a"], "cut_b": o["cut_b"],
                "cut_a_name": o["cut_a_name"], "cut_b_name": o["cut_b_name"],
                "scenarios": {},
            })
            entry["scenarios"][s] = _overlap_brief(o)
    overlap_compare = list(overlap_map.values())
    for entry in overlap_compare:
        entry["scenarios"] = {
            s: entry["scenarios"].get(s) for s, _ in _SCENARIOS
        }
        entry["appears_or_disappears"] = any(
            entry["scenarios"][s] is None for s, _ in _SCENARIOS
        )

    # ---- 缺口对比（按 类型+两侧馏分 配对）----
    gap_map: dict[tuple, dict] = {}
    for s, _ in _SCENARIOS:
        for gp in results[s]["gaps"]:
            k = _gap_key(gp)
            entry = gap_map.setdefault(k, {
                "kind": gp["kind"],
                "after_cut": gp.get("after_cut"),
                "before_cut": gp.get("before_cut"),
                "scenarios": {},
            })
            entry["scenarios"][s] = _gap_brief(gp)
    gap_compare = list(gap_map.values())
    for entry in gap_compare:
        entry["scenarios"] = {
            s: entry["scenarios"].get(s) for s, _ in _SCENARIOS
        }
        entry["appears_or_disappears"] = any(
            entry["scenarios"][s] is None for s, _ in _SCENARIOS
        )
    kind_order = {"front": 0, "inter": 1, "tail": 2}
    gap_compare.sort(key=lambda e: (kind_order[e["kind"]],
                                    str(e["after_cut"]), str(e["before_cut"])))

    # ---- 总量 / 闭合对比 ----
    totals_compare = {s: _totals_brief(results[s]["totals"]) for s, _ in _SCENARIOS}

    # ---- 越界标注：严格按实测范围判定，越界宽度单独给出，不外推 ----
    boundary_scenarios: dict[str, dict] = {}
    for s, temp in scenario_temps.items():
        below = max(tmin - temp, 0.0)
        above = max(temp - tmax, 0.0)
        if below > _TOL:
            exceeds, width = "below", below
        elif above > _TOL:
            exceeds, width = "above", above
        else:
            exceeds, width = None, 0.0
    # ---- 越界标注：严格按实测范围判定，越界宽度单独给出，不外推 ----
    boundary_scenarios: dict[str, dict] = {}
    for s, temp in scenario_temps.items():
        below = max(tmin - temp, 0.0)
        above = max(temp - tmax, 0.0)
        if below > _TOL:
            exceeds, width = "below", below
        elif above > _TOL:
            exceeds, width = "above", above
        else:
            exceeds, width = None, 0.0
        member_flags = {
            str(j): results[s]["cuts"][j]["flags"] for j in member_cuts
        }
        any_member_oor = any(
            "out_of_range" in f for fl in member_flags.values() for f in fl
        )
        boundary_scenarios[s] = {
            "temp_c": round(temp, 6),
            "in_range": exceeds is None,
            "exceeds": exceeds,  # "below" 低于实测起点 / "above" 高于实测终点
            "out_of_range_width_c": round(width, 4),
            "cut_flags": results[s]["cuts"][cut_index]["flags"],
            "member_cut_flags": member_flags,
            "any_member_out_of_range": any_member_oor,
            "clipped_range_c": results[s]["cuts"][cut_index]["clipped_range_c"],
            "has_blocking_errors": results[s]["has_blocking_errors"],
        }

    member_endpoints = [
        {"cut_index": j, "endpoint": ep, "cut_name": cuts[j]["name"]}
        for j, ep in members
    ]
    return {
        "selection": {
            "cut_index": cut_index,
            "cut_name": cuts[cut_index]["name"],
            "endpoint": endpoint,
            "original_temp_c": orig_temp,
            "endpoint_other_temp_c": float(cuts[cut_index][other_key]),
            "step_c": step_c,
            "member_endpoints": member_endpoints,
        },
        "applicable_range": {
            "temp_c": [tmin, tmax],
            "extrapolation": "none",
        },
        "scenario_temps_c": {s: round(t, 6) for s, t in scenario_temps.items()},
        "boundary": {
            "original_temp_c": orig_temp,
            "temp_range_c": [tmin, tmax],
            "scenarios": boundary_scenarios,
        },
        "cuts": cut_compare,
        "overlaps": overlap_compare,
        "gaps": gap_compare,
        "totals": totals_compare,
        "issues": {s: results[s]["issues"] for s, _ in _SCENARIOS},
        # 带回编辑器所需：同一物理切点的全部端点一起采用，重新计算与预览一致
        "apply": {
            "member_endpoints": member_endpoints,
            "candidate_temps_c": {s: round(t, 6) for s, t in scenario_temps.items()},
        },
        "note": (
            "预览仅按 evaluate 同规则临时计算，不写入已保存方案；连续切割共享的"
            "同一测温点整体平移；切点超出实测温度范围的部分一律不外推，"
            "只截断计产率并标明越界。"
        ),
    }
