import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  CutInput,
  Issue,
  PlanInput,
  ScenarioKey,
  SensitivityItemBrief,
  SensitivityPreview,
} from "../types";
import { g } from "../format";
import { cutFlagHint } from "./CutEditor";

interface Props {
  expId: number;
  plan: PlanInput;
  range: [number, number];
  /** 预览请求所依据方案的标识；方案变化后标识改变 => 旧预览标记为已过期。 */
  planSignature: string;
  onApply: (nextCuts: CutInput[], label: string) => void;
}

const SC: { key: ScenarioKey; label: string }[] = [
  { key: "down", label: "下调" },
  { key: "base", label: "原值" },
  { key: "up", label: "上调" },
];

function num(v: number | null | undefined, d = 2): string {
  return v === null || v === undefined || Number.isNaN(v) ? "—" : v.toFixed(d);
}

function deltaText(v: number | null): { text: string; cls: string } {
  if (v === null || v === undefined || Number.isNaN(v)) return { text: "—", cls: "" };
  if (Math.abs(v) < 1e-9) return { text: "0.00", cls: "zero" };
  return { text: `${v > 0 ? "+" : ""}${v.toFixed(2)}`, cls: v > 0 ? "pos" : "neg" };
}

const KIND_ZH = { front: "前缺口", inter: "中间缺口", tail: "尾缺口" } as const;

function rangeLabel(it: SensitivityItemBrief | null): string {
  if (!it) return "不存在";
  if (it.fully_outside_range) return "范围外（无数据）";
  if (it.partial_outside_range) return "部分越界";
  return "范围内";
}

export default function SensitivityPanel({ expId, plan, range, planSignature, onApply }: Props) {
  const [open, setOpen] = useState(false);
  const [cutIndex, setCutIndex] = useState(0);
  const [endpoint, setEndpoint] = useState<"start" | "end">("end");
  const [step, setStep] = useState(10);
  const [preview, setPreview] = useState<SensitivityPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sigAtLoad, setSigAtLoad] = useState<string | null>(null);
  const [applied, setApplied] = useState<ScenarioKey | null>(null);

  useEffect(() => {
    if (cutIndex >= plan.cuts.length) setCutIndex(Math.max(plan.cuts.length - 1, 0));
  }, [plan.cuts.length, cutIndex]);

  const run = async () => {
    if (plan.cuts.length === 0) return;
    setLoading(true);
    setError(null);
    setApplied(null);
    try {
      const p = await api.sensitivity(expId, {
        plan,
        cut_index: cutIndex,
        endpoint,
        step_c: step,
      });
      setPreview(p);
      setSigAtLoad(planSignature);
    } catch (e) {
      setError(`预览计算失败：${(e as Error).message}`);
      setPreview(null);
    } finally {
      setLoading(false);
    }
  };

  // 自动随选择/步长/方案刷新（打开状态下），并对过期方案做标记
  useEffect(() => {
    if (!open || plan.cuts.length === 0) return;
    if (cutIndex >= plan.cuts.length) return;
    const id = window.setTimeout(run, 200);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, expId, cutIndex, endpoint, step, planSignature]);

  const stale = preview !== null && sigAtLoad !== planSignature;

  const changedCuts = useMemo(
    () => (preview ? preview.cuts.filter((c) => c.yield_changed) : []),
    [preview]
  );
  const maxVolRow = useMemo(() => {
    if (!changedCuts.length) return null;
    return changedCuts.reduce((a, b) =>
      b.max_abs_volume_delta > a.max_abs_volume_delta ? b : a);
  }, [changedCuts]);
  const maxMassRow = useMemo(() => {
    if (!changedCuts.length) return null;
    const withMass = changedCuts.filter((c) => c.max_abs_mass_delta > 1e-9);
    if (!withMass.length) return null;
    return withMass.reduce((a, b) =>
      b.max_abs_mass_delta > a.max_abs_mass_delta ? b : a);
  }, [changedCuts]);
  const maxDeltaScale = maxVolRow?.max_abs_volume_delta || 1;

  const currentCut = plan.cuts[cutIndex];
  const selectedTemp = currentCut
    ? endpoint === "start" ? currentCut.start_temp_c : currentCut.end_temp_c
    : 0;
  const marginLow = Math.max(selectedTemp - range[0], 0);
  const marginHigh = Math.max(range[1] - selectedTemp, 0);

  const apply = (sc: ScenarioKey) => {
    if (!preview) return;
    const t = preview.apply.candidate_temps_c[sc];
    const next = plan.cuts.map((c) => ({ ...c }));
    for (const m of preview.apply.member_endpoints) {
      if (m.endpoint === "start") next[m.cut_index].start_temp_c = t;
      else next[m.cut_index].end_temp_c = t;
    }
    const label = `${preview.selection.cut_name} · ${
      endpoint === "start" ? "初馏点" : "终馏点"
    }${SC.find((x) => x.key === sc)?.label} → ${g(t)} ℃`;
    setApplied(sc);
    onApply(next, label);
  };

  return (
    <div className="sensitivity">
      <div className="sens-head" onClick={() => setOpen((v) => !v)} role="button" tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && setOpen((v) => !v)}>
        <span className="twisty">{open ? "▾" : "▸"}</span>
        <h3>切点测温误差敏感性预览（教学演示）</h3>
        <span className="sens-sub">
          选一个切点与扰动步长，对比 −ΔT / 原值 / +ΔT 三情景；预览不保存
        </span>
      </div>

      {open && (
        <div className="sens-body">
          <div className="sens-controls">
            <label>切点所在馏分
              <select value={cutIndex} onChange={(e) => setCutIndex(parseInt(e.target.value))}>
                {plan.cuts.map((c, i) => (
                  <option key={i} value={i}>
                    #{i + 1} {c.name}（{g(c.start_temp_c)}~{g(c.end_temp_c)} ℃）
                  </option>
                ))}
              </select>
            </label>
            <label>扰动哪个切点
              <select value={endpoint} onChange={(e) => setEndpoint(e.target.value as "start" | "end")}>
                <option value="start">初馏点（{currentCut ? g(currentCut.start_temp_c) : "—"} ℃）</option>
                <option value="end">终馏点（{currentCut ? g(currentCut.end_temp_c) : "—"} ℃）</option>
              </select>
            </label>
            <label>扰动步长 ΔT ℃
              <input type="number" min="0.1" step="1" value={Number.isFinite(step) ? step : ""}
                onChange={(e) => setStep(Math.max(0, parseFloat(e.target.value)))} />
            </label>
            <button className="btn" onClick={run} disabled={loading || plan.cuts.length === 0}>
              {loading ? "计算中…" : "刷新预览"}
            </button>
          </div>

          {currentCut && (
            <p className="hint">
              该切点距实测起点 {g(range[0])} ℃ 还可下调 <b>{g(marginLow)}</b> ℃；
              距实测终点 {g(range[1])} ℃ 还可上调 <b>{g(marginHigh)}</b> ℃。
              超过边界的情景会按现有规则<b>截断计产率并标明越界</b>，不外推、不虚构数值。
            </p>
          )}
          {error && <div className="banner error" style={{ margin: "6px 0" }}>{error}</div>}

          {preview && (
            <>
              {stale && (
                <div className="issue warning" style={{ margin: "6px 0" }}>
                  <span>⚠️</span>
                  <span>方案自预览后已修改，下表可能过期；正在自动刷新，或点「刷新预览」。</span>
                </div>
              )}

              {/* 物理切点成员说明 + 候选值带回 */}
              <MemberBar preview={preview} step={step} applied={applied} onApply={apply}
                range={range} />

              {/* 变化最大馏分提示 */}
              <div className="max-callouts">
                {changedCuts.length === 0 ? (
                  <span className="ok-line">三情景下各馏分产率均无变化（平台段或零宽切点）。</span>
                ) : (
                  <>
                    {maxVolRow && (
                      <span className="callout vol">
                        体积产率变化最大：<b>{maxVolRow.name}</b>
                        （±{g(preview.selection.step_c)} ℃ 内最大变化
                        {" "}{maxVolRow.max_abs_volume_delta.toFixed(2)} 个百分点）
                      </span>
                    )}
                    {maxMassRow && (
                      <span className="callout mass">
                        质量产率变化最大：<b>{maxMassRow.name}</b>
                        （{maxMassRow.max_abs_mass_delta.toFixed(2)} 个百分点）
                      </span>
                    )}
                  </>
                )}
              </div>

              {/* 逐馏分三情景表 */}
              <div className="table-wrap">
                <table className="sens-table">
                  <thead>
                    <tr>
                      <th rowSpan={2}>#</th>
                      <th rowSpan={2}>馏分</th>
                      <th colSpan={3}>体积产率 %</th>
                      <th colSpan={2}>体积差量</th>
                      <th colSpan={3}>质量产率 %</th>
                      <th colSpan={2}>质量差量</th>
                    </tr>
                    <tr>
                      <th>下调</th><th>原值</th><th>上调</th>
                      <th>下调 Δ</th><th>上调 Δ</th>
                      <th>下调</th><th>原值</th><th>上调</th>
                      <th>下调 Δ</th><th>上调 Δ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.cuts.map((c) => {
                      const isMaxVol = maxVolRow?.index === c.index;
                      const isMaxMass = maxMassRow?.index === c.index;
                      const dvD = deltaText(c.delta_down_volume_pct);
                      const dvU = deltaText(c.delta_up_volume_pct);
                      const dmD = deltaText(c.delta_down_mass_pct);
                      const dmU = deltaText(c.delta_up_mass_pct);
                      return (
                        <tr key={c.index}
                          className={[
                            c.is_perturbed ? "perturbed" : "",
                            c.shares_endpoint ? "shared" : "",
                            isMaxVol ? "max-vol" : "",
                          ].join(" ")}>
                          <td>{c.index + 1}</td>
                          <td className="cut-name">
                            {c.name}
                            {c.is_perturbed && <span className="tag-mini sel">被扰动</span>}
                            {c.shares_endpoint && <span className="tag-mini">同测温点</span>}
                            {isMaxVol && <span className="tag-mini vol">体积变化最大</span>}
                            {isMaxMass && <span className="tag-mini mass">质量变化最大</span>}
                            <Bar value={c.max_abs_volume_delta} scale={maxDeltaScale} />
                          </td>
                          <td>{num(c.scenarios.down.volume_yield_pct)}</td>
                          <td className="base">{num(c.scenarios.base.volume_yield_pct)}</td>
                          <td>{num(c.scenarios.up.volume_yield_pct)}</td>
                          <td className={dvD.cls}>{dvD.text}</td>
                          <td className={dvU.cls}>{dvU.text}</td>
                          <td>{num(c.scenarios.down.mass_yield_pct)}</td>
                          <td className="base">{num(c.scenarios.base.mass_yield_pct)}</td>
                          <td>{num(c.scenarios.up.mass_yield_pct)}</td>
                          <td className={dmD.cls}>{dmD.text}</td>
                          <td className={dmU.cls}>{dmU.text}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* 重叠 / 缺口 */}
              <div className="sens-cols">
                <div>
                  <h4>重叠三情景</h4>
                  {preview.overlaps.length === 0 ? (
                    <p className="ok-line">三情景均无重叠。</p>
                  ) : (
                    <table className="sens-mini">
                      <thead><tr><th>馏分对</th><th>下调</th><th>原值</th><th>上调</th></tr></thead>
                      <tbody>
                        {preview.overlaps.map((o, i) => (
                          <tr key={i} className={o.appears_or_disappears ? "warn-row" : ""}>
                            <td>{o.cut_a_name} × {o.cut_b_name}
                              {o.appears_or_disappears && <span className="tag-mini">出现/消失</span>}
                            </td>
                            {SC.map(({ key }) => (
                              <td key={key} className={o.scenarios[key] ? "" : "muted"}>
                                <b>{num(o.scenarios[key]?.volume_pct ?? null)}</b>
                                <span className="sub-range">{rangeLabel(o.scenarios[key])}</span>
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
                <div>
                  <h4>缺口三情景（体积 %）</h4>
                  {preview.gaps.length === 0 ? (
                    <p className="ok-line">三情景均无缺口。</p>
                  ) : (
                    <table className="sens-mini">
                      <thead><tr><th>缺口</th><th>下调</th><th>原值</th><th>上调</th></tr></thead>
                      <tbody>
                        {preview.gaps.map((gp, i) => (
                          <tr key={i} className={gp.appears_or_disappears ? "warn-row" : ""}>
                            <td>
                              {KIND_ZH[gp.kind]}
                              <span className="loc">
                                {[gp.after_cut, gp.before_cut].filter(Boolean).join("→") || "边界"}
                              </span>
                              {gp.appears_or_disappears && <span className="tag-mini">出现/消失</span>}
                            </td>
                            {SC.map(({ key }) => {
                              const it = gp.scenarios[key];
                              return (
                                <td key={key} className={it?.fully_outside_range ? "muted" : it ? "" : "muted"}>
                                  <b>{it?.fully_outside_range ? "无数据" : num(it?.volume_pct ?? null)}</b>
                                  <span className="sub-range">{rangeLabel(it)}</span>
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>

              {/* 闭合三情景 */}
              <ClosureTable preview={preview} />

              {/* 各情景数据提示（越界/密度缺失等），去重折叠 */}
              <ScenarioIssues preview={preview} />

              <p className="hint">{preview.note}</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Bar({ value, scale }: { value: number; scale: number }) {
  if (value <= 1e-9) return null;
  const w = Math.max(6, Math.min(100, (value / scale) * 100));
  return <span className="mini-bar"><span style={{ width: `${w}%` }} /></span>;
}

function MemberBar({ preview, step, applied, onApply, range }: {
  preview: SensitivityPreview;
  step: number;
  applied: ScenarioKey | null;
  onApply: (sc: ScenarioKey) => void;
  range: [number, number];
}) {
  const temps = preview.scenario_temps_c;
  const members = preview.selection.member_endpoints;
  const joined = members
    .map((m) => `#${m.cut_index + 1} ${m.cut_name}${m.endpoint === "start" ? "初" : "终"}`)
    .join("、");
  const scMeta: { key: ScenarioKey; label: string }[] = [
    { key: "down", label: `下调 ${g(step)} ℃` },
    { key: "base", label: "原值" },
    { key: "up", label: `上调 ${g(step)} ℃` },
  ];
  return (
    <div className="member-bar">
      <div className="member-info">
        被扰动的是同一物理测温点（{g(preview.selection.original_temp_c)} ℃），联动端点：
        <b>{joined}</b>
        {members.length > 1 && <span className="moved-note">连续切割共享该点，整体平移、不凭空产生重叠/缺口</span>}
      </div>
      <div className="candidates">
        {scMeta.map(({ key, label }) => {
          const b = preview.boundary.scenarios[key];
          return (
            <div key={key} className={`cand ${!b.in_range ? "oor" : ""} ${applied === key ? "applied" : ""}`}>
              <div className="cand-label">{label}</div>
              <div className="cand-temp">{g(temps[key])} ℃</div>
              {!b.in_range && (
                <div className="cand-oor">
                  ⚠️ {b.exceeds === "below" ? "低于" : "高于"}实测{
                    b.exceeds === "below" ? `起点 ${g(range[0])}` : `终点 ${g(range[1])}`
                  } ℃ {g(b.out_of_range_width_c)} ℃：
                  范围内截断计产率，越界部分无数据·不外推
                </div>
              )}
              <button className="btn tiny" onClick={() => onApply(key)}
                disabled={applied === key}>
                {applied === key ? "已带回编辑器" : "带回编辑器"}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ClosureTable({ preview }: { preview: SensitivityPreview }) {
  const t = preview.totals;
  const rows: { label: string; get: (x: typeof t.base) => string; ok?: boolean }[] = [
    { label: "名义合计 %（含重复计的重叠）", get: (x) => num(x.nominal_yield_pct) },
    { label: "并集产率 %", get: (x) => num(x.union_yield_pct) },
    { label: "重叠合计 %", get: (x) => num(x.overlap_pct) },
    { label: "范围内缺口合计 %", get: (x) => num(x.front_gap_pct + x.inter_gap_pct + x.tail_gap_pct) },
    { label: "体积闭合合计 %（应 = 100）", get: (x) => num(x.identity_sum_pct, 3) },
  ];
  return (
    <div>
      <h4>总量与闭合三情景</h4>
      <table className="sens-mini closure">
        <thead><tr><th>项目</th><th>下调</th><th>原值</th><th>上调</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{r.label}</td>
              {SC.map(({ key }) => <td key={key}>{r.get(t[key])}</td>)}
            </tr>
          ))}
          <tr className="strong">
            <td>体积闭合</td>
            {SC.map(({ key }) => (
              <td key={key} className={t[key].identity_ok ? "ok-cls" : "bad-cls"}>
                {t[key].identity_ok ? "✅ 100%" : "❌"}
              </td>
            ))}
          </tr>
          {t.base.mass && (
            <tr>
              <td>质量闭合（按密度换算）</td>
              {SC.map(({ key }) => {
                const m = t[key].mass as { identity_ok?: boolean; identity_sum_pct?: number | null } | null;
                return (
                  <td key={key} className={m?.identity_ok ? "ok-cls" : "warn-cls"}>
                    {m ? (m.identity_ok ? `✅ ${num(m.identity_sum_pct, 2)}%` : `⚠️ ${num(m.identity_sum_pct, 2)}%`) : "—"}
                  </td>
                );
              })}
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ScenarioIssues({ preview }: { preview: SensitivityPreview }) {
  const groups: { key: ScenarioKey; label: string; issues: Issue[] }[] = [
    { key: "down", label: "下调", issues: preview.issues.down },
    { key: "base", label: "原值", issues: preview.issues.base },
    { key: "up", label: "上调", issues: preview.issues.up },
  ];
  const relevant = groups
    .map((g0) => ({ ...g0, codes: new Set(g0.issues.map((i) => i.code)) }))
    .filter((g0) => g0.issues.some((i) =>
      ["out_of_range", "density_missing_segments", "mass_identity_mismatch",
        "residue_density_missing", "cut_zero_width", "loss_exceeds_unrecovered"].includes(i.code)));
  if (relevant.length === 0) return null;
  return (
    <div className="sens-issues">
      <h4>情景相关数据提示</h4>
      {relevant.map((g0) => (
        <div key={g0.key} className="sens-issue-group">
          <span className="sc-tag">{g0.label}</span>
          {g0.issues
            .filter((i) => ["out_of_range", "density_missing_segments", "mass_identity_mismatch",
              "residue_density_missing", "cut_zero_width", "loss_exceeds_unrecovered"].includes(i.code))
            .map((i, k) => (
              <span key={k} className={`mini-issue ${i.severity}`}>{i.message}</span>
            ))}
        </div>
      ))}
    </div>
  );
}
