# scripts

Helper scripts.

| Script | Does |
|---|---|
| `check_env.py` | Checks that the Python environment has the required packages |
| `convert_amazon.py` | Converts the UCI Amazon Access Samples dataset (CC BY 4.0) into `nodes.csv` / `edges.csv` |
| `evaluate_hgnn.py` | Loads a model trained by `hgnn-job/run.py` (no training) and reports test metrics and the risk threshold calibration table |
| `compare_experiments.py` | Compares several `evaluate_hgnn.py` result folders side by side |
| `make_mini_campus.py` | Writes a small synthetic campus graph for trying appeals locally |
| `similar_cases.py` | For an appealed (user, object) pair: the kNN similar cases and the candidate patterns |
| `make_amazon_scenarios.py` | Hides inferred role-based rules (title → resource) in the Amazon graph, for evaluating appeals |
| `evaluate_appeals.py` | Scores kNN and candidate patterns on `scenarios.json` (precision@k, rank of the expected rule) |
| `appeal_scenarios.py` | Reads and writes `scenarios.json` (used by the scripts above) |

## Mini campus (appeals)

```bash
python scripts/make_mini_campus.py output/mini-campus-data
python hgnn-job/run.py --data output/mini-campus-data --target-relation accessed --out output/mini-campus --learning-rate 0.01 --patience 50
python scripts/similar_cases.py --model-dir output/mini-campus --user lecturer_head_P0 --object student_P0_05
```

The candidate "user.member_of = object.member_of AND user holds position_head_of_program" should be
among the first few. To score it:

```bash
python scripts/evaluate_appeals.py --model-dir output/mini-campus --scenarios output/mini-campus-data/scenarios.json
```

## Appeals on the Amazon data

Hides 10 inferred rules "title T gets resource R" (413 access edges) plus 2 one-off appeals; one
training run covers all of them.

```bash
python scripts/make_amazon_scenarios.py datasets/amazon-graph datasets/amazon-appeals
python hgnn-job/run.py --data datasets/amazon-appeals --target-relation has_potential_access --out output/amazon-appeals
python scripts/evaluate_appeals.py --model-dir output/amazon-appeals --scenarios datasets/amazon-appeals/scenarios.json
```

## Amazon dataset

1. Download `amzn-anon-access-samples-2.0.csv` from
   [UCI](https://archive.ics.uci.edu/dataset/216/amazon+access+samples) into `datasets/` (git-ignored, about 4.8 GB).
2. Convert (about 1 minute):

   ```bash
   python scripts/convert_amazon.py datasets/amzn-anon-access-samples-2.0.csv datasets/amazon-graph
   ```

   Expected: 36,063 users, 33,252 resources, 405 departments, 4,979 titles, 3,207 managers,
   595,506 `has_potential_access` edges.
3. Train once (80/10/10), then evaluate the saved model:

   ```bash
   python hgnn-job/run.py --data datasets/amazon-graph --target-relation has_potential_access --hard-negative-ratio 0.5 --out output/exp-hard50
   python scripts/evaluate_hgnn.py --model-dir output/exp-hard50
   ```
