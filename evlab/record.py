"""Tamper-evident records.

Every model call becomes one JSON record. Each record carries the hash of the
previous record, so editing, deleting or reordering any record breaks the
chain. The run manifest stores the chain head and the SHA-256 of the records
file. This mirrors FRE 902(14): a copy is authenticated when a qualified
person certifies its hash matches the original.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone

GENESIS = "0" * 64
# Record format 1: original (no provenance block). Format 2: adds `record_format` and a `provenance` block to
# every record and `record_format` to the manifest. Runs without the field are format 1. verify_run accepts both.
RECORD_FORMAT = 2
SUPPORTED_FORMATS = (1, 2)
ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


def validate_id(value: str, what: str = "id") -> str:
    """Run ids and judgment names become folder names: letters, digits, dot, underscore, hyphen only."""
    if not value or not ID_PATTERN.fullmatch(value) or ".." in value or value in (".", ".."):
        raise SystemExit(f"Invalid {what} {value!r}: use only letters, digits, '.', '_' and '-' (no '..' or path separators).")
    return value


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ChainWriter:
    """Appends hash-chained records to a JSONL file."""

    def __init__(self, path: str):
        self.path = path
        self.prev = GENESIS
        self.count = 0
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        try:
            self._f = open(path, "x", encoding="utf-8")  # never overwrite an existing record file
        except FileExistsError:
            raise SystemExit(f"{path} already exists. Records are never overwritten; use a new id.") from None

    def append(self, record: dict) -> dict:
        body = dict(record)
        body["seq"] = self.count
        body["prev_hash"] = self.prev
        body["response_sha256"] = sha256_hex(canonical(body.get("response_raw")))
        body["record_hash"] = sha256_hex(canonical(body))
        self._f.write(json.dumps(body, ensure_ascii=False) + "\n")
        self._f.flush()
        self.prev = body["record_hash"]
        self.count += 1
        return body

    def close(self):
        self._f.close()


def load_records(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def verify_run(run_dir: str) -> dict:
    """Recompute every hash. Returns a dict with ok flag and the problems found."""
    problems: list[str] = []
    man_path = os.path.join(run_dir, "manifest.json")
    rec_path = os.path.join(run_dir, "records.jsonl")
    with open(man_path, encoding="utf-8") as f:
        manifest = json.load(f)

    file_hash = sha256_file(rec_path)
    if file_hash != manifest.get("records_sha256"):
        problems.append(f"records.jsonl SHA-256 {file_hash[:16]}... does not match manifest {manifest.get('records_sha256', '')[:16]}...")

    fmt = manifest.get("record_format", 1)
    if fmt not in SUPPORTED_FORMATS:
        problems.append(f"unsupported record format {fmt!r} (this verifier knows {SUPPORTED_FORMATS})")

    prev = GENESIS
    records = load_records(rec_path)
    for i, r in enumerate(records):
        if fmt == 2:
            if r.get("record_format") != 2:
                problems.append(f"record {i}: record_format is {r.get('record_format')!r}, manifest says 2")
            if not isinstance(r.get("provenance"), dict):
                problems.append(f"record {i}: format 2 record has no provenance block")
        claimed = r.get("record_hash")
        body = {k: v for k, v in r.items() if k != "record_hash"}
        if r.get("seq") != i:
            problems.append(f"record {i}: sequence number is {r.get('seq')} (records reordered or removed)")
        if r.get("prev_hash") != prev:
            problems.append(f"record {i} ({r.get('probe_id')}): prev_hash does not link to record {i-1}")
        if sha256_hex(canonical(r.get("response_raw"))) != r.get("response_sha256"):
            problems.append(f"record {i} ({r.get('probe_id')}): response text was altered")
        if sha256_hex(canonical(body)) != claimed:
            problems.append(f"record {i} ({r.get('probe_id')}): record hash mismatch")
        prev = claimed

    if records and prev != manifest.get("chain_head"):
        problems.append("chain head does not match manifest")
    if len(records) != manifest.get("n_records"):
        problems.append(f"manifest lists {manifest.get('n_records')} records, file has {len(records)}")

    man_body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if sha256_hex(canonical(man_body)) != manifest.get("manifest_sha256"):
        problems.append("manifest itself was edited after the run")

    return {"ok": not problems, "problems": problems, "n_records": len(records),
            "chain_head": prev, "records_sha256": file_hash, "manifest": manifest}


def verify_tsr(run_dir: str, ca_file: str | None) -> dict:
    """Check a stored RFC 3161 token (manifest.tsr) against manifest.json with `openssl ts -verify`.

    Read-only: nothing in the run folder is changed. Raises SystemExit with a clear message when the
    token, the CA file or openssl is missing. Returns ok, the token's SHA-256, its genTime and the
    imprint it signs."""
    tsr, man = os.path.join(run_dir, "manifest.tsr"), os.path.join(run_dir, "manifest.json")
    if not os.path.exists(tsr):
        raise SystemExit(f"{tsr} not found: this run has no stored timestamp token (create one with `evlab timestamp`).")
    if not ca_file:
        raise SystemExit("--tsr needs --tsa-ca <file>: the TSA's CA certificate (for freetsa.org, its cacert.pem).")
    if not os.path.isfile(ca_file):
        raise SystemExit(f"TSA CA file not found: {ca_file}")
    if not shutil.which("openssl"):
        raise SystemExit("openssl not found on PATH; it is needed to verify RFC 3161 tokens.")
    v = subprocess.run(["openssl", "ts", "-verify", "-in", tsr, "-data", man, "-CAfile", ca_file],
                       capture_output=True, text=True)
    out = {"ok": v.returncode == 0 and "Verification: OK" in v.stdout + v.stderr, "tsr_sha256": sha256_file(tsr),
           "manifest_sha256_file": sha256_file(man), "gen_time": None, "imprint": None, "detail": (v.stderr or v.stdout).strip()[-400:]}
    t = subprocess.run(["openssl", "ts", "-reply", "-in", tsr, "-text"], capture_output=True, text=True)
    if t.returncode == 0:
        hexes, in_msg = [], False
        for line in t.stdout.splitlines():
            if line.startswith("Time stamp:"):
                out["gen_time"] = line.split(":", 1)[1].strip()
            if line.startswith("Message data:"):
                in_msg = True
            elif in_msg and "-" in line and line.strip()[:4].isalnum() and line.startswith("    "):
                hexes.append("".join(line.split(" - ", 1)[1][:48].split("  ")[0].replace("-", " ").split()))
            elif in_msg:
                in_msg = False
        out["imprint"] = "".join(hexes) or None
    if out["ok"] and out["imprint"] != out["manifest_sha256_file"]:
        out["ok"] = False
        out["detail"] = "token verifies but its imprint is not the SHA-256 of manifest.json"
    return out


# ---------------------------------------------------------------------------
# Manifest signing (ed25519 via the openssl CLI; the standard library has no ed25519)
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_KEY_DIR = os.path.join("~", ".evlab", "keys")


def _openssl() -> str:
    exe = shutil.which("openssl")
    if not exe:
        raise SystemExit("openssl not found on PATH; it is needed for ed25519 signing.")
    return exe


def _ossl(args, **kw):
    return subprocess.run([_openssl(), *args], capture_output=True, **kw)


def _need_ed25519():
    with_tmp = _ossl(["genpkey", "-algorithm", "ed25519"])
    if with_tmp.returncode != 0 or b"PRIVATE KEY" not in with_tmp.stdout:
        ver = _ossl(["version"], text=True).stdout.strip()
        raise SystemExit(f"This openssl ({ver}) cannot do ed25519 (needs OpenSSL 1.1.1 or newer, e.g. `brew install openssl@3`).")


def pubkey_fingerprint(pub_path: str) -> str:
    """SHA-256 of the DER-encoded public key (SubjectPublicKeyInfo)."""
    r = _ossl(["pkey", "-pubin", "-in", pub_path, "-outform", "DER"])
    if r.returncode != 0:
        raise SystemExit(f"Cannot read public key {pub_path}: {r.stderr.decode(errors='replace').strip()}")
    return sha256_hex(r.stdout)


def keygen(out_dir: str | None = None, name: str = "evlab_ed25519") -> tuple[str, str, str]:
    """Create an ed25519 key pair. The private key is written with mode 0600 and never inside runs/."""
    out_dir = os.path.abspath(os.path.expanduser(out_dir or DEFAULT_KEY_DIR))
    runs = os.path.join(REPO_ROOT, "runs")
    if out_dir == runs or out_dir.startswith(runs + os.sep):
        raise SystemExit("Refusing to put key material inside runs/: it would travel with the evidence.")
    _need_ed25519()
    priv, pub = os.path.join(out_dir, name + ".key"), os.path.join(out_dir, name + ".pub")
    if os.path.exists(priv) or os.path.exists(pub):
        raise SystemExit(f"{priv} or {pub} already exists; keys are never overwritten.")
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    g = _ossl(["genpkey", "-algorithm", "ed25519"])
    fd = os.open(priv, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(g.stdout)
    os.chmod(priv, 0o600)
    p = _ossl(["pkey", "-in", priv, "-pubout"])
    if p.returncode != 0:
        raise SystemExit("openssl could not derive the public key: " + p.stderr.decode(errors="replace").strip())
    with open(pub, "wb") as f:
        f.write(p.stdout)
    return priv, pub, pubkey_fingerprint(pub)


def sign_run(run_dir: str, key_path: str, heads_path: str | None = None) -> dict:
    """Sign manifest.json (raw ed25519) and write manifest.sig; append the chain head to chain_heads.jsonl."""
    _need_ed25519()
    v = verify_run(run_dir)
    if not v["ok"]:
        raise SystemExit("Refusing to sign a run that does not verify: " + "; ".join(v["problems"][:3]))
    if not os.path.isfile(key_path):
        raise SystemExit(f"Private key not found: {key_path}")
    if os.stat(key_path).st_mode & 0o077:
        raise SystemExit(f"{key_path} is readable by other users; run `chmod 600 {key_path}` first.")
    sig_path, man_path = os.path.join(run_dir, "manifest.sig"), os.path.join(run_dir, "manifest.json")
    if os.path.exists(sig_path):
        raise SystemExit(f"{sig_path} already exists; a run is signed once.")
    pub = _ossl(["pkey", "-in", key_path, "-pubout"])
    if pub.returncode != 0:
        raise SystemExit("Cannot read private key: " + pub.stderr.decode(errors="replace").strip())
    fpr = sha256_hex(_ossl(["pkey", "-pubin", "-outform", "DER"], input=pub.stdout).stdout)
    s = _ossl(["pkeyutl", "-sign", "-rawin", "-inkey", key_path, "-in", man_path])
    if s.returncode != 0 or not s.stdout:
        raise SystemExit("openssl signing failed: " + s.stderr.decode(errors="replace").strip())
    man_sha = sha256_file(man_path)
    signed_at = utc_now()
    with open(sig_path, "w", encoding="utf-8") as f:
        json.dump({"alg": "ed25519", "signed_file": "manifest.json", "manifest_file_sha256": man_sha,
                   "pubkey_sha256": fpr, "signed_at": signed_at,
                   "signature_b64": base64.b64encode(s.stdout).decode()}, f, indent=2)
    head = {"run_id": v["manifest"].get("run_id"), "manifest_sha256": v["manifest"].get("manifest_sha256"),
            "manifest_file_sha256": man_sha, "chain_head": v["chain_head"], "signed_at_utc": signed_at,
            "pubkey_sha256": fpr}
    heads_path = heads_path or os.path.join(REPO_ROOT, "chain_heads.jsonl")
    with open(heads_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(head, sort_keys=True) + "\n")
    return {"sig_path": sig_path, "pubkey_sha256": fpr, "heads_path": heads_path, "head": head}


def verify_sig(run_dir: str, pub_path: str) -> dict:
    """Check manifest.sig against manifest.json with the given public key. Read-only."""
    _need_ed25519()
    sig_path, man_path = os.path.join(run_dir, "manifest.sig"), os.path.join(run_dir, "manifest.json")
    if not os.path.exists(sig_path):
        raise SystemExit(f"{sig_path} not found: this run is not signed (use `evlab sign`).")
    if not pub_path or not os.path.isfile(pub_path):
        raise SystemExit("--sig needs --pubkey <public key file>.")
    with open(sig_path, encoding="utf-8") as f:
        sig = json.load(f)
    fpr = pubkey_fingerprint(pub_path)
    out = {"ok": False, "pubkey_sha256": fpr, "signed_at": sig.get("signed_at"), "detail": ""}
    if sig.get("pubkey_sha256") != fpr:
        out["detail"] = f"signature was made by key {str(sig.get('pubkey_sha256'))[:16]}..., not the key given ({fpr[:16]}...)"
        return out
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        sp = os.path.join(t, "sig.bin")
        with open(sp, "wb") as f:
            f.write(base64.b64decode(sig.get("signature_b64", "")))
        r = _ossl(["pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", pub_path, "-in", man_path, "-sigfile", sp])
    out["ok"] = r.returncode == 0 and b"Successfully" in r.stdout
    out["detail"] = "" if out["ok"] else "signature does not match manifest.json (manifest edited, or wrong key)"
    return out
