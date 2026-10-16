"""Train the HGNN on a graph folder and export the embeddings.

Example:
    python hgnn-job/run.py --data tests/hgnn/fixtures/toy_graph --target-relation accessed
"""

import argparse
import logging
import warnings

# Third-party deprecation noise (torch / PyG on Python 3.13), not an error in Corax.
warnings.filterwarnings("ignore", message="`torch.jit.script` is deprecated")

from corax_hgnn.export import save  # noqa: E402
from corax_hgnn.graph import load_graph  # noqa: E402
from corax_hgnn.train import TrainConfig, train  # noqa: E402


def parse_args() -> argparse.Namespace:
    defaults = TrainConfig()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", required=True, help="folder with nodes.csv and edges.csv")
    parser.add_argument(
        "--target-relation", required=True, help="relation used for link prediction"
    )
    parser.add_argument("--out", default="output/hgnn", help="output folder (default: output/hgnn)")
    parser.add_argument("--hidden", type=int, default=defaults.hidden)
    parser.add_argument("--learning-rate", type=float, default=defaults.learning_rate)
    parser.add_argument("--max-epochs", type=int, default=defaults.max_epochs)
    parser.add_argument("--patience", type=int, default=defaults.patience)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    graph = load_graph(args.data, args.target_relation)
    logging.info(
        "graph: %d node types, %d edge types, target %s",
        len(graph.data.node_types),
        len(graph.data.edge_types),
        graph.target,
    )

    config = TrainConfig(
        hidden=args.hidden,
        learning_rate=args.learning_rate,
        max_epochs=args.max_epochs,
        patience=args.patience,
        seed=args.seed,
    )
    result = train(graph, config)
    out_dir = save(result, graph, config, args.out)

    print(f"best epoch      {result.best_epoch} of {len(result.history)}")
    print(f"best val loss   {result.best_val_loss:.4f}")
    print(f"val AUC         {result.val_auc:.4f}")
    print(f"saved to        {out_dir}")


if __name__ == "__main__":
    main()
