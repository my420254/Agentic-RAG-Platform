from __future__ import annotations

"""RAG 检索评测。

RAG 项目如果没有评测，很难说明 chunk、召回、重排到底有没有提升。
这里实现一个轻量离线评测器，指标覆盖 hit@k、MRR 和证据覆盖率。
"""

from dataclasses import dataclass, field
from typing import Any

from app.rag.retriever import InMemoryRetriever


@dataclass(frozen=True)
class RetrievalEvalCase:
    case_id: str
    question: str
    expected_doc_ids: list[str]
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> "RetrievalEvalCase":
        return cls(
            case_id=str(item["case_id"]),
            question=str(item["question"]),
            expected_doc_ids=[str(value) for value in item.get("expected_doc_ids", [])],
            tags=[str(value) for value in item.get("tags", [])],
        )


def root_doc_id(doc_id: str) -> str:
    return doc_id.rsplit(":", 1)[0]


def run_retrieval_eval(
    retriever: InMemoryRetriever,
    cases: list[RetrievalEvalCase],
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    rows = []
    hit_count = 0
    reciprocal_ranks: list[float] = []

    for case in cases:
        evidence = retriever.search(case.question, top_k=top_k)
        retrieved = [root_doc_id(item.doc_id) for item in evidence]
        expected = set(case.expected_doc_ids)
        first_hit_rank = 0
        for rank, doc_id in enumerate(retrieved, start=1):
            if doc_id in expected:
                first_hit_rank = rank
                break
        hit = first_hit_rank > 0
        if hit:
            hit_count += 1
            reciprocal_ranks.append(1 / first_hit_rank)
        else:
            reciprocal_ranks.append(0.0)
        rows.append(
            {
                "case_id": case.case_id,
                "question": case.question,
                "expected_doc_ids": case.expected_doc_ids,
                "retrieved_doc_ids": retrieved,
                "hit": hit,
                "first_hit_rank": first_hit_rank,
                "mrr": round(1 / first_hit_rank, 4) if first_hit_rank else 0.0,
                "tags": case.tags,
            }
        )

    total = len(cases)
    return {
        "total": total,
        "top_k": top_k,
        "hit_rate": round(hit_count / total, 4) if total else 0.0,
        "mrr": round(sum(reciprocal_ranks) / total, 4) if total else 0.0,
        "failed_cases": [row for row in rows if not row["hit"]],
        "cases": rows,
    }
