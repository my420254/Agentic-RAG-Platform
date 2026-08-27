from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.agent.state import Evidence
from app.rag.chunker import split_text


TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text or "")]


@dataclass
class DocumentChunk:
    doc_id: str
    text: str
    source: str
    tokens: set[str]


class InMemoryRetriever:
    """Keyword retriever with rerank hooks.

    This intentionally keeps the demo dependency-light. In production, replace
    `search` with vector/BM25 hybrid retrieval and keep the same Evidence API.
    """

    def __init__(self) -> None:
        self._chunks: list[DocumentChunk] = []
        self.add_document(
            "rag_handbook",
            """
            RAG 幻觉控制需要从检索和生成两端做约束：文档清洗、chunk 粒度、metadata filter、
            hybrid search、rerank、citation 约束、证据不足拒答，以及答案后校验。检索结果和实时
            工具结果冲突时，通常以数据库或工具返回的实时状态为准。
            """,
            source="built_in",
        )
        self.add_document(
            "agent_memory",
            """
            Agent 记忆建议分层管理：短期会话记忆放 Redis，长期偏好放向量库或关系库，
            工作记忆保存在图状态或 checkpoint，失败经验进入反思记忆。不要把所有历史都塞进向量库。
            """,
            source="built_in",
        )

    def add_document(self, doc_id: str, text: str, *, source: str = "upload") -> int:
        count = 0
        for index, chunk in enumerate(split_text(text)):
            self._chunks.append(
                DocumentChunk(
                    doc_id=f"{doc_id}:{index}",
                    text=chunk,
                    source=source,
                    tokens=set(tokenize(chunk)),
                )
            )
            count += 1
        return count

    def search(self, query: str, *, top_k: int = 5) -> list[Evidence]:
        query_tokens = set(tokenize(query))
        if not query_tokens:
            return []

        scored: list[Evidence] = []
        for chunk in self._chunks:
            overlap = query_tokens & chunk.tokens
            if not overlap:
                continue
            coverage = len(overlap) / max(len(query_tokens), 1)
            length_penalty = 1 / math.sqrt(max(len(chunk.tokens), 1))
            score = coverage + length_penalty
            scored.append(
                Evidence(
                    doc_id=chunk.doc_id,
                    text=chunk.text,
                    source=chunk.source,
                    score=round(score, 4),
                )
            )
        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]


retriever = InMemoryRetriever()
