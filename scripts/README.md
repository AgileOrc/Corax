# scripts

Helper scripts.

| Script | Does |
|---|---|
| `check_env.py` | Checks that the Python environment has the required packages |
| `convert_amazon.py` | Converts the UCI Amazon Access Samples dataset (CC BY 4.0) into `nodes.csv` / `edges.csv` |

## Amazon dataset

1. Download `amzn-anon-access-samples-2.0.csv` from
   [UCI](https://archive.ics.uci.edu/dataset/216/amazon+access+samples) into `datasets/` (git-ignored, about 4.8 GB).
2. Convert (about 1 minute):

   ```bash
   python scripts/convert_amazon.py datasets/amzn-anon-access-samples-2.0.csv datasets/amazon-graph
   ```

   Expected: 36,063 users, 33,252 resources, 405 departments, 4,979 titles, 3,207 managers,
   595,506 `has_potential_access` edges — the same numbers as Table 2 of Yin et al. 2024.
3. Train:

   ```bash
   python hgnn-job/run.py --data datasets/amazon-graph --target-relation has_potential_access --out output/amazon
   ```
