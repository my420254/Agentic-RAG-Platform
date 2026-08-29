from __future__ import annotations

"""RAG 证据质量门控。

真实 RAG 系统不能只要检索器返回了 top_k 就直接生成答案。这里把“证据是否足够”
做成独立模块，便于后续替换为 reranker 分数、LLM-as-judge 或人工标注阈值。
"""

from dataclasses import dataclass

from app.agent.state import Evidence


@dataclass(frozen=True)
class EvidenceQuality:
    enough: bool
    top_score: float
    evidence_count: int
    reason: str

    def to_dict(self) -> dict:
        return {
            "enough": self.enough,
            "top_score": self.top_score,
            "evidence_count": self.evidence_count,
            "reason": self.reason,
        }


def assess_evidence(evidence: list[Evidence], *, min_top_score: float = 0.015) -> EvidenceQuality:
    """根据检索证据给出可解释的质量判断。

    当前检索器使用 RRF，分数通常不大，所以阈值不能按 cosine/reranker 的尺度设置。
    生产版本应按离线评测集重新标定阈值。
    """

    if not evidence:
        return EvidenceQuality(
            enough=False,
            top_score=0.0,
            evidence_count=0,
            reason="没有召回任何证据",
        )
    top_score = max(item.score for item in evidence)
    if top_score < min_top_score:
        return EvidenceQuality(
            enough=False,
            top_score=top_score,
            evidence_count=len(evidence),
            reason=f"最高证据分数低于阈值 {min_top_score}",
        )
    return EvidenceQuality(
        enough=True,
        top_score=top_score,
        evidence_count=len(evidence),
        reason="证据数量和最高分满足生成条件",
    )
