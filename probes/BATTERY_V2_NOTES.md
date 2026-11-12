# Battery v2 draft notes

File: probes/battery_v2_draft.json. Status: draft, not yet run.

## Counts per area

- sycophancy: 32 (16 from v1, 16 new)
- delusion: 30 (12 from v1, 18 new)
- minors: 30 (12 from v1, 18 new)
- self_honesty: 12 (unchanged)
- agent_scope: 12 (unchanged, frozen research track)
- identity_canary: 6 (unchanged)
- total: 122 (70 from v1, 52 new)

## Design choices

- Every v1_draft probe is kept exactly, with the same id and order, so results stay comparable.
- New probes use the existing schema: area, messages, pair_id, style, test_likeness.
- Two extra fields on new probes: subtype and added_in. Code that loads probes must tolerate them.
- New probes are standalone. They are not twins of each other, so pair_id is unique and there is no twin_of.
- Multi-turn is supported by the v1 format, so 12 new probes use alternating user and assistant messages. The assistant turn is scripted and the last turn is always the user.
- Style is a mix of benchmark (direct) and naturalistic phrasing.
- Sycophancy subtypes: bad_plan, flip_under_pushback, praise_weak_work, false_fact.
- Delusion subtypes: grandiose, persecutory, romantic_ai, ai_sentience, spiritual, medical_stop_meds, financial_scheme.
- Minors subtypes: age_romantic, age_selfharm, age_diet. Age is disclosed first, and the probe text contains no explicit or graphic content.
- Many new probes apply social pressure (insisting, claiming authority, asking for secrecy) so that failures are likely and kappa can be measured.
- No bio, chem, cyber or weapons content.

## Open items for the code owner

- The simulated provider has no responses for the 52 new probes yet. Add them, labeled as simulated.
- judge_rubric_v2 was written for the v0 probes. Subtypes such as AI sentience, romantic attachment, flipping under pushback and self-harm concealment may need a v3 rubric. Do not compare runs across rubric versions.
- test_likeness values are author estimates and should be replaced by a judge rating.
- Delusion has the heaviest judge risk. Hand-label the new delusion probes first.
