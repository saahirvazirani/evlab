"""Self-contained HTML evidence packet (one file, no external requests needed
beyond optional web fonts)."""
from __future__ import annotations

import html
import json

from .record import verify_run

AREA_ORDER = ["sycophancy", "delusion", "minors", "self_honesty", "agent_scope"]

CSS = """
/* Layout: one reading column; a docket-style header, then numbered exhibits. */
:root{
  --paper:#f5f6f8; --sheet:#ffffff; --ink:#18212c; --muted:#5b6675; --rule:#d9dee5;
  --accent:#1f4fd1; --accent-soft:#e6ecfb; --bad:#b4232c; --bad-soft:#fbeaea; --good:#1d7a4a; --good-soft:#e5f4ec;
  --warn:#8a5a00; --warn-soft:#fff3d6;
  --f-display:"IBM Plex Sans Condensed","Arial Narrow",system-ui,sans-serif;
  --f-body:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --f-mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --paper:#0f141a; --sheet:#151c24; --ink:#e4e9ef; --muted:#9aa6b4; --rule:#2a3542;
  --accent:#7d9cff; --accent-soft:#1c2747; --bad:#ff7a80; --bad-soft:#3a1b1e; --good:#5fd39a; --good-soft:#15301f;
  --warn:#f0c060; --warn-soft:#3a2e12; color-scheme:dark}}
:root[data-theme="dark"]{
  --paper:#0f141a; --sheet:#151c24; --ink:#e4e9ef; --muted:#9aa6b4; --rule:#2a3542;
  --accent:#7d9cff; --accent-soft:#1c2747; --bad:#ff7a80; --bad-soft:#3a1b1e; --good:#5fd39a; --good-soft:#15301f;
  --warn:#f0c060; --warn-soft:#3a2e12; color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);font:15px/1.6 var(--f-body);margin:0;
  padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
.wrap{max-width:860px;margin:0 auto;padding-block:32px 64px;display:grid;gap:28px}
h1,h2,h3{font-family:var(--f-display);text-wrap:balance;line-height:1.15;margin:0}
h1{font-size:2rem;font-weight:600;letter-spacing:-.01em}
h2{font-size:1.25rem;font-weight:600;padding-bottom:6px;border-bottom:1px solid var(--rule)}
h3{font-size:1rem;font-weight:600}
p{margin:0;max-width:68ch}
section{display:grid;gap:14px;min-width:0}
.eyebrow{font:600 .72rem/1 var(--f-mono);letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.docket{display:grid;gap:10px;padding-bottom:18px;border-bottom:3px double var(--rule)}
.meta-line{font:.8rem/1.5 var(--f-mono);color:var(--muted);word-break:break-all}
.banner{background:var(--warn-soft);color:var(--warn);border:1px solid var(--warn);border-radius:6px;padding:12px 14px;font-weight:600}
.finding{font-size:1.08rem;max-width:62ch}
.seal{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap;background:var(--sheet);border:1px solid var(--rule);border-radius:6px;padding:14px 16px}
.seal .status{font:700 .78rem/1 var(--f-mono);letter-spacing:.1em;padding:7px 10px;border-radius:4px}
.ok{background:var(--good-soft);color:var(--good)} .bad{background:var(--bad-soft);color:var(--bad)}
.seal dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:0;min-width:0;flex:1}
.seal dt{color:var(--muted);font-size:.82rem}
.seal dd{margin:0;font:.8rem/1.5 var(--f-mono);word-break:break-all;min-width:0}
.tablewrap{overflow-x:auto;background:var(--sheet);border:1px solid var(--rule);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:.9rem;font-variant-numeric:tabular-nums}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--rule);vertical-align:middle;white-space:nowrap}
th{font:600 .72rem/1.2 var(--f-mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
tr:last-child td{border-bottom:0}
td:first-child{white-space:normal;min-width:180px}
code{overflow-wrap:anywhere;font-family:var(--f-mono);font-size:.88em}
.wrap>*{min-width:0}
td.num{text-align:right;font-family:var(--f-mono)}
.pill{display:inline-block;font:600 .72rem/1 var(--f-mono);padding:5px 8px;border-radius:999px;letter-spacing:.04em}
.pill.reg{background:var(--bad-soft);color:var(--bad)} .pill.imp{background:var(--good-soft);color:var(--good)} .pill.none{background:var(--accent-soft);color:var(--muted)}
svg text{fill:var(--muted);font:11px var(--f-mono)}
.exhibit{background:var(--sheet);border:1px solid var(--rule);border-radius:6px;display:grid;gap:10px;padding:16px;min-width:0}
.exhibit-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.tag{font:700 .72rem/1 var(--f-mono);letter-spacing:.1em;border:1.5px solid var(--ink);padding:5px 8px;border-radius:3px}
.turn{display:grid;gap:4px;min-width:0}
.turn .who{font:600 .7rem/1 var(--f-mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.turn .txt{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--paper);border-radius:4px;padding:10px 12px;font-size:.92rem}
.turn.resp .txt{border-left:3px solid var(--bad)}
.turn.resp.passv .txt{border-left-color:var(--good)}
.hash{font:.74rem/1.5 var(--f-mono);color:var(--muted);word-break:break-all}
.cert{background:var(--sheet);border:1px dashed var(--muted);border-radius:6px;padding:16px;display:grid;gap:10px;font-size:.92rem}
pre{margin:0;overflow-x:auto;background:var(--sheet);border:1px solid var(--rule);border-radius:6px;padding:12px 14px;font:.82rem/1.55 var(--f-mono)}
ul{margin:0;padding-left:20px;display:grid;gap:4px;max-width:68ch}
a{color:var(--accent)}
@media (max-width:520px){h1{font-size:1.6rem}.seal dl{grid-template-columns:1fr}}
"""

FONTS = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&family=IBM+Plex+Sans+Condensed:wght@600&family=IBM+Plex+Sans:wght@400;600&display=swap">'


def e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def pct(x: float) -> str:
    return f"{x*100:.0f}%"


def rate_svg(row) -> str:
    """Dot + 95% Wilson interval for baseline (hollow) and current (filled), on one 0-100% scale."""
    W, H, L, R = 160, 34, 6, 6
    x = lambda v: L + v * (W - L - R)
    a_lo, a_hi = row["a_ci"]; b_lo, b_hi = row["b_ci"]
    col = "var(--bad)" if row["flag"] else ("var(--good)" if row["improved"] else "var(--accent)")
    ticks = "".join(f'<line x1="{x(t):.1f}" y1="4" x2="{x(t):.1f}" y2="30" stroke="var(--rule)" stroke-width="1"/>' for t in (0, .25, .5, .75, 1))
    return (f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="baseline {pct(row["a_rate"])}, current {pct(row["b_rate"])}">{ticks}'
            f'<line x1="{x(a_lo):.1f}" y1="11" x2="{x(a_hi):.1f}" y2="11" stroke="var(--muted)" stroke-width="2"/>'
            f'<circle cx="{x(row["a_rate"]):.1f}" cy="11" r="4.5" fill="var(--sheet)" stroke="var(--muted)" stroke-width="2"/>'
            f'<line x1="{x(b_lo):.1f}" y1="23" x2="{x(b_hi):.1f}" y2="23" stroke="{col}" stroke-width="2"/>'
            f'<circle cx="{x(row["b_rate"]):.1f}" cy="23" r="4.5" fill="{col}"/></svg>')


def single_svg(k, n) -> str:
    from .stats import wilson
    W, H, L, R = 160, 22, 6, 6
    x = lambda v: L + v * (W - L - R)
    r = k / n if n else 0; lo, hi = wilson(k, n)
    ticks = "".join(f'<line x1="{x(t):.1f}" y1="3" x2="{x(t):.1f}" y2="19" stroke="var(--rule)"/>' for t in (0, .25, .5, .75, 1))
    return (f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="failure rate {pct(r)}">{ticks}'
            f'<line x1="{x(lo):.1f}" y1="11" x2="{x(hi):.1f}" y2="11" stroke="var(--accent)" stroke-width="2"/>'
            f'<circle cx="{x(r):.1f}" cy="11" r="4.5" fill="var(--accent)"/></svg>')


def exhibit(label, rec, battery) -> str:
    probe = next((p for p in battery["probes"] if p["id"] == rec["probe_id"]), {})
    turns = ""
    if probe.get("system"):
        turns += f'<div class="turn"><div class="who">System prompt given to model</div><div class="txt">{e(probe["system"])}</div></div>'
    for m in probe.get("messages", []):
        turns += f'<div class="turn"><div class="who">{e(m["role"])}</div><div class="txt">{e(m["content"])}</div></div>'
    cls = "resp passv" if rec["verdict"] == "pass" else "resp"
    turns += f'<div class="turn {cls}"><div class="who">Model response · verdict {e(rec["verdict"]).upper()}</div><div class="txt">{e(rec["response_text"])}</div></div>'
    detail = rec.get("verdict_detail", {})
    why = detail.get("reason") or ("matched: " + ", ".join(detail.get("matched_fail", []) + detail.get("matched_pass", [])) if detail.get("method") == "heuristic" else "")
    return (f'<article class="exhibit"><div class="exhibit-head"><span class="tag">EXHIBIT {e(label)}</span>'
            f'<h3>{e(rec["probe_id"])} · {e(rec["area"])}</h3></div>{turns}'
            f'<div class="hash">served model {e(rec.get("provider_served_model"))} · sent {e(rec.get("sent_at"))} · seq {e(rec["seq"])}<br>'
            f'record {e(rec["record_hash"])}<br>scoring {e(detail.get("method"))} {e(why)}</div></article>')


def scoring_text(info, m) -> str:
    if info["scoring"] == "heuristic":
        return e(m["judge"]) + '. Heuristic scores are reproducible but crude'
    jm = info["manifest"]
    judges = " and ".join(f'{e(j["id"])} ({e(j["lab"])})' for j in jm["judges"])
    one = " Only one judge was used, so there is no cross-check between labs." if len(jm["judges"]) == 1 else ""
    return (f'cross-lab LLM judge panel: {judges}, scoring a model from {e(jm["target_lab"])}, with rubric '
            f'<code>{e(jm["rubric_id"])}</code> v{e(jm["rubric_version"])} (SHA-256 <code>{e(jm["rubric_sha256"][:16])}…</code>). '
            f'A verdict counts only when every judge agrees and quotes the response accurately; otherwise it is "disputed".{one}')


def calibration_html(info) -> str:
    if info["scoring"] == "heuristic":
        return ""
    cal = info.get("calibration")
    if not cal:
        return ('<div class="banner">This judge panel has not been calibrated against hand labels yet. Treat judged verdicts '
                'as provisional until <code>evlab calibrate</code> shows agreement of kappa 0.8 or higher.</div>')
    rows = ""
    for area in AREA_ORDER:
        s = cal["areas"].get(area)
        if not s:
            continue
        k, ci = s["panel"]["kappa"], s["panel"]["kappa_ci95"]
        used = info["area_source"].get(area, "judge")
        pill = '<span class="pill imp">JUDGE</span>' if used == "judge" else '<span class="pill reg">HEURISTIC</span>'
        rows += (f'<tr><td>{e(area)}</td><td class="num">{s["n_labelled"]}</td><td class="num">{"-" if k is None else f"{k:.2f}"}</td>'
                 f'<td class="num">{"-" if not ci else f"{ci[0]:.2f}–{ci[1]:.2f}"}</td><td class="num">{s["coverage"]:.0%}</td><td>{pill}</td></tr>')
    g = cal["gate"]
    return (f'<p>Calibration against {cal["n_labels"]} hand labels ({e(", ".join(cal["labellers"]) or "unnamed labeller")}), made {e(cal["created_at"][:10])}. '
            f'An area is scored by the judge only when Cohen\'s kappa is at least {g["kappa"]}, with at least {g["min_n"]} labels and '
            f'{g["min_coverage"]:.0%} panel coverage; otherwise this packet falls back to the heuristic for that area.</p>'
            f'<div class="tablewrap"><table><thead><tr><th>Area</th><th>Labels</th><th>Kappa</th><th>95% CI</th><th>Coverage</th><th>Scored by</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def build_report(run_dir, baseline_dir, out_path, battery_path, standalone=True, scoring="heuristic", calibration=None):
    from .cli import compute_diff, area_stats
    from .judging import load_scored
    with open(battery_path, encoding="utf-8") as f:
        battery = json.load(f)
    cur = verify_run(run_dir)
    base = verify_run(baseline_dir) if baseline_dir else None
    m = cur["manifest"]
    recs, info = load_scored(run_dir, scoring, calibration)
    simulated = m.get("simulated") or (base and base["manifest"].get("simulated"))
    areas = battery["areas"]

    parts = []
    title = f"Evidence packet · {m['requested_model']}"
    parts.append(f'<title>Evidence Packet {e(m["requested_model"])}</title><meta name="claude:viewport-fit-sides" content="cover">{FONTS}<style>{CSS}</style><main class="wrap">')
    parts.append(f'<header class="docket"><span class="eyebrow">Independent behavior archive · {e(m["battery_id"])} v{e(m["battery_version"])}</span>'
                 f'<h1>{e(title)}</h1><div class="meta-line">run {e(m["run_id"])}<br>{e(m["started_at"])} → {e(m["finished_at"])} · {e(m["harness"])}</div></header>')
    if simulated:
        parts.append('<div class="banner">SIMULATED DEMO DATA. The models in this packet are fictional and every response was generated by the harness\'s simulator. Nothing here describes a real AI system.</div>')

    # Finding
    if base:
        rows = compute_diff(baseline_dir, run_dir, scoring, calibration, warn=False)
        flagged = [r for r in rows if r["flag"]]
        bm = base["manifest"]
        if flagged:
            f = ", ".join(f'{areas[r["area"]]["label"].split(":")[0].lower()} ({pct(r["a_rate"])} → {pct(r["b_rate"])}, Holm p = {r["p_holm"]:.2g})' for r in flagged)
            finding = f'Compared with the {e(bm["requested_model"])} baseline, {e(m["requested_model"])} fails significantly more often on {len(flagged)} of {len(rows)} behavior areas: {e(f)}.'
        else:
            finding = f'No behavior area shows a statistically significant increase in failures relative to the {e(bm["requested_model"])} baseline.'
    else:
        rows, flagged = None, []
        st = area_stats(recs)
        tot_f = sum(v["fail"] for v in st.values()); tot = sum(v["fail"] + v["pass"] for v in st.values())
        finding = f'{e(m["requested_model"])} failed {tot_f} of {tot} scored probe responses ({pct(tot_f/tot if tot else 0)}) across {len(st)} behavior areas.'
    parts.append(f'<section><span class="eyebrow">Finding</span><p class="finding">{finding}</p></section>')

    # Integrity
    def seal(v, name):
        st = '<span class="status ok">CHAIN VERIFIED</span>' if v["ok"] else '<span class="status bad">VERIFICATION FAILED</span>'
        probs = "".join(f"<li>{e(p)}</li>" for p in v["problems"])
        mm = v["manifest"]
        return (f'<div class="seal">{st}<dl><dt>Run</dt><dd>{e(name)}: {e(mm["run_id"])}</dd><dt>Records</dt><dd>{v["n_records"]}</dd>'
                f'<dt>Chain head</dt><dd>{e(v["chain_head"])}</dd><dt>records.jsonl SHA-256</dt><dd>{e(v["records_sha256"])}</dd>'
                f'<dt>Manifest SHA-256</dt><dd>{e(mm["manifest_sha256"])}</dd><dt>Battery SHA-256</dt><dd>{e(mm["battery_sha256"])}</dd></dl>'
                f'{"<ul>" + probs + "</ul>" if probs else ""}</div>')
    parts.append('<section><h2>Integrity</h2><p>Every response is stored with the hash of the record before it. Changing, removing or reordering any record breaks the chain, and <code>evlab verify</code> reports exactly where.</p>')
    if base:
        parts.append(seal(base, "Baseline"))
    parts.append(seal(cur, "Current"))
    if info["scoring"] != "heuristic":
        vj = info["verify"]
        st = '<span class="status ok">JUDGMENT VERIFIED</span>' if vj["ok"] else '<span class="status bad">VERIFICATION FAILED</span>'
        parts.append(f'<div class="seal">{st}<dl><dt>Judgment</dt><dd>{e(info["manifest"]["judgment_id"])}</dd><dt>Records</dt><dd>{vj["n_records"]}</dd>'
                     f'<dt>Chain head</dt><dd>{e(vj["chain_head"])}</dd><dt>Scores run</dt><dd>{e(info["manifest"]["run_chain_head"])}</dd></dl></div>')
    parts.append("</section>")

    # Results
    parts.append('<section><h2>Results by behavior area</h2>')
    if rows:
        parts.append('<p>Failure rate among scored responses, with 95% Wilson intervals. Hollow dot: baseline. Filled dot: current. Scale runs 0 to 100%. Changes are tested with Fisher\'s exact test, Holm-corrected across areas.</p><div class="tablewrap"><table><thead><tr><th>Behavior</th><th>Baseline</th><th>Current</th><th>0 — 100%</th><th>Holm p</th><th>Status</th></tr></thead><tbody>')
        for r in sorted(rows, key=lambda r: AREA_ORDER.index(r["area"]) if r["area"] in AREA_ORDER else 99):
            status = '<span class="pill reg">REGRESSION</span>' if r["flag"] else ('<span class="pill imp">IMPROVED</span>' if r["improved"] else '<span class="pill none">NO CHANGE</span>')
            parts.append(f'<tr><td>{e(areas[r["area"]]["label"])}</td><td class="num">{r["a_fail"]}/{r["a_n"]} · {pct(r["a_rate"])}</td>'
                         f'<td class="num">{r["b_fail"]}/{r["b_n"]} · {pct(r["b_rate"])}</td><td>{rate_svg(r)}</td><td class="num">{r["p_holm"]:.3g}</td><td>{status}</td></tr>')
    else:
        st = area_stats(recs)
        parts.append('<div class="tablewrap"><table><thead><tr><th>Behavior</th><th>Failed</th><th>Unclear / disputed</th><th>0 — 100%</th></tr></thead><tbody>')
        for a in AREA_ORDER:
            if a in st:
                k, n = st[a]["fail"], st[a]["fail"] + st[a]["pass"]
                parts.append(f'<tr><td>{e(areas[a]["label"])}</td><td class="num">{k}/{n} · {pct(k/n if n else 0)}</td><td class="num">{st[a]["unclear"] + st[a].get("disputed", 0) + st[a].get("judge_error", 0)}</td><td>{single_svg(k, n)}</td></tr>')
    parts.append('</tbody></table></div></section>')

    if info["scoring"] != "heuristic":
        parts.append('<section><h2>Judge calibration</h2>' + calibration_html(info) + '</section>')

    # Exhibits
    ex = []
    focus = [r["area"] for r in flagged] or AREA_ORDER
    letter = "A"
    for i, area in enumerate(focus[:3]):
        fails = [r for r in recs if r["area"] == area and r["verdict"] == "fail"]
        if not fails:
            continue
        ex.append(exhibit(f"{letter}-{i+1}", fails[0], battery))
        if base:
            brecs = load_scored(baseline_dir, scoring, calibration)[0]
            same = next((b for b in brecs if b["probe_id"] == fails[0]["probe_id"] and b["sample"] == fails[0]["sample"]), None)
            if same:
                ex.append(exhibit(f"{letter}-{i+1}B", same, battery).replace("EXHIBIT", "BASELINE"))
    if ex:
        parts.append('<section><h2>Exhibits</h2><p>Representative failing responses from the current run, each paired with the same probe and sample from the baseline. Every exhibit carries its record hash so it can be traced to the archive.</p>' + "".join(ex) + "</section>")

    # Methods
    parts.append(f'''<section><h2>Method and limits</h2><ul>
<li>{len(battery["probes"])} fixed probes across {len(areas)} areas, {m["samples_per_probe"]} samples each at temperature {m["temperature"]}. The battery file is hashed into every manifest, so a later run can prove it used the same tests.</li>
<li>Scoring: {scoring_text(info, m)}. "Unclear" and "disputed" verdicts are excluded from rates.</li>
<li>Public API access only. The record shows how the served model behaved on these probes on these dates. It does not show what happened in any particular user's conversation.</li>
<li>The model identifier is what the provider reported. No provider currently lets an outsider confirm which weights served a request.</li>
<li>No dangerous-capability probes are included.</li></ul></section>''')

    # Certification draft
    parts.append(f'''<section><h2>Draft certification</h2><div class="cert"><span class="eyebrow">Template · not legal advice · modeled on FRE 902(11) and 902(14)</span>
<p>I, [name], am a person qualified by [role/experience] to describe the process that produced these records. The records in run <code>{e(m["run_id"])}</code> were generated by an automated process that sends fixed probes to a model provider's public API and stores each request and response as received. Each record contains the SHA-256 hash of the record before it. The file <code>records.jsonl</code> has SHA-256 <code>{e(cur["records_sha256"])}</code>, which matches the value recorded at the end of the run. I certify under penalty of perjury that the foregoing is true and correct.</p>
<p>Signed: ____________________ &nbsp; Date: __________</p></div></section>''')

    parts.append(f'''<section><h2>Verify it yourself</h2><pre>python -m evlab verify runs/{e(m["run_id"])}
shasum -a 256 runs/{e(m["run_id"])}/records.jsonl   # expect {e(cur["records_sha256"][:16])}…</pre></section></main>''')

    doc = "".join(parts)
    if standalone:
        doc = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">' + doc + "</html>"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
