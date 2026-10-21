import importlib


def main() -> None:
    for name in ["fastapi", "uvicorn", "httpx", "jwt", "numpy", "torch", "torch_geometric"]:
        module = importlib.import_module(name)
        print(f"{name:16} {getattr(module, '__version__', 'ok')}")

    from torch_geometric.nn import SAGEConv, to_hetero

    print("SAGEConv and to_hetero OK")


if __name__ == "__main__":
    main()
