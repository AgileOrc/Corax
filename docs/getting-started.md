# Getting started

What you need, how the repository is organized, and how to run Corax with Docker. Run every command from the
repository root. Once the stack is up, [Running the demo](demo.md) walks through it.

## Prerequisites

To run the demo, Docker is all you need:

- **Docker**: Docker Desktop (Windows, macOS) or Docker Engine with the compose plugin (Linux). Check with
  `docker compose version`. With the older standalone tool, write `docker-compose` wherever this guide says
  `docker compose`.
- **Free ports** 8080 (the document app) and 8090 (the Corax console), or other ones ([Settings](#settings)).
- **About 2.5 GB of disk** for the images. Most of it is PyTorch, used once to train the model.

To develop, test or run the scripts without Docker, you also need:

- **Python 3.11** or newer.
- **The [OPA binary](https://www.openpolicyagent.org/docs/latest/#running-opa)**, for the policy tests and the appeal scripts.
- **Node.js 22.12** or newer, only to work on the document app's web frontend.

## Project layout

| Folder | What it holds | Who needs it |
|---|---|---|
| `policy/` | Corax's Rego framework: token checks, route matching, the call to the AI risk check, the deny-only rule | Anyone protecting an application |
| `service/` | The Corax service (FastAPI): `/risk` for OPA, `/corax/*` for administrators, appeals and the rules they write | Anyone protecting an application |
| `hgnn/` | Trains the graph model and exports one embedding per user and object (`python -m hgnn`) | Anyone training a model |
| `scripts/` | Data preparation (from CSV or the public datasets), evaluation and the demo scripts. See [Scripts](scripts.md) | Anyone preparing data or reproducing results |
| `demo/` | The application Corax protects in the demo: a document app, its rules, its web frontend and the Corax console | Anyone running or changing the demo |
| `deploy/` | Docker Compose, Envoy and OPA settings that run everything together | Anyone running the stack |
| `tests/` | Tests for the service, the model, the scripts and the demo app | Developers |
| `docs/` | This documentation | Everyone |

Two folders are created on your machine and never committed. `output/` holds prepared data and trained models,
and `datasets/` holds public datasets you download yourself.

## Deploy with Docker

```bash
git clone https://github.com/AgileOrc/Corax.git
cd Corax
docker compose -f deploy/docker-compose.yml run --rm prepare
docker compose -f deploy/docker-compose.yml up -d --build
```

- `prepare` builds the tools image (the first time takes a few minutes), generates the synthetic company into
  `output/gateway/data` and trains the graph model into `output/gateway/hgnn` (about 20 seconds). Run it once.
  `output/` stays on your disk.
- `up -d --build` builds and starts six containers:

| Container | Role | Port |
|---|---|---|
| `envoy` | Gateway: asks OPA about every request, forwards the allowed ones | `8080` |
| `opa` | Policy engine: Corax's framework, the app's rules and the rules from appeals | internal |
| `service` | The Corax service: `/risk` for OPA, `/corax/*` for administrators | internal |
| `app` | The document app (FastAPI and SQLite), with no access checks of its own | internal |
| `web` | The app's web frontend | internal, through Envoy |
| `console` | The Corax console, to send requests and handle appeals by hand | `8090` |

Check that everything is up. `app` and `service` should say `healthy`:

```bash
docker compose -f deploy/docker-compose.yml ps
```

Then open **http://localhost:8080** (the document app) and **http://localhost:8090** (the Corax console).

The service and OPA share a volume for the rules from appeals, and OPA watches it, so a new rule is live without a
restart. Both run inside Linux, so the file events reach OPA. A Windows folder mounted into a container often does
not deliver them.

> Tip: to drop `-f deploy/docker-compose.yml` from every command, set `COMPOSE_FILE` once per terminal:
> `export COMPOSE_FILE=deploy/docker-compose.yml` (macOS, Linux), `$env:COMPOSE_FILE="deploy/docker-compose.yml"`
> (PowerShell) or `set COMPOSE_FILE=deploy/docker-compose.yml` (cmd).

### Settings

Set these in the terminal before `up`, then run `up -d` again. Write `$env:NAME="value"` in PowerShell,
`set NAME=value` in cmd, or `export NAME=value` in bash.

| Variable | Default | Meaning |
|---|---|---|
| `CORAX_GATEWAY_PORT` | `8080` | Port of the document app |
| `CORAX_CONSOLE_PORT` | `8090` | Port of the Corax console |
| `CORAX_DEMO_PASSWORD` | `123456` | Every demo account's password. Set it before the first `up` or after a reset, because the app creates its accounts once |

The limits of a narrow rule (6% of the model's 86 employees, so 5 people, then 50 new accesses and a mean risk of
0.5) are the service's `AUTO_APPLY_MAX_USER_SHARE`, `AUTO_APPLY_MAX_PAIRS` and `AUTO_APPLY_MAX_MEAN_RISK`. The share
is set under `service:` → `environment:` in `deploy/docker-compose.yml`. Add or change them there, then `up -d`.

### Before you expose the stack

The defaults are for a local demo. Before anyone else can reach the stack, for example on a conference network:

- **Set `CORAX_DEMO_PASSWORD`**, then reset the stack so the accounts are created with it.
- **Replace the token secret** in `demo/data.json` (`corax.config.jwt.secret`). OPA, the service and the app use it
  to check sign-in tokens. Anyone who knows it can create an administrator token without a password.
- **Keep the `demo` container off shared machines.** It reads the other containers' logs through the Docker socket.

### Reset, stop, clean up

| What | Command |
|---|---|
| Start again from a fresh stack (drops requests, exceptions and rules, keeps the prepared data) | `docker compose -f deploy/docker-compose.yml down -v`, then `... up -d` |
| Stop, keeping everything | `docker compose -f deploy/docker-compose.yml down`, later `... up -d` |
| Rebuild after changing code | `docker compose -f deploy/docker-compose.yml up -d --build` |
| Remove the containers, volumes and images | `docker compose -f deploy/docker-compose.yml down -v --rmi local`, and `docker image rm corax-tools` |
| Generate the data and train the model again | delete `output/gateway`, then `... run --rm prepare` |

### Troubleshooting

| Problem | Fix |
|---|---|
| `port is already allocated` | Another program uses 8080 or 8090. Choose other ports ([Settings](#settings)) |
| The demo log says "the stack has N generated file(s) already", or cases fail | The stack was used before. Reset it |
| A demo scenario shows the colleague allowed before | Each scenario works once per stack, because the colleague may already have access. Reset |
| The containers stopped after Docker or the computer restarted | `docker compose -f deploy/docker-compose.yml up -d`. The data is kept |
| The app or the service never becomes `healthy` | `prepare` did not run, or `output/gateway` is missing. Run it, then `up -d` |
| You changed `demo/data.json` or `deploy/envoy.yaml` | `docker compose -f deploy/docker-compose.yml restart opa envoy`. Both are mounted as single files, which they do not reload |
| Linux: `output/` belongs to root after `prepare` | `sudo chown -R "$USER" output` |
| Your numbers differ slightly from the docs | Training depends on the machine's PyTorch build. The demo cases still check what each one should show |

## Develop without Docker

```bash
python -m venv .venv
```

Activate it with `.venv\Scripts\Activate.ps1` (PowerShell), `source .venv/Scripts/activate` (Git Bash) or
`source .venv/bin/activate` (Linux, macOS), then install the packages.

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r hgnn/requirements.txt -r service/requirements.txt -r demo/app/requirements.txt -r requirements-dev.txt
```

Pick the CUDA build of torch instead of `cpu` if you have a GPU. Run the tests:

```bash
pytest
opa test policy demo/policy
```

Set `OPA_PATH` if `opa` is not on the `PATH`.

To work on the document app's web frontend with live reload, keep the Docker stack running and start the
development server. It proxies every API call to the gateway on port 8080:

```bash
cd demo/web
npm ci
npm run dev
```

Then open http://localhost:5173.

Preparing data, training the model and the demo scripts are in [Scripts](scripts.md).
