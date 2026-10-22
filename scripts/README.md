# scripts

Every dataset follows the same flow:

```
prepare/   dataset → nodes.csv, edges.csv, scenarios.json, hidden/*.csv   (format: docs/data-format.md)
   │
hgnn-job/run.py   trains the HGNN once and saves the model folder           (the only place that trains)
   │
evaluate/  loads the saved model, never trains
```

| Script | Does |
|---|---|
| `check_env.py` | Checks that the Python environment has the required packages |
| `similar_cases.py` | For one appealed (user, object) pair: the kNN similar cases, the candidate patterns and, with `--pick N`, the tier, Rego and validation of candidate N. Nothing is written |
| `prepare/make_dummy.py` | Writes a small dummy campus graph with two appeal scenarios, for tests and local trials |
| `prepare/convert_amazon.py` | Converts the UCI Amazon Access Samples dataset (CC BY 4.0) |
| `prepare/make_amazon_scenarios.py` | Hides inferred role-based rules (title → resource) in the Amazon graph, for evaluating appeals |
| `prepare/convert_xu_stoller.py` | Converts a Xu & Stoller ABAC policy (`.abac`) with one rule hidden (`--hide-rule N`) or each rule in turn (`--all-rules`) |
| `prepare/appeal_scenarios.py` | Reads and writes `scenarios.json` (used by the scripts above) |
| `evaluate/evaluate_hgnn.py` | Test metrics of the risk score and the risk threshold calibration table |
| `evaluate/evaluate_knn.py` | kNN precision@k, rank of the hidden rule among the candidate patterns, and its tier |

## Dummy campus

```bash
python scripts/prepare/make_dummy.py output/dummy-data
python hgnn-job/run.py --data output/dummy-data --target-relation accessed --out output/dummy --learning-rate 0.01 --patience 50
python scripts/evaluate/evaluate_knn.py --model-dir output/dummy --scenarios output/dummy-data/scenarios.json
python scripts/similar_cases.py --model-dir output/dummy --user lecturer_head_P0 --object student_P0_05
```

The candidate "user.member_of = object.member_of AND user holds position_head_of_program" should be
among the first few.

## Amazon dataset

1. Download `amzn-anon-access-samples-2.0.csv` from
   [UCI](https://archive.ics.uci.edu/dataset/216/amazon+access+samples) into `datasets/` (git-ignored, about 4.8 GB).
2. Convert (about 1 minute):

   ```bash
   python scripts/prepare/convert_amazon.py datasets/amzn-anon-access-samples-2.0.csv datasets/amazon-graph
   ```

   Expected: 36,063 users, 33,252 resources, 405 departments, 4,979 titles, 3,207 managers,
   595,506 `has_potential_access` edges.
3. Risk score: train once (80/10/10), then evaluate the saved model:

   ```bash
   python hgnn-job/run.py --data datasets/amazon-graph --target-relation has_potential_access --hard-negative-ratio 0.5 --out output/exp-hard50
   python scripts/evaluate/evaluate_hgnn.py --model-dir output/exp-hard50
   ```

4. Appeals: hide 10 inferred rules "title T gets resource R" (413 access edges) plus 2 one-off appeals;
   one training run covers all of them.

   ```bash
   python scripts/prepare/make_amazon_scenarios.py datasets/amazon-graph datasets/amazon-appeals
   python hgnn-job/run.py --data datasets/amazon-appeals --target-relation has_potential_access --out output/amazon-appeals
   python scripts/evaluate/evaluate_knn.py --model-dir output/amazon-appeals --scenarios datasets/amazon-appeals/scenarios.json
   ```

## Xu & Stoller ABAC policies

Standard policy mining benchmark from Z. Xu and S. D. Stoller, "Mining Attribute-Based Access Control
Policies", IEEE TDSC 12(5), 2015. Download `ABAC-Mining.zip` from Stoller's
[software page](https://www3.cs.stonybrook.edu/~stoller/software/) into `datasets/xu-stoller/` and
extract the `.abac` files there. The archive is GPL-3.0: keep it under `datasets/` (git-ignored); the
scripts here only read the format.

Each rule is hidden in turn: the pairs only that rule grants are removed from the access edges, so every
rule gives its own data folder and its own model. Candidates use up to 3 predicates and `object has ...`
(the resource type matters in every rule). Rule 3 of the university policy is skipped: rule 2 already
grants all its pairs.

```bash
# 1. prepare: output/xu-stoller/<file>/rule_NN/data
for f in datasets/xu-stoller/ABACMining/gen-case-studies/university/university-sets_10_*.abac; do python scripts/prepare/convert_xu_stoller.py "$f" "output/xu-stoller/$(basename "$f" .abac)" --all-rules; done
# 2. train each once: output/xu-stoller/<file>/rule_NN/model (about 5 seconds each)
for d in output/xu-stoller/*/rule_*; do python hgnn-job/run.py --data "$d/data" --target-relation accessed --out "$d/model" --learning-rate 0.01 --patience 50 --test-ratio 0; done
# 3. evaluate the saved models (no training)
python scripts/evaluate/evaluate_knn.py --runs "output/xu-stoller/*/rule_*" --out output/xu-stoller/results.json
```

The `ir-gen-case-studies` folder holds the same policies with irrelevant attributes added, for a noise test.
