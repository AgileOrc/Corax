import importlib


def main() -> None:
    for name in ["fastapi", "uvicorn", "httpx", "jwt", "numpy", "torch", "torch_geometric"]:
        module = importlib.import_module(name)
        print(f"{name:16} {getattr(module, '__version__', 'ok')}")

    nn = importlib.import_module("torch_geometric.nn")
    for name in ["SAGEConv", "to_hetero"]:
        getattr(nn, name)

    print("SAGEConv and to_hetero OK")


if __name__ == "__main__":
    main()
