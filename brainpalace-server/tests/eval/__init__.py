"""Retrieval evaluation harness (phase 010).

Builds a throwaway index over a small fixed fixture corpus and scores a
committed set of query cases (recall@k, MRR) so retrieval-affecting changes can
be measured instead of shipped blind. Directional, not pass/fail — NOT part of
the QA gate. See docs/EVALUATION.md.
"""
