# Command: python hgnn-job/run.py --data tests/hgnn/fixtures/toy_graph --target-relation accessed

import argparse
import json
import logging
import warnings

warnings.filterwarnings("ignore", message="`torch.jit.script` is deprecated")

from corax_hgnn.export import save, save_graph
from corax_hgnn.graph import load_graph
from corax_hgnn.train import TrainConfig, train


def parse_args() -> argparse.Namespace:
    defaults = TrainConfig()
    parser = argparse.ArgumentParser(description="Train the HGNN and export the embeddings.")
    parser.add_argument("--data", required=True, help="folder with nodes.csv and edges.csv")
    parser.add_argument(
        "--target-relation", required=True, help="relation used for link prediction"
    )
    parser.add_argument("--out", default="output/hgnn", help="output folder (default: output/hgnn)")
    parser.add_argument(
        "--test-ratio", type=float, default=defaults.test_ratio,
        help="held-out edges for scripts/evaluate/evaluate_hgnn.py (default 0.1: 80/10/10); 0 = none",
    )
    parser.add_argument("--hidden", type=int, default=defaults.hidden)
    parser.add_argument("--num-layers", type=int, default=defaults.num_layers)
    parser.add_argument("--hard-negative-ratio", type=float, default=defaults.hard_negative_ratio)
    parser.add_argument("--learning-rate", type=float, default=defaults.learning_rate)
    parser.add_argument("--max-epochs", type=int, default=defaults.max_epochs)
    parser.add_argument("--patience", type=int, default=defaults.patience)
    parser.add_argument(
        "--target-pass-rate", type=float, default=defaults.target_pass_rate,
        help="share of real access that must pass; sets the exported risk threshold",
    )
    parser.add_argument("--seed", type=int, default=defaults.seed)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    # graph.py 
    # load_graph function to translate the graph so that it can be processed through PyTorch
    graph = load_graph(args.data, args.target_relation) 
    logging.info(
        "graph: %d node types, %d edge types, target %s",
        len(graph.data.node_types),
        len(graph.data.edge_types),
        graph.target,
    )

    # train.py
    config = TrainConfig(
        test_ratio=args.test_ratio,
        hidden=args.hidden,
        num_layers=args.num_layers,
        hard_negative_ratio=args.hard_negative_ratio,
        learning_rate=args.learning_rate,
        max_epochs=args.max_epochs,
        patience=args.patience,
        target_pass_rate=args.target_pass_rate,
        seed=args.seed,
    )
    result = train(graph, config)

    # export.py
    out_dir = save(result, graph, config, args.out, data_folder=args.data)
    save_graph(args.data, args.target_relation, out_dir)
    metadata = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))

    print(f"best epoch      {result.best_epoch} of {len(result.history)}")
    print(f"best val loss   {result.best_val_loss:.4f}")
    print(f"val AUC         {result.val_auc:.4f}")
    print(f"risk threshold  {metadata['risk_threshold']['value']:.4f}"
          f" (target pass rate {config.target_pass_rate:.1%})")  # fmt: skip
    print(f"saved to        {out_dir}")
    if config.test_ratio > 0:
        print(f"evaluate with   python scripts/evaluate/evaluate_hgnn.py --model-dir {out_dir}")

if __name__ == "__main__":
    main()
