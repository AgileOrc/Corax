from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from risk import RiskModel


@dataclass(frozen=True)
class SimilarCase:
    user: str
    object: str
    similarity: float
    user_similarity: float
    object_similarity: float


class SimilarityIndex:
    def __init__(self, model: RiskModel):
        self.user_ids = list(model.users)
        self.object_ids = list(model.objects)
        self.user_row = {user: i for i, user in enumerate(self.user_ids)}
        self.object_row = {obj: i for i, obj in enumerate(self.object_ids)}
        self.users = _unit_rows(np.stack(list(model.users.values())))
        self.objects = _unit_rows(np.stack(list(model.objects.values())))

    def find(
        self,
        user: str,
        obj: str,
        k: int = 10,
        has_access: Callable[[str, str], bool] = lambda _user, _obj: False,
        max_per_user: int | None = 2,
    ) -> list[SimilarCase]:
        if user not in self.user_row:
            raise ValueError(f"unknown user {user!r}")
        if obj not in self.object_row:
            raise ValueError(f"unknown object {obj!r}")

        user_sim = self.users @ self.users[self.user_row[user]]
        object_sim = self.objects @ self.objects[self.object_row[obj]]
        user_order = np.argsort(-user_sim, kind="stable")
        object_order = np.argsort(-object_sim, kind="stable")

        def allowed(u: str, o: str) -> bool:
            return (u, o) != (user, obj) and not has_access(u, o)

        m = max(k, 1)
        while True:
            top_users, top_objects = user_order[:m], object_order[:m]
            block = (user_sim[top_users][:, None] + object_sim[top_objects][None, :]) / 2
            found, per_user = [], Counter()
            for flat in np.argsort(-block, axis=None, kind="stable"):
                i, j = divmod(int(flat), len(top_objects))
                u, o = self.user_ids[top_users[i]], self.object_ids[top_objects[j]]
                if max_per_user is not None and per_user[u] >= max_per_user:
                    continue
                if allowed(u, o):
                    per_user[u] += 1
                    found.append((float(block[i, j]), top_users[i], top_objects[j]))
                    if len(found) == k:
                        break

            outside = []
            if m < len(user_order):
                outside.append((user_sim[user_order[m]] + object_sim[object_order[0]]) / 2)
            if m < len(object_order):
                outside.append((user_sim[user_order[0]] + object_sim[object_order[m]]) / 2)
            if not outside or (len(found) == k and found[-1][0] >= max(outside)):
                break
            m *= 2

        return [
            SimilarCase(
                user=self.user_ids[u],
                object=self.object_ids[o],
                similarity=score,
                user_similarity=float(user_sim[u]),
                object_similarity=float(object_sim[o]),
            )
            for score, u, o in found
        ]


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    matrix = matrix.astype(np.float64)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)
