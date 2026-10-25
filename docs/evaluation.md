# Evaluation

Every number below comes from a model trained once with `python -m hgnn` and scored by a script that
only loads it (`scripts/evaluate/`). Commands: [scripts](reference.md#scripts).

## Risk score: Amazon Access Samples

UCI Amazon Access Samples (CC BY 4.0): 36,063 users, 33,252 resources, 405 departments, 4,979 titles,
3,207 managers, 595,506 access edges. Split 80 / 10 / 10, the test edges are never used in training.

- **Random negatives**: random (user, resource) pairs without access.
- **Hard negatives**: a resource a peer of the user (same department, title or manager) has, but the
  user does not. They look normal, which makes them the realistic case for a misconfigured rule.

| Model | AUC random | AUC hard | Threshold | False deny | Detection random | Detection hard |
|---|---|---|---|---|---|---|
| Base | 0.995 | 0.675 | 0.988 | 0.85% | 90.5% | 6.4% |
| 50% hard negatives in training (chosen) | 0.985 | 0.897 | 0.978 | 0.94% | 78.8% | 24.5% |

The threshold is calibrated so that 99% of real access in the validation split passes. Training with
hard negatives costs some detection of random pairs but almost quadruples detection of hard ones, at
the same false deny rate.

## Appeals: hidden rules

Benchmarks: the university ABAC policies of [[6]](#references) and rules inferred from the Amazon data.
A rule is removed from the data, the model is trained without it, and one of its pairs is appealed. A
good appeal flow puts that rule near the top of the candidate list.

- **P@10**: share of the 10 similar cases that belong to the hidden rule.
- **Rank**: position of the hidden rule among the candidates.
- **Tier**: of the hidden rule, under the default limits (40% of users, 50 pairs, mean risk 0.5).

| Data | Appeals | P@10 | Rank 1 | Top 5 | Tier of the rule |
|---|---|---|---|---|---|
| Xu & Stoller university policies (5 files × 9 rules) | 45 | 34% | 26 | 37 | 45 large |
| Amazon, inferred "title T gets resource R" rules | 10 | 70% | 1 | 10 | 8 small, 2 large |
| Dummy data, "head of program reads own students" | 1 | 10% | 0 | 1 | small |

Appeals that should not generalize (a lecturer asking for a student of another program, a one-off
Amazon grant) produce only large candidates on every dataset, so they wait for an admin.

The Xu & Stoller rules are all large because each grants more than 50 pairs, and rules 1, 6 and 9 reach
60 to 75% of the users. That is the intended behavior: a rule that broad needs a human.

**Known weakness**: rules that slice by an attribute of the object only (Xu & Stoller rules 4 and 8)
rank lower (5 to 11), because every value of that attribute gives a narrower candidate.

## Reproduce

- Xu & Stoller: [Scripts → Xu & Stoller](reference.md#xu--stoller-abac-policies). The `.abac`
  files are GPL-3.0 and are not part of this repository.
- Amazon: [Scripts → Amazon](reference.md#amazon-dataset).
- Dummy data: [Getting started](getting-started.md).

## References

[1] J. Yin, G. Chen, W. Hong, J. Cao, H. Wang, and Y. Miao, "A heterogeneous graph-based semi-supervised learning framework for access control decision-making," *World Wide Web*, vol. 27, no. 4, Art. no. 35, 2024, doi: [10.1007/s11280-024-01275-2](https://doi.org/10.1007/s11280-024-01275-2).

[2] M. N. Nobi, R. Krishnan, Y. Huang, M. Shakarami, and R. Sandhu, "Toward deep learning based access control," in *Proc. 12th ACM Conf. Data Appl. Secur. Privacy (CODASPY)*, 2022, pp. 143–154, doi: [10.1145/3508398.3511497](https://doi.org/10.1145/3508398.3511497).

[3] M. N. Nobi, R. Krishnan, Y. Huang, and R. Sandhu, "Administration of machine learning based access control," in *Computer Security – ESORICS 2022* (Lecture Notes in Computer Science, vol. 13555), V. Atluri, R. Di Pietro, C. D. Jensen, and W. Meng, Eds. Cham, Switzerland: Springer, 2022, pp. 189–210, doi: [10.1007/978-3-031-17146-8_10](https://doi.org/10.1007/978-3-031-17146-8_10).

[4] M. You, J. Yin, H. Wang, J. Cao, K. Wang, Y. Miao, and E. Bertino, "A knowledge graph empowered online learning framework for access control decision-making," *World Wide Web*, vol. 26, no. 2, pp. 827–848, 2023, doi: [10.1007/s11280-022-01076-5](https://doi.org/10.1007/s11280-022-01076-5).

[5] M. Zhang, X. Wang, M. Zhu, C. Shi, Z. Zhang, and J. Zhou, "Robust heterogeneous graph neural networks against adversarial attacks," in *Proc. AAAI Conf. Artif. Intell.*, vol. 36, no. 4, 2022, pp. 4363–4370, doi: [10.1609/aaai.v36i4.20357](https://doi.org/10.1609/aaai.v36i4.20357).

[6] Z. Xu and S. D. Stoller, "Mining attribute-based access control policies," *IEEE Trans. Dependable Secure Comput.*, vol. 12, no. 5, pp. 533–545, Sep./Oct. 2015, doi: [10.1109/TDSC.2014.2369048](https://doi.org/10.1109/TDSC.2014.2369048).
