"""evlab: independent, tamper-evident archive of frontier model behavior.

  python -m evlab run      --provider anthropic --model <id> [--samples 5]
  python -m evlab verify   runs/<run_id>
  python -m evlab diff     runs/<baseline> runs/<current>
  python -m evlab judge    runs/<run_id> --judge openrouter:openai/<model> --judge openrouter:google/<model>
  python -m evlab label    runs/<run_id> [runs/<other>] --out labels/<name>.jsonl
  python -m evlab calibrate labels/<name>.jsonl runs/<run_id>/judgments/<judgment_id> [...]
  python -m evlab report   runs/<current> [--baseline runs/<baseline>] [--scoring heuristic|<judgment_id>]
  python -m evlab timestamp runs/<run_id> [--tsa https://freetsa.org/tsr]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import urllib.request
from collections import defaultdict

from . import __version__
from .providers import build_provenance, get_provider, redact
from .record import RECORD_FORMAT, ChainWriter, keygen, sign_run, verify_sig, canonical, load_records, sha256_file, sha256_hex, utc_now, validate_id, verify_run, verify_tsr
from .judging import calibrate, check_comparable, judge_run, label_session, list_judgments, load_scored, verify_judgment
from .scoring import check_panel, heuristic_verdict, parse_judge_spec
from .stats import fisher_exact_two_sided, holm, wilson


BATTERY = os.path.join(os.path.dirname(__file__), "..", "probes", "battery_v0.json")
RUBRIC = os.path.join(os.path.dirname(__file__), "..", "probes", "judge_rubric_v2.json")


def load_env_file():
    """Read KEY=value lines from api_keys.env in the project folder (never overrides real env vars)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api_keys.env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v and not os.environ.get(k.strip()):
                os.environ[k.strip()] = v
            elif v and os.environ.get(k.strip()) != v:
                print(f"warning: {k.strip()} is already set in your shell and differs from api_keys.env; "
                      f"the shell value is used. Run `unset {k.strip()}` to use the file.", file=sys.stderr)


def load_battery(path):
    with open(path, encoding="utf-8") as f:
        b = json.load(f)
    return b, sha256_file(path)


def cmd_run(a):
    battery, battery_hash = load_battery(a.battery)
    prov = get_provider(a.provider, a.model, a.base_url, a.reasoning_effort)
    specs = judge_specs(a)
    if specs:  # fail before spending anything on the run
        check_panel(specs, a.provider, a.model, a.target_lab)
    started = utc_now()
    run_id = a.run_id or f"{started[:10]}_{a.provider}_{a.model}".replace(":", "-").replace("/", "-")
    validate_id(run_id, "run id")
    run_dir = os.path.join(a.out, run_id)
    if os.path.exists(run_dir):
        raise SystemExit(f"{run_dir} already exists. Runs are never overwritten; pass a new --run-id.")
    w = ChainWriter(os.path.join(run_dir, "records.jsonl"))
    probes = battery["probes"]
    total = len(probes) * a.samples
    print(f"Run {run_id}: {len(probes)} probes x {a.samples} samples = {total} calls", file=sys.stderr)
    done = 0
    for probe in probes:
        area_cfg = battery["areas"][probe["area"]]
        for s in range(a.samples):
            if hasattr(prov, "set_area"):
                prov.set_area(probe["area"], probe["id"])
            t0 = utc_now()
            try:
                text, raw, meta, req = prov.complete(probe.get("system"), probe["messages"], a.temperature, a.max_tokens, s)
                meta = dict(meta)
                provenance = meta.pop("provenance", None) or build_provenance(a.provider, raw, None, None)
                err = None
            except Exception as e:  # keep failures in the record; never silently drop
                text, raw, meta, req, err = "", None, {}, None, redact(str(e))
                provenance = build_provenance(a.provider, None, None, None)
                if "HTTP 401" in err or "HTTP 403" in err:
                    w.close()
                    raise SystemExit(f"Stopped: the API rejected the key ({err[err.find('HTTP'):][:160]}).\n"
                                     "Check api_keys.env, then test the key with the curl command in README.md.")
            verdict, vmeta = heuristic_verdict(text, area_cfg) if not err else ("error", {"method": "none"})
            w.append({
                "record_format": RECORD_FORMAT, "provenance": provenance,
                "run_id": run_id, "probe_id": probe["id"], "area": probe["area"], "sample": s,
                "probe_sha256": sha256_hex(canonical(probe)),
                "requested_model": a.model, "provider": a.provider, **{f"provider_{k}": v for k, v in meta.items()},
                "request": req, "sent_at": t0, "received_at": utc_now(),
                "response_text": text, "response_raw": raw, "error": err,
                "verdict": verdict, "verdict_detail": vmeta,
            })
            done += 1
            if done % 25 == 0 or done == total:
                print(f"  {done}/{total}", file=sys.stderr)
    w.close()
    print(file=sys.stderr)
    manifest = {
        "run_id": run_id, "harness": f"evlab {__version__}", "python": platform.python_version(),
        "battery_id": battery["battery_id"], "battery_version": battery["version"], "battery_sha256": battery_hash,
        "provider": a.provider, "requested_model": a.model, "samples_per_probe": a.samples,
        "temperature": a.temperature, "max_tokens": a.max_tokens,
        "record_format": RECORD_FORMAT, "judge": "heuristic regex (see battery file)",
        "simulated": a.provider == "simulated", "started_at": started, "finished_at": utc_now(),
        "n_records": w.count, "chain_head": w.prev, "records_sha256": sha256_file(os.path.join(run_dir, "records.jsonl")),
    }
    manifest["manifest_sha256"] = sha256_hex(canonical(manifest))
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote {run_dir}\n  chain head {w.prev}\n  manifest   {manifest['manifest_sha256']}")
    recs = load_records(os.path.join(run_dir, "records.jsonl"))
    cost = sum(((r.get("provider_usage") or {}).get("cost") or 0) for r in recs)
    errors = sum(1 for r in recs if r.get("error"))
    empty = sum(1 for r in recs if not r.get("error") and not (r.get("response_text") or "").strip())
    if cost:
        print(f"  cost       ${cost:.4f} (as reported by the provider)")
    if errors or empty:
        print(f"  warning    {errors} calls failed, {empty} came back empty (try a higher --max-tokens)")
    if specs:
        judge_run(run_dir, specs, a.rubric, a.battery, target_lab=a.target_lab)


def judge_specs(a) -> list[dict]:
    specs = [parse_judge_spec(s) for s in (getattr(a, "judge", None) or [])]
    if getattr(a, "judge_provider", None):
        if not a.judge_model:
            raise SystemExit("--judge-provider needs --judge-model")
        specs.append(parse_judge_spec(f"{a.judge_provider}:{a.judge_model}"))
    return specs


def cmd_judge(a):
    specs = judge_specs(a)
    if not specs:
        raise SystemExit("Name at least one judge with --judge provider:model (two from different labs is recommended).")
    if len(specs) == 1:
        print("note: a single judge is allowed, but a two-lab panel is recommended and the report will say only one was used.", file=sys.stderr)
    judge_run(a.run, specs, a.rubric, a.battery, name=a.name, max_tokens=a.max_tokens,
              reasoning_effort=a.reasoning_effort, target_lab=a.target_lab)


def cmd_label(a):
    label_session(a.runs, a.out, a.battery, a.rubric, per_area=a.per_area, seed=a.seed,
                  labeller=a.labeller or os.environ.get("USER", ""))


def fmt(x, nd=2):
    return "  -  " if x is None else f"{x:.{nd}f}"


def cmd_calibrate(a):
    c = calibrate(a.labels, a.judgments, out_path=a.out, gate=a.gate, min_n=a.min_n)
    judges = c["judges"]
    print(f"Calibration of {' + '.join(judges)} against {c['n_labels']} hand labels ({', '.join(c['labellers']) or 'unnamed'})")
    print(f"Gate: kappa >= {c['gate']['kappa']}, n >= {c['gate']['min_n']}, panel coverage >= {c['gate']['min_coverage']:.0%}\n")
    print(f"{'area':<14}{'n':>4} {'cover':>6} {'agree':>6} {'kappa':>6}  {'95% CI':<13} {'heur':>5} " + " ".join(f"{'J' + str(i + 1):>5}" for i in range(len(judges))) + "  gate")
    for area, s in list(c["areas"].items()) + [("OVERALL", c["overall"])]:
        ci = s["panel"]["kappa_ci95"]
        agree = s["panel"]["percent_agree"]
        print(f"{area:<14}{s['n_labelled']:>4} {s['coverage']:>6.0%} {(f'{agree:.0%}' if agree is not None else '-'):>6} {fmt(s['panel']['kappa']):>6}  "
              f"{(fmt(ci[0]) + '-' + fmt(ci[1])) if ci else '-':<13} {fmt(s['heuristic']['kappa']):>5} "
              + " ".join(f"{fmt(s['judges'][j]['kappa']):>5}" for j in judges)
              + ("  PASS" if s["gate_passed"] else "  below"))
    for i, j in enumerate(judges):
        print(f"  J{i + 1} = {j}")
    print("\nkappa = panel vs your labels (disputed records excluded; 'cover' is the share the panel agreed on).")
    print("agree = plain percent agreement. When almost every label is the same (say all pass), kappa can be low or 0 even at 97% agreement.")
    print(f"heur = the regex heuristic vs your labels. Wrote {c['path']}")


def cmd_verify(a):
    r = verify_run(a.run)
    if r["ok"]:
        print(f"VERIFIED  {r['n_records']} records, chain head {r['chain_head']}")
    else:
        print("FAILED")
        for p in r["problems"]:
            print("  -", p)
    bad = not r["ok"]
    for jdir in list_judgments(a.run):
        v = verify_judgment(jdir, a.run)
        name = os.path.basename(jdir)
        if v["ok"]:
            print(f"VERIFIED  judgment {name}: {v['n_records']} records, chain head {v['chain_head']}")
        else:
            bad = True
            print(f"FAILED    judgment {name}")
            for p in v["problems"]:
                print("  -", p)
    if getattr(a, "tsr", False):
        t = verify_tsr(a.run, a.tsa_ca)
        if t["ok"]:
            print(f"VERIFIED  timestamp token: genTime {t['gen_time']}, token SHA-256 {t['tsr_sha256']}, "
                  f"imprint = SHA-256(manifest.json) {t['imprint']}")
        else:
            bad = True
            print(f"FAILED    timestamp token (token SHA-256 {t['tsr_sha256']}, genTime {t['gen_time']})")
            print("  -", t["detail"])
    if getattr(a, "sig", False):
        g = verify_sig(a.run, a.pubkey)
        if g["ok"]:
            print(f"VERIFIED  manifest signature (ed25519), key SHA-256 {g['pubkey_sha256']}, signed {g['signed_at']}")
        else:
            bad = True
            print("FAILED    manifest signature")
            print("  -", g["detail"])
    if bad:
        sys.exit(1)


def cmd_keygen(a):
    priv, pub, fpr = keygen(a.out)
    print(f"Wrote {priv} (mode 0600, keep it secret and backed up)\n      {pub}\n  public key SHA-256 {fpr}")


def cmd_sign(a):
    r = sign_run(a.run, a.key, a.heads)
    print(f"Wrote {r['sig_path']}\n  public key SHA-256 {r['pubkey_sha256']}\n  appended chain head to {r['heads_path']} (post it publicly)")


def area_stats(records):
    s = defaultdict(lambda: defaultdict(int, {"pass": 0, "fail": 0, "unclear": 0, "error": 0}))
    for r in records:
        s[r["area"]][r["verdict"]] += 1
    return {k: dict(v) for k, v in s.items()}


def compute_diff(run_a, run_b, scoring="heuristic", calibration=None, warn=True):
    (ra, ia), (rb, ib) = load_scored(run_a, scoring, calibration), load_scored(run_b, scoring, calibration)
    for w in check_comparable(ia, ib):
        if warn:
            print(f"warning: {w}", file=sys.stderr)
    sa, sb = area_stats(ra), area_stats(rb)
    rows, pv = [], {}
    for area in sorted(set(sa) | set(sb)):
        A, B = sa.get(area, {}), sb.get(area, {})
        fa, na = A.get("fail", 0), A.get("fail", 0) + A.get("pass", 0)
        fb, nb = B.get("fail", 0), B.get("fail", 0) + B.get("pass", 0)
        p = fisher_exact_two_sided(fa, na - fa, fb, nb - fb)
        pv[area] = p
        rows.append({"area": area, "a_fail": fa, "a_n": na, "b_fail": fb, "b_n": nb,
                     "a_rate": fa / na if na else 0, "b_rate": fb / nb if nb else 0,
                     "a_ci": wilson(fa, na), "b_ci": wilson(fb, nb), "p": p,
                     "a_unclear": A.get("unclear", 0), "b_unclear": B.get("unclear", 0)})
    ph = holm(pv)
    for r in rows:
        r["p_holm"] = ph[r["area"]]
        r["flag"] = r["p_holm"] < 0.05 and r["b_rate"] > r["a_rate"]
        r["improved"] = r["p_holm"] < 0.05 and r["b_rate"] < r["a_rate"]
    return rows


def cmd_diff(a):
    for row in compute_diff(a.baseline, a.current, a.scoring, a.calibration):
        tag = "REGRESSION" if row["flag"] else ("improved" if row["improved"] else "")
        print(f"{row['area']:<14} {row['a_fail']:>3}/{row['a_n']:<3} -> {row['b_fail']:>3}/{row['b_n']:<3}  p_holm={row['p_holm']:.4f}  {tag}")


def cmd_report(a):
    from .report import build_report
    out = a.out or os.path.join(a.run, "evidence_packet.html")
    build_report(a.run, a.baseline, out, battery_path=a.battery, standalone=not a.fragment,
                 scoring=a.scoring, calibration=a.calibration)
    print(f"Wrote {out}")


def cmd_timestamp(a):
    """RFC 3161 trusted timestamp on the manifest (needs openssl with `ts`)."""
    man = os.path.join(a.run, "manifest.json")
    tsq, tsr = os.path.join(a.run, "manifest.tsq"), os.path.join(a.run, "manifest.tsr")
    subprocess.run(["openssl", "ts", "-query", "-data", man, "-sha256", "-cert", "-out", tsq], check=True)
    with open(tsq, "rb") as f:
        req = urllib.request.Request(a.tsa, data=f.read(), headers={"content-type": "application/timestamp-query"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(tsr, "wb") as out:
        out.write(resp.read())
    print(f"Wrote {tsr}. Verify with: openssl ts -verify -in {tsr} -data {man} -CAfile <tsa cacert.pem>")


def main(argv=None):
    load_env_file()
    ap = argparse.ArgumentParser(prog="evlab", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a probe battery and write a hash-chained record")
    r.add_argument("--provider", required=True, choices=["openrouter", "anthropic", "openai", "openai-compat", "simulated"])
    r.add_argument("--model", required=True)
    r.add_argument("--base-url", help="for openai-compat servers, e.g. http://localhost:11434/v1 (Ollama)")
    r.add_argument("--battery", default=BATTERY)
    r.add_argument("--samples", type=int, default=5)
    r.add_argument("--temperature", type=float, default=1.0)
    r.add_argument("--max-tokens", type=int, default=400)
    r.add_argument("--reasoning-effort", choices=["minimal", "low", "medium", "high"],
                   help="OpenRouter: cap thinking on reasoning models (keeps cost and length down)")
    r.add_argument("--judge", action="append", metavar="PROVIDER:MODEL[#LAB]",
                   help="judge the run right after it finishes (repeat for a panel; see `evlab judge`)")
    r.add_argument("--judge-provider", choices=["openrouter", "anthropic", "openai", "openai-compat"], help="older single-judge form")
    r.add_argument("--judge-model")
    r.add_argument("--target-lab", help="declare the target model's lab when it can't be inferred")
    r.add_argument("--rubric", default=RUBRIC)
    r.add_argument("--run-id")
    r.add_argument("--out", default="runs")
    r.set_defaults(fn=cmd_run)

    j = sub.add_parser("judge", help="score a finished run with a cross-lab judge panel (writes its own hash chain)")
    j.add_argument("run")
    j.add_argument("--judge", action="append", required=True, metavar="PROVIDER:MODEL[#LAB]",
                   help="e.g. openrouter:openai/gpt-5-mini; repeat for each judge. Add #lab if the lab can't be inferred")
    j.add_argument("--rubric", default=RUBRIC)
    j.add_argument("--battery", default=BATTERY)
    j.add_argument("--name", help="judgment id (default: judges + rubric)")
    j.add_argument("--max-tokens", type=int, default=600)
    j.add_argument("--reasoning-effort", choices=["minimal", "low", "medium", "high"], default="low")
    j.add_argument("--target-lab")
    j.set_defaults(fn=cmd_judge, judge_provider=None)

    lb = sub.add_parser("label", help="hand-label responses, blind to model and verdict, for calibration")
    lb.add_argument("runs", nargs="+")
    lb.add_argument("--out", required=True, help="labels file, e.g. labels/pv_2026-10.jsonl (appended to; resumable)")
    lb.add_argument("--per-area", type=int, default=40)
    lb.add_argument("--seed", type=int, default=0)
    lb.add_argument("--labeller")
    lb.add_argument("--battery", default=BATTERY)
    lb.add_argument("--rubric", default=RUBRIC)
    lb.set_defaults(fn=cmd_label)

    c = sub.add_parser("calibrate", help="agreement (Cohen's kappa) between a judge panel and your hand labels")
    c.add_argument("labels")
    c.add_argument("judgments", nargs="+", help="runs/<run_id>/judgments/<judgment_id> (one or more, same panel)")
    c.add_argument("--out", help="default calibrations/<judgment_id>.json")
    c.add_argument("--gate", type=float, default=0.8)
    c.add_argument("--min-n", type=int, default=20)
    c.set_defaults(fn=cmd_calibrate)

    v = sub.add_parser("verify", help="recompute every hash and check the chain (and any judgments)")
    v.add_argument("run")
    v.add_argument("--tsr", action="store_true", help="also verify manifest.tsr (RFC 3161) with openssl; needs --tsa-ca")
    v.add_argument("--tsa-ca", help="the timestamp authority's CA certificate file (pinned; e.g. freetsa.org cacert.pem)")
    v.add_argument("--sig", action="store_true", help="also verify manifest.sig (ed25519) with openssl; needs --pubkey")
    v.add_argument("--pubkey", help="public key file for --sig")
    v.set_defaults(fn=cmd_verify)

    k = sub.add_parser("keygen", help="create an ed25519 signing key pair (private key mode 0600)")
    k.add_argument("--out", help="directory for the keys (default ~/.evlab/keys; never inside runs/)")
    k.set_defaults(fn=cmd_keygen)

    sg = sub.add_parser("sign", help="sign a run's manifest and append its chain head to chain_heads.jsonl")
    sg.add_argument("run")
    sg.add_argument("--key", required=True, help="private key file from `evlab keygen`")
    sg.add_argument("--heads", help="chain heads file (default chain_heads.jsonl at the repo root)")
    sg.set_defaults(fn=cmd_sign)

    d = sub.add_parser("diff", help="compare failure rates between two runs (Fisher exact, Holm-corrected)")
    d.add_argument("baseline")
    d.add_argument("current")
    d.add_argument("--scoring", default="heuristic", help="'heuristic' or a judgment id present in both runs")
    d.add_argument("--calibration", help="calibration file (default: newest match in calibrations/)")
    d.set_defaults(fn=cmd_diff)

    p = sub.add_parser("report", help="write a self-contained HTML evidence packet")
    p.add_argument("run")
    p.add_argument("--baseline")
    p.add_argument("--battery", default=BATTERY)
    p.add_argument("--scoring", default="heuristic", help="'heuristic' or a judgment id")
    p.add_argument("--calibration")
    p.add_argument("--out")
    p.add_argument("--fragment", action="store_true", help="omit the <!doctype>/<html> wrapper (for hosts that add their own)")
    p.set_defaults(fn=cmd_report)

    t = sub.add_parser("timestamp", help="get an RFC 3161 trusted timestamp for a run manifest")
    t.add_argument("run")
    t.add_argument("--tsa", default="https://freetsa.org/tsr")
    t.set_defaults(fn=cmd_timestamp)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
