"""Run with: python3 -m pytest -q  (or python3 tests/test_integrity.py)"""
import json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from evlab.record import verify_run, verify_tsr, validate_id
from evlab.providers import redact
from evlab.stats import fisher_exact_two_sided


def _run(tmp, model, rid):
    subprocess.run([sys.executable, "-m", "evlab", "run", "--provider", "simulated", "--model", model,
                    "--samples", "2", "--run-id", rid, "--out", tmp], cwd=ROOT, check=True, capture_output=True)
    return os.path.join(tmp, rid)


def test_clean_run_verifies():
    tmp = tempfile.mkdtemp()
    assert verify_run(_run(tmp, "sim-model-2026-08", "a"))["ok"]


def test_edited_response_is_caught():
    tmp = tempfile.mkdtemp()
    d = _run(tmp, "sim-model-2026-08", "b")
    p = os.path.join(d, "records.jsonl")
    lines = open(p).read().splitlines()
    rec = json.loads(lines[5]); rec["response_text"] = "edited"; rec["response_raw"]["content"] = "edited"
    lines[5] = json.dumps(rec)
    open(p, "w").write("\n".join(lines) + "\n")
    r = verify_run(d)
    assert not r["ok"] and any("record 5" in x for x in r["problems"])


def test_deleted_record_is_caught():
    tmp = tempfile.mkdtemp()
    d = _run(tmp, "sim-model-2026-08", "c")
    p = os.path.join(d, "records.jsonl")
    lines = open(p).read().splitlines()
    del lines[3]
    open(p, "w").write("\n".join(lines) + "\n")
    assert not verify_run(d)["ok"]


def test_fisher_matches_known_value():
    # scipy.stats.fisher_exact([[1, 9], [11, 3]]) -> p = 0.002759...
    assert abs(fisher_exact_two_sided(1, 9, 11, 3) - 0.0027594) < 1e-5


def _cli(*args):
    return subprocess.run([sys.executable, "-m", "evlab", *args], cwd=ROOT, capture_output=True, text=True)


def test_existing_run_dir_is_refused():
    tmp = tempfile.mkdtemp()
    d = _run(tmp, "sim-model-2026-08", "dup")
    before = open(os.path.join(d, "records.jsonl")).read()
    r = _cli("run", "--provider", "simulated", "--model", "sim-model-2026-08", "--samples", "1", "--run-id", "dup", "--out", tmp)
    assert r.returncode != 0 and "already exists" in r.stderr
    assert open(os.path.join(d, "records.jsonl")).read() == before and verify_run(d)["ok"]


def test_bad_run_ids_are_refused():
    tmp = tempfile.mkdtemp()
    for bad in ["../x", "a/b", "..", "a..b", "a b"]:
        r = _cli("run", "--provider", "simulated", "--model", "sim-model-2026-08", "--samples", "1", "--run-id", bad, "--out", os.path.join(tmp, "out"))
        assert r.returncode != 0, bad
    assert not os.path.exists(os.path.join(tmp, "x")) and not os.path.exists(os.path.join(tmp, "out"))
    assert validate_id("ok_run-1.2") == "ok_run-1.2"


def test_existing_judgment_dir_is_refused_and_name_validated():
    tmp = tempfile.mkdtemp()
    d = _run(tmp, "sim-model-2026-08", "j")
    args = ["judge", d, "--judge", "simulated:sim-judge-a", "--judge", "simulated:sim-judge-b"]
    assert _cli(*args, "--name", "n1").returncode == 0
    r = _cli(*args, "--name", "n1")
    assert r.returncode != 0 and "already exists" in r.stderr
    assert _cli(*args, "--name", "../evil").returncode != 0
    assert not os.path.exists(os.path.join(d, "evil"))


def test_api_keys_are_redacted():
    os.environ["TESTVENDOR_API_KEY"] = "zzzSECRETVALUE12345"
    try:
        out = redact("bad key zzzSECRETVALUE12345 and sk-or-v1-abcdef0123456789 echoed")
        assert "zzzSECRETVALUE12345" not in out and "sk-or-v1" not in out and "[REDACTED]" in out
        assert "tok123456789" not in redact("auth tok123456789", extra=["tok123456789"])
        assert redact("plain error 500") == "plain error 500"
    finally:
        del os.environ["TESTVENDOR_API_KEY"]


def test_tsr_verify_fails_clearly():
    tmp = tempfile.mkdtemp()
    d = _run(tmp, "sim-model-2026-08", "t")
    for args in [(d, None), (d, os.path.join(tmp, "missing.pem"))]:
        try:
            verify_tsr(*args)
            assert False, "should have stopped"
        except SystemExit as e:
            assert "manifest.tsr" in str(e) or "--tsa-ca" in str(e) or "not found" in str(e)
    open(os.path.join(d, "manifest.tsr"), "wb").write(b"not a token")
    ca = os.path.join(tmp, "ca.pem"); open(ca, "w").write("x")
    try:
        verify_tsr(d, None); assert False
    except SystemExit as e:
        assert "--tsa-ca" in str(e)
    try:
        verify_tsr(d, os.path.join(tmp, "missing.pem")); assert False
    except SystemExit as e:
        assert "CA file not found" in str(e)
    assert not verify_tsr(d, ca)["ok"]  # garbage token must not verify
    r = _cli("verify", d, "--tsr", "--tsa-ca", ca)
    assert r.returncode == 1 and "FAILED" in r.stdout


def test_real_tsr_if_available():
    """Set EVLAB_TSA_CA to the TSA's cacert.pem to check runs/tsa_check (skipped otherwise)."""
    ca, d = os.environ.get("EVLAB_TSA_CA"), os.path.join(ROOT, "runs", "tsa_check")
    if not (ca and os.path.isfile(ca) and os.path.exists(os.path.join(d, "manifest.tsr"))):
        return
    t = verify_tsr(d, ca)
    assert t["ok"] and t["gen_time"] and t["imprint"] == t["manifest_sha256_file"]


def _keys(tmp, name="k"):
    r = _cli("keygen", "--out", os.path.join(tmp, name))
    assert r.returncode == 0, r.stderr + r.stdout
    return os.path.join(tmp, name, "evlab_ed25519.key"), os.path.join(tmp, name, "evlab_ed25519.pub")


def test_sign_roundtrip_tamper_and_wrong_key():
    tmp = tempfile.mkdtemp()
    d = _run(tmp, "sim-model-2026-08", "sg")
    priv, pub = _keys(tmp)
    assert oct(os.stat(priv).st_mode & 0o777) == "0o600"
    heads = os.path.join(tmp, "heads.jsonl")
    r = _cli("sign", d, "--key", priv, "--heads", heads)
    assert r.returncode == 0, r.stderr + r.stdout
    h = json.loads(open(heads).read().splitlines()[-1])
    assert h["run_id"] == "sg" and h["pubkey_sha256"] and h["manifest_sha256"] and h["signed_at_utc"]
    assert _cli("verify", d, "--sig", "--pubkey", pub).returncode == 0
    _, pub2 = _keys(tmp, "k2")
    r = _cli("verify", d, "--sig", "--pubkey", pub2)
    assert r.returncode == 1 and "FAILED" in r.stdout
    mp = os.path.join(d, "manifest.json")
    m = json.load(open(mp)); m["samples_per_probe"] = 99; json.dump(m, open(mp, "w"), indent=2)
    r = _cli("verify", d, "--sig", "--pubkey", pub)
    assert r.returncode == 1 and "signature" in r.stdout
    # keys must not go inside runs/
    r = _cli("keygen", "--out", os.path.join(ROOT, "runs", "keys_x"))
    assert r.returncode != 0 and not os.path.exists(os.path.join(ROOT, "runs", "keys_x"))


def test_old_format_run_verifies_and_new_run_has_provenance():
    tmp = tempfile.mkdtemp()
    d = _run(tmp, "sim-model-2026-08", "pv")
    recs = [json.loads(l) for l in open(os.path.join(d, "records.jsonl"))]
    assert json.load(open(os.path.join(d, "manifest.json")))["record_format"] == 2
    for r in recs:
        p = r["provenance"]
        assert r["record_format"] == 2 and p["provider"] == "simulated" and p["simulated"] is True
        assert p["served_model"] == "sim-model-2026-08" and p["response_id"].startswith("sim_")
        assert "response_headers" in p and "raw_body_sha256" in p and "system_fingerprint" in p and "upstream_provider" in p
    # rebuild the same run as a format-1 run (no provenance, no record_format) with a valid chain
    from evlab.record import ChainWriter, canonical, sha256_hex, sha256_file
    old = os.path.join(tmp, "old"); os.makedirs(old)
    w = ChainWriter(os.path.join(old, "records.jsonl"))
    for r in recs:
        w.append({k: v for k, v in r.items() if k not in ("record_format", "provenance", "seq", "prev_hash", "response_sha256", "record_hash")})
    w.close()
    m = json.load(open(os.path.join(d, "manifest.json")))
    m.pop("record_format"); m.pop("manifest_sha256")
    m.update(chain_head=w.prev, records_sha256=sha256_file(os.path.join(old, "records.jsonl")))
    m["manifest_sha256"] = sha256_hex(canonical(m))
    json.dump(m, open(os.path.join(old, "manifest.json"), "w"))
    assert verify_run(old)["ok"]
    # a format-2 manifest over format-1 records must not pass
    m2 = dict(m); m2.pop("manifest_sha256"); m2["record_format"] = 2; m2["manifest_sha256"] = sha256_hex(canonical(m2))
    json.dump(m2, open(os.path.join(old, "manifest.json"), "w"))
    assert not verify_run(old)["ok"]


def test_provenance_headers_never_include_auth():
    from evlab.providers import build_provenance
    import hashlib
    body = b'{"id":"gen-1","model":"x/y","provider":"Acme","system_fingerprint":"fp"}'
    p = build_provenance("openrouter", json.loads(body), {"authorization": "Bearer sk-secret", "x-api-key": "k", "request-id": "r1",
                         "x-request-id": "r2", "set-cookie": "c"}, body)
    assert p["response_headers"] == {"request-id": "r1", "x-request-id": "r2"}
    assert p["response_id"] == "gen-1" and p["upstream_provider"] == "Acme" and p["system_fingerprint"] == "fp"
    assert p["raw_body_sha256"] == hashlib.sha256(body).hexdigest()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
