# Risk score

## Background

The model is Corax's own implementation of the heterogeneous graph method in [[1]](../references.md), with the architecture and hyperparameters described there. Users, objects and everything that connects them (departments, roles, projects, managers) are nodes of one typed graph. Past access is one edge type, and the model learns to predict it (link prediction).

## What Corax adds

- **The decoder is the risk score.** No separate classifier is trained on top of the embeddings: the
  dot product the model was trained with gives the risk of user *u* reading object *o*:

  $$
  \mathrm{risk}(u, o) = 1 - \sigma\left(\mathbf{h}_u^{T} \mathbf{h}_o\right),
  \qquad \sigma(x) = \frac{1}{1 + e^{-x}}
  $$

  Applications rarely have labeled examples of access that should be denied, and this needs none.
- **The model only checks, after the policy.** It runs once the policy has already allowed a request
  and can only turn that allow into a deny, so its mistakes can cost a false deny but never a false allow.
- **A calibrated threshold.** Set so that 99% of real access in the validation split passes.
- **Hard negatives** (optional, `--hard-negative-ratio`): some training negatives are objects a peer of
  the user has, the realistic case of a misconfigured rule. On Amazon they raise the AUC on such pairs
  from 0.675 to 0.897 ([Evaluation](../evaluation.md)).
- **A held-out test split** (80 / 10 / 10), so reported numbers come from edges never used for training
  or calibration.
- **The same embeddings find similar cases** (kNN) for [appeals](appeals.md).

## Graph

Corax is not tied to one domain, it reads typed nodes and typed edges from two CSV files
([Data format](../getting-started/data-format.md)). One edge type is the target. For the example used in these docs, a company whose
employees read reports:

| Amazon dataset | Example company |
|---|---|
| `user` | `employee` (e.g. `alice`) |
| `resource` | `report` (the object being accessed, e.g. `report_105`) |
| `department` | `department` |
| `title` | `role` (`role_manager`, `role_staff`) |
| `has_potential_access` | `accessed` (employee → report, from allowed requests only) |

A role is a node, not an attribute, so the graph contains the path `employee → role → employee`
("both are managers"). This is what lets the model see that two managers are similar.

## Model and training

| Item | Value |
|---|---|
| Node input | Learnable `nn.Embedding` per node |
| Encoder | 2 × `SAGEConv` with ReLU, converted with `to_hetero()`; `ToUndirected()` adds reverse edges |
| Decoder | Dot product `h_user · h_object` |
| Loss | Binary cross-entropy with logits, 2 negatives per positive |
| Split | `RandomLinkSplit` 80 / 10 / 10: train, validation (early stopping, threshold), test (evaluation only) |
| Optimizer | Adam, learning rate 0.001, patience 10, embedding size 64 |
| Hard negatives | Optional share of negatives taken from a peer's objects (`--hard-negative-ratio`, 0.5 on Amazon) |

Full-batch training: the graphs fit in memory, and `LinkNeighborLoader` needs `pyg-lib`, which is hard
to install on Windows.

Node inputs are learned per node (transductive): a new user or object only gets an embedding after
retraining. Until then `/risk` returns no score and the policy decision stands.

## From embeddings to risk

```
p     = σ(h_user · h_object)     how likely this user is to be connected to this object
risk  = 1 − p
deny  when risk > threshold
```

The dot product is used, not cosine, because the model was trained with it.

**Threshold.** The risk below which 99% of the real access in the validation split falls
(`--target-pass-rate 0.99`, about 1% false deny). It is an operating choice:
`scripts/evaluate/evaluate_hgnn.py` prints false deny and detection on the test split for 95%, 98%,
99%, 99.5% and 99.9%. The value is stored in `metadata.json` and can be overridden with
`AI_RISK_THRESHOLD`. Scores are deterministic, so a legitimate pair that is denied is denied every
time and can be resolved once through an appeal.

An employee who just joined a project has no access history yet, but is connected to the project's
reports through `works_on` / `belongs_to`, so the score stays reasonable.

## Limits

- The score is about pairs, not behavior over time: it does not detect fast enumeration by an
  otherwise legitimate user.
- Hard cases (an object a peer has) are caught less often than random ones; see [Evaluation](../evaluation.md).
