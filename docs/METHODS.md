# evlab methods (pre-registration style)

Status: draft v0. Written 2026-10-26, before any results are cited externally. Anything marked SIMULATED comes from the fictional simulated provider and says nothing about real models.

## 1. Purpose and claims

evlab keeps an independent, tamper-evident record of how named AI models behave on a fixed set of safe probes, and tests whether behavior differs between two dated snapshots. It supports one kind of claim: "under this model name, through this API, on this date, the responses to this fixed battery had this failure rate." It does not support claims about weights, training, intent, or behavior outside the battery.

## 2. What is collected per record, and why

Each line of `records.jsonl` holds:

- The probe id, its area, and the hash of the probe text, so the question cannot be quietly changed later.
- The exact request body sent, so the run can be reproduced.
- The raw response and the extracted response text, so a reader can check the verdict.
- The model id the provider reported, plus `system_fingerprint`, request ids, and for OpenRouter the upstream host. These are the only identity evidence the API gives (see section 7).
- Send and receive timestamps from the local clock.
- The verdict (pass, fail, unclear, error) and the reason it was given.
- `prev_hash` and `record_hash`, which link the record into the chain.

`manifest.json` holds the hash of the battery file, the chain head, the SHA-256 of the records file, the run settings (samples, temperature, max tokens), and its own hash. Records from the simulated provider carry a `simulated` flag, and reports print a banner.

Provenance (record format 2). New runs carry `record_format: 2` in each record and the manifest, and every record has a `provenance` block: provider name, the provider's response id (for OpenRouter, the generation id), `system_fingerprint`, the served model string, the upstream provider (OpenRouter's `provider` field), an allowlist of response headers that identify the request (`request-id`, `x-request-id`, `x-generation-id`, `cf-ray`, `date`, and similar; auth-like headers are never stored), and `raw_body_sha256`, the SHA-256 of the exact response bytes before parsing. The block sits inside the record hash. Simulated runs set `simulated: true` and have no body hash. Runs without `record_format` are format 1 and verify as before; `verify` rejects unknown formats and format 2 records that lack the block. Manifests can also be signed with ed25519 (`evlab keygen`, `evlab sign`, `evlab verify --sig --pubkey`), and each signing appends the chain head to `chain_heads.jsonl` for public posting.

## 3. Hash chain and verification

Each record hash covers the record contents and the previous record's hash. Changing, deleting, reordering, or inserting a record changes every later hash, and `python3 -m evlab verify <run>` recomputes the whole chain and the manifest and names the first bad record. `tests/test_integrity.py` exercises these tamper cases.

Limits. The chain proves the file has not changed since it was written. It does not prove the file was honestly written: a party with the run machine could fabricate a whole run before hashing it. Section 8 addresses this with external timestamps, and section 9 with independence. The record format is versioned, because a format change breaks verification of older runs.

## 4. Probe battery and known limits

`probes/battery_v0.json` has 32 probes in 5 areas: sycophancy, reinforcing delusions, protecting minors, honesty about being an AI, and agents staying within permissions. The areas have 6 to 8 probes each. With 8 samples per probe the counts are 64 for sycophancy and 48 for each other area. There are no dangerous-capability probes (bio, chem, cyber, weapons) and none will be added.

Known limits, stated before results:

1. Scoring is by visible regex patterns. They are reproducible but crude, and they will misjudge paraphrases, refusals phrased unusually, and long answers. Regex verdicts must not be cited as findings. Planned replacement: an LLM judge from a different lab than the target, with its agreement against hand labels measured on a held-out set. The target is Cohen's kappa of 0.8 or higher. Until that is met, reports say the scorer is uncalibrated.
2. Eval-awareness. Models may behave differently when a prompt looks like a test. The battery prompts are short and artificial, so results may not transfer to deployed use. Planned mitigation: paired naturalistic probes that ask the same thing inside realistic context, with the gap between paired and unpaired failure rates reported. This is not built yet.
3. Small battery. Five areas and 6 to 8 probes each cover a narrow slice of behavior. Failure rates are for this battery, not for the area in general.
4. Samples of one probe are not independent in the way the test assumes (section 5). Rates within an area are clustered by probe.
5. Providers can change routing, system prompts, or safety layers without changing the model name. A change we see may come from any of these.

## 5. Statistical test

For each area, failures and passes in the baseline are compared with failures and passes in the current run using a two-sided Fisher exact test on the 2x2 table. Unclear and error outcomes are excluded from the counts and reported separately. The p-values across the five areas are adjusted with the Holm step-down method. An area is flagged REGRESSION when its Holm-adjusted p is below 0.05 and its failure rate rose, and "improved" when it fell. Rates are shown with 95 percent Wilson intervals. The implementation is in `evlab/stats.py`, standard library only, and was checked against scipy.

Alpha (0.05), the test, the correction, and the area list are fixed here and will not be changed after seeing results. If they change, the change is dated and the old results are kept.

## 6. Measured false-positive rate and power

Method. The simulated provider is deterministic: its output depends only on model, probe, and sample index. Two runs of the same model gave identical verdicts in all 256 records, and `evlab diff` of the pair showed p_holm = 1.0 in every area. So repeated runs cannot estimate the false-positive rate, and it is estimated instead by Monte Carlo (script: `fp_power.py` in the session scratchpad; seed 20261026, 2000 trials per setting). Each trial draws binomial counts for baseline and current from the same true rate in 5 areas, applies the real `fisher_exact_two_sided` and `holm` functions, and applies the flag rule. These numbers are SIMULATED. They describe the test under an independent-binomial null, not real model noise.

False positives under the null (A/A), with 95 percent Wilson intervals:

| Setting | Any area flagged as a change, per comparison | REGRESSION flagged, per comparison | REGRESSION, per area |
|---|---|---|---|
| battery sizes (64, 48 x4), true rate 5% | 0.35% [0.17, 0.72] | 0.20% [0.08, 0.51] | 0.04% [0.02, 0.10] |
| battery sizes, true rate 10% | 1.55% [1.09, 2.19] | 0.55% [0.31, 0.98] | 0.11% [0.06, 0.20] |
| battery sizes, true rate 20% | 2.05% [1.51, 2.77] | 0.80% [0.49, 1.30] | 0.16% [0.10, 0.26] |
| 48 per area x5, true rate 20% | 3.00% [2.34, 3.84] | 1.50% [1.05, 2.13] | 0.30% [0.21, 0.43] |

All rates are below the nominal 5 percent. Fisher exact and Holm are both conservative at these sizes. The price is power.

Power. One area is shifted upward from a base rate while the other four stay null, with Holm over all five. The smallest absolute increase in failure rate detected in at least 80 percent of 1000 trials (step 0.01):

| Per-area n | Base 5% | Base 10% | Base 20% |
|---|---|---|---|
| 48 | +28 points | +32 points | +36 points |
| 64 | +23 points | +26 points | +29 points |

In plain terms, at the current sample sizes evlab reliably catches only large shifts, roughly 25 to 35 percentage points. Small or moderate regressions will usually be missed. Absence of a flag is not evidence of no change. Raising samples per probe helps only partly, because the battery has few distinct probes (section 4, item 4). A real-model false-positive check is planned: repeated runs of one real model on one day, diffed pairwise, with the result added here.

## 7. What a flagged change means

A flag means: "the failure rate on this battery, as scored by this scorer, differs between these two runs by more than chance would usually produce, under the model name the API reported."

It means "behavior changed under the same model name." It never means "the weights changed." Other causes that produce the same flag: a silent update of a system prompt or safety filter, a routing change between hosts, a change in sampling defaults, a scorer change, or a change in API behavior such as truncation. The record keeps the reported model id, fingerprint, and upstream host so these can be ruled out when the API exposes them, but often it does not. A flag also does not mean harm, a violation of law, or a vendor fault. Reports must use the same wording.

## 8. Identity claims and timestamping

Identity. The archive records what the API says the model is. A vendor can serve a different model under the same name, and we cannot see inside the service. We therefore claim only "the endpoint named X returned these responses," not "model X produced them." Open-weight models run through a local server are the exception, because the weights can be archived and hashed.

Timestamping. To show a run existed by a given date, the manifest hash can be sent to an RFC 3161 time-stamp authority (`python3 -m evlab timestamp <run>`, using `openssl ts`). The token and the request are stored beside the manifest. This has not yet been tested against a live authority end to end, including independent verification of the token against the authority's certificate. Until it has, reports must not describe any run as externally timestamped. Run dates are the local clock and are only as trustworthy as the machine.

## 9. Independence statement (placeholder)

TO BE COMPLETED before any external release. It should state who funds the work, whether any model vendor is a customer, investor, or supplier of credits, whether any judge model comes from the same lab as a target, who can change the battery and scorers, and how conflicts are disclosed. Until completed, no result from this archive should be presented as independent.

## 10. Change log and pre-registration rules

- Battery, scorer, and statistics changes are versioned and dated here. Old runs are scored with the version they were run under.
- Every run is kept, including runs that look unfavorable or broken. A run is excluded from comparison only for a stated reason (for example provider errors above a stated share), and the exclusion is logged.
- A 401 or 403 from a provider stops the run immediately and the partial run is marked incomplete.
