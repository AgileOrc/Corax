import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

import numpy as np

Structure = Mapping[str, Mapping[str, Sequence[str]]]
Pair = tuple[str, str]

@dataclass(frozen=True, order=True)
class Predicate:
    kind: str
    relation: str
    other: str = ""

    def holds(self, structure: Structure, user: str, obj: str) -> bool:
        user_facts, object_facts = structure.get(user, {}), structure.get(obj, {})
        if self.kind == "user_has":
            return self.other in user_facts.get(self.relation, ())
        if self.kind == "object_has":
            return self.other in object_facts.get(self.relation, ())
        if self.kind == "shared":
            return not set(user_facts.get(self.relation, ())).isdisjoint(
                object_facts.get(self.other, ())
            )
        if self.kind == "direct":
            return obj in user_facts.get(self.relation, ())
        if self.kind == "object_is":
            return obj == self.other
        raise ValueError(f"unknown predicate kind {self.kind!r}")

    def text(self) -> str:
        if self.kind == "user_has":
            return f"user {self.relation} {self.other}"
        if self.kind == "object_has":
            return f"object {self.relation} {self.other}"
        if self.kind == "shared":
            return f"user.{self.relation} = object.{self.other}"
        if self.kind == "object_is":
            return f"object is {self.other}"
        return f"user {self.relation} object"

@dataclass(frozen=True)
class Candidate:
    predicates: tuple[Predicate, ...]
    users: int | None
    pairs: int
    estimated: bool
    support: float
    examples: tuple[Pair, ...]

    def text(self) -> str:
        return " AND ".join(p.text() for p in self.predicates)

def predicates_for(
    structure: Structure,
    user: str,
    obj: str,
    identities: frozenset[str] = frozenset(),
    object_identity: bool = False,
) -> list[Predicate]:
    user_facts, object_facts = structure.get(user, {}), structure.get(obj, {})
    found = {Predicate("object_is", "", obj)} if object_identity else set()
    for relation, nodes in user_facts.items():
        if obj in nodes:
            found.add(Predicate("direct", relation))
        found.update(Predicate("user_has", relation, n) for n in nodes if n not in identities)
    for relation, nodes in object_facts.items():
        found.update(Predicate("object_has", relation, n) for n in nodes if n not in identities)
    for user_relation, user_nodes in user_facts.items():
        for object_relation, object_nodes in object_facts.items():
            if not set(user_nodes).isdisjoint(object_nodes):
                found.add(Predicate("shared", user_relation, object_relation))
    return sorted(found)

def sample_pairs(
    users: Sequence[str],
    objects: Sequence[str],
    has_access: Callable[[str, str], bool],
    n: int = 2000,
    seed: int = 0,
) -> list[Pair]:
    rng = random.Random(seed)
    pairs: list[Pair] = []
    for _ in range(n * 10):
        if len(pairs) == n:
            break
        user, obj = rng.choice(users), rng.choice(objects)
        if not has_access(user, obj):
            pairs.append((user, obj))
    return pairs

def candidates(
    structure: Structure,
    access: Mapping[str, frozenset[str]],
    appeal: Pair,
    users: Sequence[str],
    objects: Sequence[str],
    neighbours: Sequence[Pair] = (),
    max_size: int = 2,
    object_values: bool = False,
    object_identity: bool = False,
    exact_limit: int = 5_000_000,
    sample_size: int = 20_000,
) -> list[Candidate]:
    identities = frozenset(users) | frozenset(objects)
    vocabulary = [
        p
        for p in predicates_for(structure, *appeal, identities, object_identity)
        if object_values or p.kind != "object_has"
    ]
    combos = [c for size in range(1, max_size + 1) for c in combinations(vocabulary, size)]

    def support(combo) -> float:
        if not neighbours:
            return 0.0
        hits = sum(all(p.holds(structure, u, o) for p in combo) for u, o in neighbours)
        return hits / len(neighbours)

    small = len(users) * len(objects) <= exact_limit
    matrices = _Matrices(structure, access, users, objects) if small else None
    sample = None
    found, seen = [], set()
    for combo in combos:
        if all(p.kind in _SEPARABLE for p in combo):
            key, scope = _separable(structure, access, appeal, users, objects, combo)
        elif matrices is not None:
            key, scope = _exact(matrices, appeal, combo)
        else:
            if sample is None:
                sample = _sample_without_access(access, appeal, users, objects, sample_size)
            key, scope = _estimate(structure, sample, combo)
        if scope is None or key in seen:
            continue
        seen.add(key)
        found.append(Candidate(predicates=combo, support=support(combo), **scope))
    return sorted(found, key=_order)

_SEPARABLE = {"user_has", "object_has", "object_is"}

def _order(c: Candidate) -> tuple:
    users = -1 if c.users is None else c.users
    return (c.pairs, users, len(c.predicates), -c.support, c.predicates)

def opened_pairs(
    structure: Structure,
    access: Mapping[str, frozenset[str]],
    appeal: Pair,
    users: Sequence[str],
    objects: Sequence[str],
    predicates: Sequence[Predicate],
    exact_limit: int = 5_000_000,
) -> list[Pair]:
    if all(p.kind in _SEPARABLE for p in predicates):
        in_users, in_objects = _separable_sets(structure, users, objects, predicates)
        return [
            (u, o)
            for u in in_users
            for o in in_objects
            if o not in access.get(u, ()) and (u, o) != appeal
        ]
    if len(users) * len(objects) > exact_limit:
        raise ValueError("too many pairs to list a relational pattern exactly")
    matrices = _Matrices(structure, access, users, objects)
    opened = np.logical_and.reduce([matrices.of(p) for p in predicates]) & ~matrices.access
    opened[matrices.user_row[appeal[0]], matrices.object_col[appeal[1]]] = False
    return [(users[r], objects[c]) for r, c in zip(*np.nonzero(opened), strict=True)]

def _separable_sets(structure, users, objects, combo):
    user_conditions = [p for p in combo if p.kind == "user_has"]
    object_conditions = [p for p in combo if p.kind != "user_has"]
    in_users = [u for u in users if all(p.holds(structure, u, "") for p in user_conditions)]
    in_objects = [o for o in objects if all(p.holds(structure, "", o) for p in object_conditions)]
    return in_users, in_objects

def _separable(structure, access, appeal, users, objects, combo):
    in_users, in_objects = _separable_sets(structure, users, objects, combo)
    object_set = frozenset(in_objects)

    pairs = affected = 0
    examples = []
    for user in in_users:
        owned = access.get(user, frozenset())
        skip = owned | {appeal[1]} if user == appeal[0] else owned
        opened = len(object_set) - len(object_set & skip)
        if not opened:
            continue
        affected += 1
        pairs += opened
        for obj in in_objects:
            if len(examples) == 5:
                break
            if obj not in skip:
                examples.append((user, obj))
    if not pairs:
        return None, None
    key = ("separable", frozenset(in_users), object_set)
    return key, dict(users=affected, pairs=pairs, estimated=False, examples=tuple(examples))


def _exact(matrices, appeal, combo):
    opened = np.logical_and.reduce([matrices.of(p) for p in combo]) & ~matrices.access
    opened[matrices.user_row[appeal[0]], matrices.object_col[appeal[1]]] = False
    if not opened.any():
        return None, None
    rows, cols = np.nonzero(opened)
    examples = tuple(
        (matrices.users[r], matrices.objects[c]) for r, c in zip(rows[:5], cols[:5], strict=True)
    )
    scope = dict(
        users=int(opened.any(axis=1).sum()),
        pairs=int(opened.sum()),
        estimated=False,
        examples=examples,
    )
    return ("matrix", opened.tobytes()), scope

def _sample_without_access(access, appeal, users, objects, sample_size):
    def has_access(user, obj):
        return obj in access.get(user, ()) or (user, obj) == appeal

    without_access = len(users) * len(objects) - sum(len(v) for v in access.values()) - 1
    return sample_pairs(users, objects, has_access, n=sample_size), without_access

def _estimate(structure, sample, combo):
    pairs_sample, without_access = sample
    hits = [(u, o) for u, o in pairs_sample if all(p.holds(structure, u, o) for p in combo)]
    if not hits:
        return None, None
    scope = dict(
        users=None,
        pairs=round(len(hits) / len(pairs_sample) * without_access),
        estimated=True,
        examples=tuple(hits[:5]),
    )
    return ("estimate", combo), scope

class _Matrices:
    def __init__(self, structure, access, users, objects):
        self.structure, self.users, self.objects = structure, users, objects
        self.user_row = {u: i for i, u in enumerate(users)}
        self.object_col = {o: j for j, o in enumerate(objects)}
        self.access = np.zeros((len(users), len(objects)), dtype=bool)
        for user, owned in access.items():
            if user in self.user_row:
                for obj in owned:
                    if obj in self.object_col:
                        self.access[self.user_row[user], self.object_col[obj]] = True

    def _facts(self, nodes, relation):
        return [set(self.structure.get(n, {}).get(relation, ())) for n in nodes]

    def of(self, p: Predicate) -> np.ndarray:
        shape = (len(self.users), len(self.objects))
        if p.kind == "user_has":
            column = np.array([p.holds(self.structure, u, "") for u in self.users])
            return np.broadcast_to(column[:, None], shape)
        if p.kind in _SEPARABLE:
            row = np.array([p.holds(self.structure, "", o) for o in self.objects])
            return np.broadcast_to(row[None, :], shape)
        if p.kind == "shared":
            user_facts = self._facts(self.users, p.relation)
            object_facts = self._facts(self.objects, p.other)
            nodes = sorted(set().union(*user_facts) & set().union(*object_facts))
            index = {n: k for k, n in enumerate(nodes)}
            a = np.zeros((len(self.users), len(nodes)), dtype=np.float32)
            b = np.zeros((len(self.objects), len(nodes)), dtype=np.float32)
            for i, facts in enumerate(user_facts):
                a[i, [index[n] for n in facts if n in index]] = 1
            for j, facts in enumerate(object_facts):
                b[j, [index[n] for n in facts if n in index]] = 1
            return (a @ b.T) > 0
        if p.kind == "direct":
            matrix = np.zeros(shape, dtype=bool)
            for i, facts in enumerate(self._facts(self.users, p.relation)):
                for obj in facts:
                    if obj in self.object_col:
                        matrix[i, self.object_col[obj]] = True
            return matrix
        raise ValueError(f"unknown predicate kind {p.kind!r}")