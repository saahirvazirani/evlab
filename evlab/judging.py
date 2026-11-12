"""Cross-lab judge panel, hand labels and calibration.

A judgment never edits a run. It is a second hash-chained file under
runs/<run_id>/judgments/<judgment_id>/ whose records point at the run's
records by seq and record_hash. Old runs stay verifiable, and any run can be
re-judged later by a different panel or rubric.
"""
from __future__ import annotations

import glob
import json
import os
import random
import re
import sys

from . import __version__
from .record import ChainWriter, validate_id, canonical, load_records, sha256_file, sha256_hex, utc_now, verify_run
from .scoring import AuthError, JudgeClient, check_panel, combine
from .stats import bootstrap_ci, cohen_kappa, confusion

JUDGMENT_FORMAT = 1
DEFINITE = ("pass", "fail", "unclear")
GATE_KAPPA = 0.8
GATE_COVERAGE = 0.8
GATE_MIN_N = 20


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")


def default_judgment_id(specs: list[dict], rubric: dict) -> str:
    return "+".join(slug(s["id"]) for s in specs) + "__" + slug(rubric["rubric_id"])


def _write_manifest(path: str, manifest: dict) -> dict:
    manifest["manifest_sha256"] = sha256_hex(canonical(manifest))
    with open(os.path.join(path, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def judge_run(run_dir: str, specs: list[dict], rubric_path: str, battery_path: str, name: str | None = None,
              max_tokens: int = 600, reasoning_effort: str | None = "low", target_lab: str | None = None) -> str:
    v = verify_run(run_dir)
    if not v["ok"]:
        raise SystemExit(f"Refusing to judge {run_dir}: the run does not verify ({v['problems'][0]}).")
    m = v["manifest"]
    if sha256_file(battery_path) != m["battery_sha256"]:
        raise SystemExit(f"{battery_path} is not the battery this run used (SHA-256 differs from the manifest).")
    with open(battery_path, encoding="utf-8") as f:
        battery = json.load(f)
    with open(rubric_path, encoding="utf-8") as f:
        rubric = json.load(f)
    if rubric.get("battery_id") != m["battery_id"]:
        raise SystemExit(f"Rubric {rubric.get('rubric_id')} is for {rubric.get('battery_id')}, but this run used {m['battery_id']}.")
    tlab = check_panel(specs, m["provider"], m["requested_model"], target_lab)
    clients = [JudgeClient(s, max_tokens, reasoning_effort) for s in specs]

    jid = validate_id(name, "judgment name") if name else default_judgment_id(specs, rubric)  # default ids are slugged ("+" joins judges)
    jdir = os.path.join(run_dir, "judgments", jid)
    if os.path.exists(jdir):
        raise SystemExit(f"{jdir} already exists. Judgments are never overwritten; pass --name to make a new one.")
    probes = {p["id"]: p for p in battery["probes"]}
    recs = load_records(os.path.join(run_dir, "records.jsonl"))
    w = ChainWriter(os.path.join(jdir, "records.jsonl"))
    started, stopped, offline = utc_now(), None, 0
    print(f"Judging {m['run_id']} with {', '.join(c.id for c in clients)}: {len(recs)} records", file=sys.stderr)
    try:
        for i, r in enumerate(recs):
            body = {"kind": "judgment", "format_version": JUDGMENT_FORMAT, "run_id": m["run_id"],
                    "target_seq": r["seq"], "target_record_hash": r["record_hash"], "probe_id": r["probe_id"],
                    "area": r["area"], "sample": r["sample"],
                    "heuristic_verdict": r["verdict"] if (r.get("verdict_detail") or {}).get("method") == "heuristic" else None}
            if r.get("error"):
                body.update(judges=[], verdict="error")
            else:
                area_cfg, rub = battery["areas"][r["area"]], rubric["areas"][r["area"]]
                results = [c.grade(probes[r["probe_id"]], r.get("response_text") or "", area_cfg, rub) for c in clients]
                body.update(judges=results, verdict=combine(results))
                down = all("unreachable" in (x.get("error") or "") for x in results)
                offline = offline + 1 if down else 0
            body["judged_at"] = utc_now()
            w.append(body)
            if (i + 1) % 25 == 0 or i + 1 == len(recs):
                print(f"  {i + 1}/{len(recs)}", file=sys.stderr)
            if offline >= 3:
                stopped = "stopped: the network was down for 3 records in a row; judge again once it is back"
                break
    except AuthError as e:
        stopped = f"stopped: a judge API rejected the key ({e})"
    finally:
        w.close()
    recs_j = load_records(os.path.join(jdir, "records.jsonl"))
    cost = sum(((a.get("response_raw") or {}).get("usage") or {}).get("cost") or 0
               for r in recs_j for j in r.get("judges", []) for a in j.get("attempts", []) if isinstance(a.get("response_raw"), dict))
    counts = {}
    for r in recs_j:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    _write_manifest(jdir, {
        "kind": "judgment", "format_version": JUDGMENT_FORMAT, "judgment_id": jid, "harness": f"evlab {__version__}",
        "run_id": m["run_id"], "run_chain_head": v["chain_head"], "run_records_sha256": v["records_sha256"],
        "run_n_records": v["n_records"], "target_provider": m["provider"], "target_model": m["requested_model"], "target_lab": tlab,
        "judges": [{"id": c.id, "lab": c.lab} for c in clients],
        "rubric_id": rubric["rubric_id"], "rubric_version": rubric["version"], "rubric_sha256": sha256_file(rubric_path),
        "combine": "unanimous verdict with a verified quote; anything else is 'disputed'",
        "temperature": 0.0, "max_tokens": max_tokens, "reasoning_effort": reasoning_effort,
        "simulated": bool(m.get("simulated")) or any(s["provider"] == "simulated" for s in specs),
        "started_at": started, "finished_at": utc_now(), "complete": stopped is None and w.count == v["n_records"],
        "stopped": stopped, "verdict_counts": counts, "judge_cost_usd": round(cost, 6),
        "n_records": w.count, "chain_head": w.prev, "records_sha256": sha256_file(os.path.join(jdir, "records.jsonl")),
    })
    if stopped:
        raise SystemExit(f"{stopped}\nPartial judgment kept at {jdir} (marked incomplete).")
    print(f"Wrote {jdir}\n  verdicts   {counts}")
    if cost:
        print(f"  judge cost ${cost:.4f} (as reported by the provider)")
    return jdir


def list_judgments(run_dir: str) -> list[str]:
    return sorted(d for d in glob.glob(os.path.join(run_dir, "judgments", "*")) if os.path.isdir(d))


def verify_judgment(jdir: str, run_dir: str | None = None) -> dict:
    """Verify a judgment's own chain, and that every record points at a real record of its run."""
    run_dir = run_dir or os.path.dirname(os.path.dirname(os.path.abspath(jdir)))
    v = verify_run(jdir)
    jm = v["manifest"]
    rv = verify_run(run_dir)
    if not rv["ok"]:
        v["problems"].append("the run this judgment scores does not verify")
    if jm.get("run_chain_head") != rv["chain_head"]:
        v["problems"].append("judgment was made for a different version of the run (chain head differs)")
    run_recs = load_records(os.path.join(run_dir, "records.jsonl"))
    for i, r in enumerate(load_records(os.path.join(jdir, "records.jsonl"))):
        s = r.get("target_seq")
        if not isinstance(s, int) or s >= len(run_recs) or run_recs[s]["record_hash"] != r.get("target_record_hash"):
            v["problems"].append(f"judgment {i}: does not point at a record in the run")
    if not jm.get("complete"):
        v["problems"].append("judgment is incomplete" + (f" ({jm.get('stopped')})" if jm.get("stopped") else ""))
    v["ok"] = not v["problems"]
    return v


# ---------------------------------------------------------------------------
# Scored records: what diff and report count
# ---------------------------------------------------------------------------
def find_calibration(jm: dict, path: str | None = None) -> dict | None:
    """The newest calibration for this judge panel and rubric, or None."""
    files = [path] if path else glob.glob(os.path.join("calibrations", "*.json"))
    best = None
    for p in files:
        try:
            with open(p, encoding="utf-8") as f:
                c = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if sorted(c.get("judges", [])) == sorted(j["id"] for j in jm["judges"]) and c.get("rubric_sha256") == jm["rubric_sha256"]:
            if not best or c["created_at"] > best["created_at"]:
                best = dict(c, path=p)
    if path and not best:
        raise SystemExit(f"{path} was made for a different judge panel or rubric.")
    return best


def load_scored(run_dir: str, scoring: str = "heuristic", calibration_path: str | None = None) -> tuple[list[dict], dict]:
    """Run records with `verdict` set by the chosen scoring. Judge scoring falls back to the heuristic,
    area by area, where a calibration exists and that area did not pass it."""
    recs = load_records(os.path.join(run_dir, "records.jsonl"))
    if scoring == "heuristic":
        return recs, {"scoring": "heuristic"}
    jdir = os.path.join(run_dir, "judgments", scoring)
    if not os.path.isdir(jdir):
        have = ", ".join(os.path.basename(d) for d in list_judgments(run_dir)) or "none"
        raise SystemExit(f"{run_dir} has no judgment '{scoring}' (has: {have}). Run `evlab judge` first.")
    vj = verify_judgment(jdir, run_dir)
    if not vj["ok"]:
        raise SystemExit(f"Judgment {jdir} does not verify: {vj['problems'][0]}")
    jm = vj["manifest"]
    cal = find_calibration(jm, calibration_path)
    source = {a: ("judge" if not cal or (cal["areas"].get(a) or {}).get("gate_passed") else "heuristic")
              for a in {r["area"] for r in recs}}
    judg = {j["target_seq"]: j for j in load_records(os.path.join(jdir, "records.jsonl"))}
    out = []
    for r in recs:
        j = judg[r["seq"]]
        r = dict(r)
        if r.get("error"):
            pass
        elif source[r["area"]] == "judge":
            r["verdict"] = j["verdict"]
            r["verdict_detail"] = {"method": "llm_judge_panel", "judgment_record": j["record_hash"],
                                   "reason": " | ".join(f"{x['judge']}: {str(x.get('verdict')).upper()}, {x.get('reason') or x.get('error') or ''}" for x in j["judges"])}
        elif j.get("heuristic_verdict"):
            r["verdict"] = j["heuristic_verdict"]
        out.append(r)
    return out, {"scoring": scoring, "judgment_dir": jdir, "verify": vj, "manifest": jm, "calibration": cal, "area_source": source}


def check_comparable(info_a: dict, info_b: dict) -> list[str]:
    """Refuse to compare runs scored differently. Returns warnings that don't block."""
    if info_a["scoring"] == "heuristic" and info_b["scoring"] == "heuristic":
        return []
    if info_a["scoring"] == "heuristic" or info_b["scoring"] == "heuristic":
        raise SystemExit("One run is scored by the heuristic and the other by a judge. Score both the same way.")
    ma, mb = info_a["manifest"], info_b["manifest"]
    if [j["id"] for j in ma["judges"]] != [j["id"] for j in mb["judges"]] or ma["rubric_sha256"] != mb["rubric_sha256"]:
        raise SystemExit("The two runs were scored by different judge panels or rubric versions, which would mix "
                         "judge drift with model drift. Re-judge both runs with the same panel and rubric.")
    if info_a["area_source"] != info_b["area_source"]:
        raise SystemExit("The two runs use different calibrations. Pass the same --calibration for both.")
    warn = []
    if abs(_days(ma["started_at"]) - _days(mb["started_at"])) > 7:
        warn.append(f"The two judgments were made {abs(_days(ma['started_at']) - _days(mb['started_at'])):.0f} days apart. "
                    "Judge models can change too; re-judge both runs together for the cleanest comparison.")
    return warn


def _days(ts: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() / 86400


# ---------------------------------------------------------------------------
# Hand labels
# ---------------------------------------------------------------------------
def load_labels(path: str) -> dict[str, dict]:
    """record_hash -> label record (the last label for a record wins)."""
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                out[r["record_hash"]] = r
    return out


def label_session(run_dirs: list[str], out_path: str, battery_path: str, rubric_path: str, per_area: int = 40,
                  seed: int = 0, labeller: str = "", inp=input, say=print) -> int:
    """Show responses one at a time, blind to model and verdict, and append hand labels to out_path."""
    with open(battery_path, encoding="utf-8") as f:
        battery = json.load(f)
    with open(rubric_path, encoding="utf-8") as f:
        rubric = json.load(f)
    probes = {p["id"]: p for p in battery["probes"]}
    done = load_labels(out_path)
    pool: dict[str, list] = {}
    for d in run_dirs:
        if not verify_run(d)["ok"]:
            raise SystemExit(f"{d} does not verify; refusing to label from it.")
        m = json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8"))
        for r in load_records(os.path.join(d, "records.jsonl")):
            if not r.get("error") and (r.get("response_text") or "").strip() and r["record_hash"] not in done:
                pool.setdefault(r["area"], []).append((m, r))
    rng = random.Random(seed)
    queue = []
    for area, items in sorted(pool.items()):
        have = sum(1 for x in done.values() if x["area"] == area)
        rng.shuffle(items)
        queue += items[:max(0, per_area - have)]
    rng.shuffle(queue)
    if not queue:
        say("Nothing left to label.")
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    n = 0
    keys = {"p": "pass", "f": "fail", "u": "unclear"}
    with open(out_path, "a", encoding="utf-8") as f:
        for i, (m, r) in enumerate(queue):
            probe, rub = probes[r["probe_id"]], rubric["areas"][r["area"]]
            say("\n" + "=" * 72)
            say(f"[{i + 1}/{len(queue)}]  {battery['areas'][r['area']]['label']}")
            say(f"  FAIL if: {rub['fail']}\n  PASS if: {rub['pass']}")
            say("-" * 72)
            if probe.get("system"):
                say(f"SYSTEM: {probe['system']}")
            for msg in probe["messages"]:
                say(f"{msg['role'].upper()}: {msg['content']}")
            say(f"\nRESPONSE:\n{r['response_text']}\n")
            while True:
                try:
                    a = inp("p = pass, f = fail, u = unclear, s = skip, q = quit > ").strip().lower()
                except EOFError:
                    a = "q"
                if a in keys or a in ("s", "q"):
                    break
            if a == "q":
                break
            if a == "s":
                continue
            f.write(json.dumps({"record_hash": r["record_hash"], "run_id": m["run_id"], "seq": r["seq"],
                                "probe_id": r["probe_id"], "area": r["area"], "label": keys[a],
                                "labeller": labeller, "labelled_at": utc_now()}) + "\n")
            f.flush()
            n += 1
    say(f"\nSaved {n} labels to {out_path} ({len(done) + n} in total).")
    return n


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------
def _agreement(pairs):
    k = cohen_kappa(pairs)
    ci = bootstrap_ci(pairs, cohen_kappa)
    tp = sum(1 for a, b in pairs if a == "fail" and b == "fail")
    fail_labels = sum(1 for a, _ in pairs if a == "fail")
    fail_calls = sum(1 for _, b in pairs if b == "fail")
    return {"n": len(pairs), "kappa": k, "kappa_ci95": ci,
            "percent_agree": (sum(1 for a, b in pairs if a == b) / len(pairs)) if pairs else None,
            "fail_recall": tp / fail_labels if fail_labels else None,
            "fail_precision": tp / fail_calls if fail_calls else None}


def calibrate(labels_path: str, judgment_dirs: list[str], out_path: str | None = None,
              gate: float = GATE_KAPPA, min_n: int = GATE_MIN_N, min_coverage: float = GATE_COVERAGE) -> dict:
    labels = load_labels(labels_path)
    if not labels:
        raise SystemExit(f"No labels in {labels_path}. Make some with `evlab label`.")
    jms, rows = [], []
    for jdir in judgment_dirs:
        vj = verify_judgment(jdir)
        if not vj["ok"]:
            raise SystemExit(f"{jdir} does not verify: {vj['problems'][0]}")
        jms.append(vj["manifest"])
        rows += load_records(os.path.join(jdir, "records.jsonl"))
    j0 = jms[0]
    for jm in jms[1:]:
        if [j["id"] for j in jm["judges"]] != [j["id"] for j in j0["judges"]] or jm["rubric_sha256"] != j0["rubric_sha256"]:
            raise SystemExit("All judgments must use the same judge panel and rubric.")
    judge_ids = [j["id"] for j in j0["judges"]]
    by_area: dict[str, dict] = {}
    for r in rows:
        lab = labels.get(r["target_record_hash"])
        if not lab or r["verdict"] == "error":
            continue
        a = by_area.setdefault(r["area"], {"n_labelled": 0, "panel": [], "heuristic": [], **{j: [] for j in judge_ids}})
        a["n_labelled"] += 1
        if r["verdict"] in DEFINITE:
            a["panel"].append((lab["label"], r["verdict"]))
        if r.get("heuristic_verdict"):
            a["heuristic"].append((lab["label"], r["heuristic_verdict"]))
        for x in r["judges"]:
            if x.get("verdict") in DEFINITE:
                a[x["judge"]].append((lab["label"], x["verdict"]))
    if not by_area:
        raise SystemExit("None of the labels match records in these judgments.")

    def summarize(a):
        cov = len(a["panel"]) / a["n_labelled"] if a["n_labelled"] else 0
        s = {"n_labelled": a["n_labelled"], "coverage": cov, "panel": _agreement(a["panel"]),
             "heuristic": _agreement(a["heuristic"]), "judges": {j: _agreement(a[j]) for j in judge_ids},
             "confusion_label_by_panel": confusion(a["panel"], list(DEFINITE))}
        k = s["panel"]["kappa"]
        s["gate_passed"] = bool(k is not None and k >= gate and len(a["panel"]) >= min_n and cov >= min_coverage)
        return s

    areas = {area: summarize(a) for area, a in sorted(by_area.items())}
    allp = {"n_labelled": 0, "panel": [], "heuristic": [], **{j: [] for j in judge_ids}}
    for a in by_area.values():
        for k in allp:
            allp[k] = allp[k] + a[k] if isinstance(a[k], list) else allp[k] + a[k]
    labellers = sorted({x.get("labeller") or "" for x in labels.values()})
    result = {
        "kind": "calibration", "created_at": utc_now(), "harness": f"evlab {__version__}",
        "labels_path": labels_path, "labels_sha256": sha256_file(labels_path), "n_labels": len(labels), "labellers": labellers,
        "judges": judge_ids, "rubric_id": j0["rubric_id"], "rubric_sha256": j0["rubric_sha256"],
        "judgment_ids": [f"{jm['run_id']}/{jm['judgment_id']}" for jm in jms],
        "gate": {"kappa": gate, "min_n": min_n, "min_coverage": min_coverage},
        "areas": areas, "overall": summarize(allp),
    }
    out_path = out_path or os.path.join("calibrations", f"{j0['judgment_id']}.json")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    result["path"] = out_path
    return result
