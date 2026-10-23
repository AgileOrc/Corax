# Corax graph data format

Corax does not know about any specific domain. Any application (a company, a hospital, a shop)
describes its users, objects and relations as a typed graph in two CSV files.

## nodes.csv

| Column | Meaning |
|---|---|
| `id` | Unique node id across the whole file, e.g. `alice` |
| `type` | Node type, e.g. `employee`, `report`, `department` |

```csv
id,type
alice,employee
report_105,report
department_sales,department
```

## edges.csv

| Column | Meaning |
|---|---|
| `src` | Source node id (must exist in `nodes.csv`) |
| `relation` | Relation name, e.g. `works_on`, `member_of` |
| `dst` | Destination node id (must exist in `nodes.csv`) |

```csv
src,relation,dst
alice,member_of,department_sales
alice,accessed,report_105
```

The edge type is the triple `(source type, relation, destination type)`, derived from the node types.
The same relation name may connect different node types, e.g. `(employee, member_of, department)` and
`(report, member_of, department)` are two edge types.

## Rules

- Every node type must appear in at least one edge.
- One relation is the **target relation** for link prediction (passed as `--target-relation`).
  It must connect exactly one pair of node types, e.g. `accessed` from `employee` to `report`.
  Its edges should come only from requests the policy allowed.
- Extra columns are allowed and ignored by the HGNN.

## scenarios.json (appeal evaluation only)

Optional. Only `scripts/evaluate/evaluate_knn.py` reads it; training and the running service do not.
Each scenario is an appeal with a known answer: the pairs of a rule that was removed from the access
edges (`hidden/<name>.csv`), and the predicates of that rule.

```json
{
  "target_relation": "accessed",
  "object_identity": false,
  "object_values": false,
  "max_size": 2,
  "scenarios": [
    {
      "name": "manager",
      "appeal": ["alice", "report_105"],
      "expected": [
        {"kind": "shared", "relation": "member_of", "other": "member_of"},
        {"kind": "user_has", "relation": "holds", "other": "role_manager"}
      ],
      "hidden": "hidden/manager.csv"
    },
    {"name": "one_off", "appeal": ["bob", "report_731"], "expected": null, "hidden": null}
  ]
}
```

| Field | Meaning |
|---|---|
| `target_relation` | Same as `--target-relation` for training |
| `object_identity`, `object_values`, `max_size` | Candidate options: allow `object is <id>`, allow `object has <value>`, max predicates per candidate (defaults `false`, `false`, `2`) |
| `appeal` | The (user, object) pair that is appealed; must not be in the access edges |
| `expected` | Predicates of the hidden rule (kinds: `user_has`, `object_has`, `shared`, `direct`, `object_is`), or `null` for a one-off appeal from which nothing should be generalized |
| `hidden` | CSV with `user,object` rows: every pair the hidden rule grants and the access edges leave out, or `null` |

The data folder then looks like:

```
nodes.csv
edges.csv            without the hidden pairs
scenarios.json
hidden/manager.csv
```
