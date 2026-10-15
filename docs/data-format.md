# Corax graph data format

Corax does not know about any specific domain. Any application (a campus, a hospital, a shop)
describes its users, objects and relations as a typed graph in two CSV files.

## nodes.csv

| Column | Meaning |
|---|---|
| `id` | Unique node id across the whole file, e.g. `lecturer_budi` |
| `type` | Node type, e.g. `lecturer`, `student`, `program` |

```csv
id,type
lecturer_budi,lecturer
student_ani,student
program_IF,program
```

## edges.csv

| Column | Meaning |
|---|---|
| `src` | Source node id (must exist in `nodes.csv`) |
| `relation` | Relation name, e.g. `teaches`, `member_of` |
| `dst` | Destination node id (must exist in `nodes.csv`) |

```csv
src,relation,dst
lecturer_budi,member_of,program_IF
lecturer_budi,accessed,student_ani
```

The edge type is the triple `(source type, relation, destination type)`, derived from the node types.
The same relation name may connect different node types, e.g. `(lecturer, member_of, program)` and
`(student, member_of, program)` are two edge types.

## Rules

- Every node type must appear in at least one edge.
- One relation is the **target relation** for link prediction (passed as `--target-relation`).
  It must connect exactly one pair of node types, e.g. `accessed` from `lecturer` to `student`.
  Its edges should come only from requests the policy allowed.
- Extra columns are allowed and ignored by the HGNN.
