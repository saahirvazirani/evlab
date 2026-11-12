# Power and cost model

Written 2026-10-27. Script: `scripts/power_model.py` (standard library only, uses `evlab.stats`, seed 20261027, 1000 trials). All power numbers are simulated under an independent-binomial model. All token and cost numbers are measured from existing run records unless marked assumed.

## 1. Minimum detectable change (80% power, alpha 0.05, Holm over 5 areas)

One area is shifted upward from the base rate, the other four stay at the base rate. Values are percentage points of failure rate.

| Per-area n | Base 5% | Base 10% | Base 20% |
|---|---|---|---|
| 48 | +28 | +32 | +35 |
| 100 | +17 | +20 | +24 |
| 200 | +11 | +13 | +16 |
| 400 | +7 | +9 | +11 |
| 800 | +5 | +6 | +8 |

Per-area n needed to catch a given true increase with 80% power:

| Base rate | +10 points | +15 points |
|---|---|---|
| 5% | 220 | 120 |
| 10% | 330 | 170 |
| 20% | 480 | 220 |

The n=48 row matches the figures in METHODS.md section 6 within one point, which is a consistency check on the script.

## 2. Measured token use and cost per record

| Call type | Records with usage | Mean input tokens | Mean output tokens | Mean cost per call |
|---|---|---|---|---|
| Target: Sonnet 5.5 (reasoning low, max 800) | 93 of 96 | 46 | 479 | $0.0049 |
| Target: Gemini 3.8 Flash | 92 of 96 | 29 | 293 | $0.0011 |
| Target: Llama 4 Maverick | 96 of 96 | 37 | 153 | $0.0001 |
| Judge call (GPT-6 Luna or Gemini 3.8 Flash, rubric v2) | 386 calls | about 740 | about 70 | $0.0005 |

Output tokens dominate target cost, and they include reasoning tokens for Sonnet and Gemini. Judge calls are input-heavy because each carries the rubric and the response under test. A judged record uses two judge calls (the panel of two), so measured judge cost is about $0.0010 per record.

Reconciliation with known spend. The Gemini run cost $0.10 by the account, and the records sum to $0.103 over 92 records with usage, so about $0.107 for all 96. The account shows about $0.67 for judge panel spend. The usage fields in the five saved judgment passes sum to about $0.44 over 480 judged records, or $0.0009 per record. The gap is probably retries, failed attempts, and passes whose records were not kept. For budgeting I use the higher figure, $0.67 over 480 records, which is $0.0014 per judged record.

## 3. Cost per model per monthly run

Cost per run equals 5 areas times n times (target cost per record plus $0.0014 judge cost). Three of the six models have measured costs. The other three are assumed, because no frontier model with higher prices has been run yet.

Scenario sizes, at a 10% base rate: +10 points needs n=330, which is 1,650 records; +15 points needs n=170, which is 850 records. At a 20% base rate: n=480 (2,400 records) and n=220 (1,100 records).

| Model (cost per target record) | +10 pts, 10% base | +15 pts, 10% base | +10 pts, 20% base | +15 pts, 20% base |
|---|---|---|---|---|
| Llama 4 Maverick class ($0.0001, measured) | $2.49 | $1.28 | $3.62 | $1.66 |
| Gemini 3.8 Flash class ($0.0011, measured) | $4.16 | $2.14 | $6.05 | $2.77 |
| Sonnet 5.5 class ($0.0049, measured) | $10.37 | $5.34 | $15.08 | $6.91 |
| Mid frontier, assumed same as Sonnet | $10.37 | $5.34 | $15.08 | $6.91 |
| Premium frontier C, assumed 3x Sonnet ($0.0147) | $26.57 | $13.69 | $38.64 | $17.71 |
| Premium frontier D, assumed 3x Sonnet ($0.0147) | $26.57 | $13.69 | $38.64 | $17.71 |
| **Six-model month** | **$80** | **$42** | **$117** | **$54** |

Yearly compute, with 12 monthly runs of all six models, one baseline run of all six, and 12 extra release-day runs of an average model:

| Scenario | Monthly runs | Release-day runs | Baseline | Year total | Year total with 2x margin |
|---|---|---|---|---|---|
| +10 pts, 10% base | $966 | $161 | $80 | about $1,200 | about $2,400 |
| +15 pts, 10% base | $498 | $83 | $42 | about $620 | about $1,250 |
| +10 pts, 20% base | $1,405 | $234 | $117 | about $1,760 | about $3,500 |
| +15 pts, 20% base | $644 | $107 | $54 | about $805 | about $1,600 |

An earlier $30k compute budget line is about 8 to 50 times the modeled need, even with a 2x margin. The model supports either a smaller compute line (about $3k to $5k) or using the rest on things that raise power more cheaply than samples, listed below.

## 4. Assumptions and caveats

1. Power is for independent draws. The battery has 6 to 8 probes per area, so samples of one probe are correlated. Taking n=330 in an area from 7 probes means about 47 samples per probe, and that does not give the power in the table. Real power at these n will be lower. The fix is more distinct probes per area, not more samples per probe. Cost per record is unchanged, so the budget holds, but the battery needs to grow to roughly 30 or more probes per area before the table is trustworthy.
2. The power model compares two runs of the same size. The baseline run costs the same as one monthly run. Comparing each month to the previous month reuses it at no extra cost, but a month-to-month chain tests small steps, not drift since a fixed date.
3. Costs are OpenRouter prices on 2026-10-27 at max tokens 800 and reasoning effort low. Prices can change. Longer reasoning settings would raise output tokens and cost. No batch discount or caching is assumed.
4. Prompts are short (30 to 46 input tokens), so input cost is negligible for targets.
5. The two premium models and the mid frontier model are assumed prices. Replace them with measured costs after real runs. A 5x Sonnet price for both premium models would raise the six-model month by about $30 in the first column.
6. Judge cost per record is $0.0014 for a two-judge panel on rubric v2. A third judge, or a judge that uses more reasoning, would raise it. Judging is about 9% of cost for premium targets and over 90% for the cheapest targets.
7. Not included: the one-time calibration (about 200 hand labels, real runs on two models), RFC 3161 timestamp fees, retries after errors (about 4% of calls errored or returned unclear in the saved runs), and human time. Failed 401 or 403 calls stop a run, so a bad key costs a rerun.
8. The yearly figure assumes the battery stays at 32 probes in 5 areas. Adding areas adds a Holm penalty and shifts the table slightly.
