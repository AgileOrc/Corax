# Evaluation

Every number below comes from a model trained once with `python -m hgnn` and scored by a script that
only loads it (`scripts/evaluate/`). Commands: [Scripts](reference/scripts.md).

## Risk score: Amazon Access Samples

UCI Amazon Access Samples (CC BY 4.0): 36,063 users, 33,252 resources, 405 departments, 4,979 titles,
3,207 managers, 595,506 access edges. Split 80 / 10 / 10; the test edges are never used in training.

- **Random negatives**: random (user, resource) pairs without access.
- **Hard negatives**: a resource a peer of the user (same department, title or manager) has, but the
  user does not. They look normal, which makes them the realistic case for a misconfigured rule.

| Model | AUC random | AUC hard | Threshold | False deny | Detection random | Detection hard |
|---|---|---|---|---|---|---|
| Base | 0.995 | 0.675 | 0.988 | 0.85% | 90.5% | 6.4% |
| 50% hard negatives in training (chosen) | 0.985 | 0.897 | 0.978 | 0.94% | 78.8% | 24.5% |

The threshold is calibrated so that 99% of real access in the validation split passes. Training with
hard negatives costs some detection of random pairs but almost quadruples detection of hard ones, at
the same false deny rate.

## Appeals: hidden rules

Benchmarks: the university ABAC policies of [[6]](references.md) and rules inferred from the Amazon data.
A rule is removed from the data, the model is trained without it, and one of its pairs is appealed. A
good appeal flow puts that rule near the top of the candidate list.

- **P@10**: share of the 10 similar cases that belong to the hidden rule.
- **Rank**: position of the hidden rule among the candidates.
- **Tier**: of the hidden rule, under the default limits (40% of users, 50 pairs, mean risk 0.5).

| Data | Appeals | P@10 | Rank 1 | Top 5 | Tier of the rule |
|---|---|---|---|---|---|
| Xu & Stoller university policies (5 files × 9 rules) | 45 | 34% | 26 | 37 | 45 large |
| Amazon, inferred "title T gets resource R" rules | 10 | 70% | 1 | 10 | 8 small, 2 large |
| Dummy campus, "head of program reads own students" | 1 | 10% | 0 | 1 | small |

Appeals that should not generalize (a lecturer asking for a student of another program, a one-off
Amazon grant) produce only large candidates on every dataset, so they wait for an admin.

The Xu & Stoller rules are all large because each grants more than 50 pairs, and rules 1, 6 and 9 reach
60–75% of the users. That is the intended behavior: a rule that broad needs a human.

**Known weakness**: rules that slice by an attribute of the object only (Xu & Stoller rules 4 and 8)
rank lower (5 to 11), because every value of that attribute gives a narrower candidate.

## Reproduce

- Xu & Stoller: [Scripts → Xu & Stoller](reference/scripts.md#xu--stoller-abac-policies). The `.abac`
  files are GPL-3.0 and are not part of this repository.
- Amazon: [Scripts → Amazon](reference/scripts.md#amazon-dataset).
- Dummy campus: [Quick start](getting-started/quickstart.md).
