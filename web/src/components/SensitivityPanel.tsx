import { Fragment, useMemo, useState } from "react";
import { api } from "../api";
import type {
  PlanInput, SensitivityResult, SensitivityScenario,
} from "../types";
import { g } from "../format";
import { cutFlagHint } from "./CutEditor";

interface Props {
  expId: number;
  plan: PlanInput;
  range: [number, number];
  basis: "volume" | "mass";
  onApply: (cutIndex: number, endpoint: "start" | "end", temp: number) => void;
}

function fmt(v: number | null | undefined, d = 2) {
  return v === null || v === undefined || Number.isNaN(v) ? "—" : v.toFixed(d);
}

function fmtDelta(v: number | null | undefined) {
  if (v === null || v === undefined) return "Δ —";
  const s = v > 0 ? `+${v.toFixed(2)}` : v.toFixed(2);
  return `Δ ${s}`;
}

function sum3(a: number | null, b: number | null, c: number | null) {
  return a === null || b === null || c === null ? null : a + b + c;
}

/** 当前口径下变化最大的馏分（体积口径看体积增量，质量口径优先质量增量）。 */
function mostAffected(s: SensitivityScenario, basis: "volume" | "mass"): number | null {
  if (s.key === "base") return null;
  let best: number | null = null;
  let bestScore = 1e-9;
  for (const d of s.cut_deltas) {
    const v = basis === "mass"
      ? (d.mass_delta_pct ?? d.volume_delta_pct)
      : d.volume_delta_pct;
    const score = Math.abs(v ?? 0);
    if (score > bestScore) {
      bestScore = score;
      best = d.index;
    }
  }
  return best;
}

export default function SensitivityPanel({ expId, plan, range, basis, onApply }: Props) {
  const [cutIndex, setCutIndex] = useState(0);
  const [endpoint, setEndpoint] = useState<"start" | "end">("end");
  const [step, setStep] = useState(5);
  const [result, setResult] = useState<SensitivityResult | null>(null);
  const [snapshot, setSnapshot] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ci = Math.min(cutIndex, plan.cuts.length - 1);
  const cut = plan.cuts[ci];
  const requestKey = useMemo(
    () => JSON.stringify({ plan, cut_index: ci, endpoint, step_c: step }),
    [plan, ci, endpoint, step]
  );
  const stale = result !== null && snapshot !== requestKey;

  if (plan.cuts.length === 0) return null;

  const run = async () => {
    if (!Number.isFinite(step) || step <= 0) {
      setError("扰动步长需为大于 0 的温度（℃）");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const payload = { plan, cut_index: ci, endpoint, step_c: step };
      const r = await api.sensitivity(expId, payload);
      setResult(r);
      setSnapshot(JSON.stringify(payload));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const hasMass = result?.scenarios.some((s) => s.result.totals.mass !== null);

  return (
    <div className="editor sens">
      <h3>切点敏感性预览（单切点测温误差演示 · 只计算不保存）</h3>
      <div className="row">
        <label>馏分
          <select value={ci} onChange={(e) => setCutIndex(parseInt(e.target.value))}>
            {plan.cuts.map((c, i) => (
              <option key={i} value={i}>
                #{i + 1} {c.name}（{g(c.start_temp_c)}~{g(c.end_temp_c)} ℃）
              </option>
            ))}
          </select>
        </label>
        <label>切点
          <select value={endpoint} onChange={(e) => setEndpoint(e.target.value as "start" | "end")}>
            <option value="start">初馏点（{g(cut?.start_temp_c)} ℃）</option>
            <option value="end">终馏点（{g(cut?.end_temp_c)} ℃）</option>
          </select>
        </label>
        <label>扰动步长 ΔT ℃
          <input type="number" min="0.1" step="0.5" value={Number.isFinite(step) ? step : ""}
            onChange={(e) => setStep(parseFloat(e.target.value))} />
        </label>
        <button className="btn primary" onClick={run} disabled={loading}>
          {loading ? "计算中…" : "计算敏感性预览"}
        </button>
      </div>
      <p className="hint">
        对所选切点分别按 <b>下调 / 原值 / 上调</b> 三种情景重算各馏分体积与质量产率、
        重叠缺口与闭合结果；实测范围 {g(range[0])}~{g(range[1])} ℃ 之外<b>不外推</b>，
        越界情景会标明并按边界截断。预览不写入已保存方案。
      </p>
      {error && <div className="banner error">{error} <button onClick={() => setError(null)}>×</button></div>}
      {stale && (
        <p className="stale-note">⚠️ 编辑器内容已变化，以下为上次预览结果（未自动更新，也不会写入方案）。</p>
      )}

      {result && (
        <>
          <p className="sens-head">
            切点：<b>{result.cut_name} · {result.endpoint_label}</b>，
            原值 {g(result.original_temp_c)} ℃，扰动 ±{g(result.step_c)} ℃
            （实测范围 {g(result.applicable_range.temp_c[0])}~{g(result.applicable_range.temp_c[1])} ℃）
          </p>

          <table className="sens-table">
            <thead>
              <tr>
                <th rowSpan={2}>馏分</th>
                {result.scenarios.map((s) => (
                  <th key={s.key} colSpan={2} className={s.out_of_range ? "oor" : ""}>
                    {s.label} {g(s.temp_c)} ℃
                    {s.out_of_range && <span className="pill out_of_range">越界·已截断</span>}
                  </th>
                ))}
              </tr>
              <tr>
                {result.scenarios.map((s) => (
                  <Fragment key={s.key}><th>体积%</th><th>质量%</th></Fragment>
                ))}
              </tr>
            </thead>
            <tbody>
              {plan.cuts.map((c, idx) => {
                const most = result.scenarios.some((s) => mostAffected(s, basis) === idx);
                return (
                  <tr key={idx} className={most ? "most-row" : ""}>
                    <td>
                      {c.name}
                      {most && <span className="pill most">变化最大</span>}
                    </td>
                    {result.scenarios.map((s) => {
                      const row = s.result.cuts[idx];
                      const d = s.cut_deltas[idx];
                      const isMost = mostAffected(s, basis) === idx;
                      return (
                        <Fragment key={s.key}>
                          <td className={isMost ? "most" : ""}>
                            {fmt(row?.volume_yield_pct)}
                            {s.key !== "base" && (
                              <div className="delta">{fmtDelta(d?.volume_delta_pct)}</div>
                            )}
                          </td>
                          <td className={isMost ? "most" : ""}>
                            {fmt(row?.mass_yield_pct)}
                            {s.key !== "base" && (
                              <div className="delta">{fmtDelta(d?.mass_delta_pct)}</div>
                            )}
                            {row && row.flags.length > 0 && (
                              <div className="flags">
                                {row.flags.map((f) => (
                                  <span key={f} className={`pill ${f}`}>{cutFlagHint(f)}</span>
                                ))}
                              </div>
                            )}
                          </td>
                        </Fragment>
                      );
                    })}
                  </tr>
                );
              })}
              <tr className="apply-row">
                <td>把预览切点带回编辑器</td>
                {result.scenarios.map((s) => (
                  <td key={s.key} colSpan={2}>
                    {s.key === "base" ? (
                      <span className="muted">当前值</span>
                    ) : (
                      <button className="btn"
                        onClick={() => onApply(result.cut_index, result.endpoint, s.temp_c)}>
                        采用 {g(s.temp_c)} ℃
                      </button>
                    )}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
          {result.scenarios.filter((s) => s.range_note).map((s) => (
            <p key={s.key} className="range-note">⚠️ {s.label}情景：{s.range_note}</p>
          ))}

          <h4>重叠 / 缺口 / 闭合核对</h4>
          <table className="sens-totals">
            <thead>
              <tr>
                <th>核对项</th>
                {result.scenarios.map((s) => (
                  <th key={s.key}>{s.label} {g(s.temp_c)} ℃</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>重叠（体积%）</td>
                {result.scenarios.map((s) => (
                  <td key={s.key}>{fmt(s.result.totals.overlap_pct)}</td>
                ))}
              </tr>
              <tr>
                <td>缺口合计·前+中+尾（体积%）</td>
                {result.scenarios.map((s) => {
                  const t = s.result.totals;
                  return <td key={s.key}>{fmt(t.front_gap_pct + t.inter_gap_pct + t.tail_gap_pct)}</td>;
                })}
              </tr>
              <tr>
                <td>范围内未切出馏出液（体积%）</td>
                {result.scenarios.map((s) => (
                  <td key={s.key}>{fmt(s.result.totals.uncut_distillate_pct)}</td>
                ))}
              </tr>
              <tr>
                <td>闭合合计（应 = 100%）</td>
                {result.scenarios.map((s) => (
                  <td key={s.key} className={s.result.totals.identity_ok ? "ok" : "bad"}>
                    {fmt(s.result.totals.identity_sum_pct, 4)} {s.result.totals.identity_ok ? "✅" : "❌"}
                  </td>
                ))}
              </tr>
              {hasMass && (
                <>
                  <tr>
                    <td>重叠（质量%）</td>
                    {result.scenarios.map((s) => (
                      <td key={s.key}>{fmt(s.result.totals.mass?.overlap_pct)}</td>
                    ))}
                  </tr>
                  <tr>
                    <td>缺口合计·前+中+尾（质量%）</td>
                    {result.scenarios.map((s) => {
                      const m = s.result.totals.mass;
                      return (
                        <td key={s.key}>
                          {m ? fmt(sum3(m.front_gap_pct, m.inter_gap_pct, m.tail_gap_pct)) : "—"}
                        </td>
                      );
                    })}
                  </tr>
                  <tr>
                    <td>质量闭合合计</td>
                    {result.scenarios.map((s) => {
                      const m = s.result.totals.mass;
                      return (
                        <td key={s.key} className={m?.identity_ok ? "ok" : ""}>
                          {m ? `${fmt(m.identity_sum_pct, 4)} ${m.identity_ok ? "✅" : "⚠️"}` : "—"}
                        </td>
                      );
                    })}
                  </tr>
                </>
              )}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
