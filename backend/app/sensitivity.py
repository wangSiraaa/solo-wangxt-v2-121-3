"""单个切点测温误差的敏感性预览（只计算，不落库）。

给定方案中某个馏分的一个切点（初馏点或终馏点）与温度扰动步长 ΔT，
分别按 **下调（T−ΔT）/ 原值（T）/ 上调（T+ΔT）** 三种情景重新计算
整套结果：各馏分体积/质量产率、重叠、缺口与总量闭合，并给出相对原值
情景的逐馏分增量，供前端标出变化最大的馏分。

规则与主计算完全一致（复用 ``planning.evaluate_plan``）：

* 同一套 PCHIP 插值与密度换算——密度表覆盖不到的段不猜密度，
  质量增量照常按覆盖规则给出或留空；
* **严格不外推**：扰动后切点超出实测温度范围时，情景被明确标记
  ``out_of_range`` 并附说明，结果仍按现有截断规则计算（越界部分
  不计产率），不虚构范围外数值；
* 预览是只读计算，不写入任何已保存方案。
"""
from __future__ import annotations

from .curve import PreparedCurve
from .density import DensityModel
from .planning import evaluate_plan

_DELTA_TOL = 1e-9
_ENDPOINT_LABEL = {"start": "初馏点", "end": "终馏点"}
_SCENARIO_LABEL = {"down": "下调", "base": "原值", "up": "上调"}


def _delta(new: float | None, old: float | None) -> float | None:
    if new is None or old is None:
        return None
    return round(new - old, 4)


def _most_affected(cut_deltas: list[dict]) -> int | None:
    """按 |体积增量| 最大（并列时看 |质量增量|）取变化最大的馏分；全零返回 None。"""
    best_idx: int | None = None
    best_key: tuple[float, float] = (_DELTA_TOL, _DELTA_TOL)
    for d in cut_deltas:
        key = (
            abs(d["volume_delta_pct"] or 0.0),
            abs(d["mass_delta_pct"] or 0.0),
        )
        if key > best_key:
            best_key = key
            best_idx = d["index"]
    return best_idx


def evaluate_sensitivity(
    *,
    curve: PreparedCurve,
    density: DensityModel | None,
    feed_density: float | None,
    residue_density: float | None,
    cuts: list[dict],
    loss_pct: float,
    basis: str,
    cut_index: int,
    endpoint: str,
    step_c: float,
) -> dict:
    """对 ``cuts[cut_index]`` 的 ``endpoint`` 切点做 ±step_c 扰动预览。

    返回 ``scenarios``（down/base/up 三个完整计算结果 + 逐馏分增量），
    越界情景只标记、不虚构数值。
    """
    if not 0 <= cut_index < len(cuts):
        raise ValueError(f"cut_index {cut_index} 超出馏分数 {len(cuts)}")
    field = "start_temp_c" if endpoint == "start" else "end_temp_c"
    original = float(cuts[cut_index][field])
    tmin, tmax = curve.t_min, curve.t_max

    def run(temp: float) -> dict:
        perturbed = [dict(c) for c in cuts]
        perturbed[cut_index][field] = temp
        return evaluate_plan(
            curve=curve,
            cuts=perturbed,
            loss_pct=loss_pct,
            basis=basis,
            density=density,
            feed_density=feed_density,
            residue_density=residue_density,
        )

    base_result = run(original)
    scenarios: list[dict] = []
    for key, temp in (("down", original - step_c), ("base", original), ("up", original + step_c)):
        result = base_result if key == "base" else run(temp)
        out_of_range = temp < tmin or temp > tmax
        range_note = None
        if out_of_range:
            range_note = (
                f"扰动后切点 {temp:g} ℃ 超出实测温度范围 [{tmin:g}, {tmax:g}] ℃："
                "越界部分无数据、不外推，结果按范围边界截断计算（与主编辑器"
                "输入同样越界切点时的行为一致）"
            )
        cut_deltas = []
        for row, base_row in zip(result["cuts"], base_result["cuts"]):
            cut_deltas.append(
                {
                    "index": row["index"],
                    "name": row["name"],
                    "volume_delta_pct": _delta(
                        row["volume_yield_pct"], base_row["volume_yield_pct"]
                    ),
                    "mass_delta_pct": _delta(
                        row["mass_yield_pct"], base_row["mass_yield_pct"]
                    ),
                }
            )
        scenarios.append(
            {
                "key": key,
                "label": _SCENARIO_LABEL[key],
                "temp_c": round(temp, 6),
                "out_of_range": out_of_range,
                "range_note": range_note,
                "result": result,
                "cut_deltas": cut_deltas,
                "most_affected_cut_index": _most_affected(cut_deltas),
            }
        )

    return {
        "cut_index": cut_index,
        "cut_name": str(cuts[cut_index]["name"]),
        "endpoint": endpoint,
        "endpoint_label": _ENDPOINT_LABEL[endpoint],
        "original_temp_c": original,
        "step_c": step_c,
        "applicable_range": {"temp_c": [tmin, tmax], "extrapolation": "none"},
        "scenarios": scenarios,
    }
