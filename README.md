# evidence-archive (MVP)

An independent, tamper-evident record of how frontier AI models behave over time.

It runs a fixed battery of safe behavior probes against a model through its public API and stores every request and response as a hash-chained record. It can then check that the record hasn't been altered, test whether behavior changed between two model snapshots, and write an evidence packet that a regulator or insurer can read.

Standard library only (Python 3.10+). No dependencies to install.

## Quickstart (2 minutes, no API key)

```bash
python3 -m evlab run --provider simulated --model sim-model-2026-08 --samples 8 --run-id demo_baseline
python3 -m evlab run --provider simulated --model sim-model-2026-10 --samples 8 --run-id demo_current
python3 -m evlab verify runs/demo_current
python3 -m evlab diff   runs/demo_baseline runs/demo_current
python3 -m evlab report runs/demo_current --baseline runs/demo_baseline
open runs/demo_current/evidence_packet.html
```

The simulated models are fictional. Every record and report made from them is marked as simulated.

## Real run with OpenRouter (one key, models from many labs)

1. Open `api_keys.env` in this folder and paste your key after `OPENROUTER_API_KEY=` (get one at https://openrouter.ai/keys). Save the file.
2. Run (model ids are listed at https://openrouter.ai/models):

```bash
python3 -m evlab run --provider openrouter --model openai/gpt-4o-mini --samples 3
python3 -m evlab report runs/<run_id>
```

Test a key before a run (it should return JSON with your key's label):

```bash
curl -s https://openrouter.ai/api/v1/key -H "Authorization: Bearer $(grep OPENROUTER_API_KEY api_keys.env | cut -d= -f2-)"
```

Records also store `provider_upstream_provider`, meaning which host OpenRouter routed the request to.

If `OPENROUTER_API_KEY` is already exported in your shell, that value wins over `api_keys.env` and evlab prints a warning. Run `unset OPENROUTER_API_KEY` to use the file.

## Real run with a lab's own API

```bash
export ANTHROPIC_API_KEY=...        # or OPENAI_API_KEY
python3 -m evlab run --provider anthropic --model <model-id> --samples 3
python3 -m evlab run --provider openai    --model <model-id> --samples 3
# open-weight model via Ollama (weights can be archived permanently):
python3 -m evlab run --provider openai-compat --base-url http://localhost:11434/v1 --model llama3.1:8b
```

32 probes × 3 samples = 96 calls, which costs well under $1 on most models.

## Cross-lab judge panel

The regex scorers are a transparent baseline. For citable results, score a finished run with a panel of LLM judges, each from a different lab than the target and from each other:

```bash
python3 -m evlab judge runs/<run_id> --judge openrouter:openai/<model> --judge openrouter:google/<model>
python3 -m evlab verify runs/<run_id>                 # checks the run and every judgment chain
python3 -m evlab diff runs/<baseline> runs/<current> --scoring <judgment_id>
python3 -m evlab report runs/<current> --baseline runs/<baseline> --scoring <judgment_id>
```

A judgment never edits the run. It is a second hash-chained file at `runs/<run_id>/judgments/<judgment_id>/` that stores each judge's full request and raw reply and points at the run's records by hash. The panel's verdict counts only when every judge agrees and quotes the response accurately; anything else is `disputed` and excluded from rates, like `unclear`. The rubric lives in `probes/judge_rubric_v2.json` and its hash goes into every judgment. `diff` refuses to compare runs scored by different panels or rubric versions. For the cleanest comparison, judge the baseline and the current run on the same day.

Add `#<lab>` to a judge spec if its lab can't be inferred from the model id (e.g. `openai-compat:my-model#meta`). `--judge` also works on `evlab run` to judge right after the run. Demo without keys: `--judge simulated:sim-judge-a --judge simulated:sim-judge-b` on a simulated run.

### Calibrating the panel against hand labels

```bash
python3 -m evlab label runs/<run_a> runs/<run_b> --out labels/<your_name>.jsonl --per-area 40
python3 -m evlab calibrate labels/<your_name>.jsonl runs/<run_a>/judgments/<id> runs/<run_b>/judgments/<id>
```

`label` shows responses one at a time in random order, without the model's name or any verdict, and saves as you go (quit and resume any time). `calibrate` prints Cohen's kappa per area for the panel, each judge, and the regex heuristic, and writes `calibrations/<judgment_id>.json`. An area passes when kappa is at least 0.8, with at least 20 labels and at least 80% of them agreed by the panel. `diff` and `report` then use the judge only for passing areas and fall back to the heuristic elsewhere; the report shows which.

Optional trusted timestamp on a run (RFC 3161, needs `openssl ts`):

```bash
python3 -m evlab timestamp runs/<run_id>
```

## Tamper test (good live demo)

```bash
python3 -m evlab verify runs/demo_current          # VERIFIED
# edit any response_text in runs/demo_current/records.jsonl
python3 -m evlab verify runs/demo_current          # FAILED, and it names the record
python3 tests/test_integrity.py
```

## What's in a record

Each line of `records.jsonl` has the probe and its hash, the exact request sent, the raw response, the model ID the provider reported (plus `system_fingerprint` and request IDs where the API provides them), send and receive timestamps, the verdict and why it was given, `prev_hash`, and `record_hash`. `manifest.json` holds the hash of the battery file, the chain head, the SHA-256 of the records file, and its own hash.

## Battery v0

`probes/battery_v0.json` has 5 areas: sycophancy, reinforcing delusions, protecting minors, the model's honesty about itself, and agents staying within their permissions. There are no dangerous-capability probes. The scorers are visible regexes that are reproducible but crude; use a calibrated judge panel (above) before citing results.

## Limits

- The record shows how the served model behaved on these probes on these dates. It does not show what happened in a particular user's conversation.
- The model ID is whatever the provider reports. No provider today lets an outsider confirm which weights served a request.
- Check each provider's terms of service before publishing results. Some restrict publishing benchmark results.

## Layout

```
evlab/record.py     hash chain, verify
evlab/providers.py  anthropic, openai / openai-compatible, simulated
evlab/scoring.py    heuristic scorer, optional cross-lab LLM judge
evlab/stats.py      Fisher exact, Holm, Wilson intervals (stdlib)
evlab/report.py     HTML evidence packet
evlab/cli.py        run | verify | diff | report | timestamp
probes/             battery definitions
tests/              tamper and stats tests
```
