from __future__ import annotations

"""轻量混合检索实现。

公开仓库应该在普通机器上开箱可跑，因此这里不强制下载 embedding 模型。
为了仍然体现生产 RAG 的检索形态，本文件实现 BM25-style 词项排名、
确定性的稀疏向量相似度排名，并用 RRF 做结果融合。
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import blake2b
import math
import re

from app.agent.state import Evidence
from app.rag.chunker import split_text


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
VECTOR_DIM = 256


def tokenize(text: str) -> list[str]:
    # 英文和 API 名称保留词级 token；中文额外加入相邻双字 token，
    # 这样“幻觉”这类词不会只被拆成单字。
    tokens = [token.lower() for token in TOKEN_RE.findall(text or "")]
    chinese_chars = [token for token in tokens if "\u4e00" <= token <= "\u9fff"]
    tokens.extend(
        chinese_chars[index] + chinese_chars[index + 1]
        for index in range(len(chinese_chars) - 1)
    )
    return tokens


def sparse_hash_vector(tokens: list[str]) -> dict[int, float]:
    # 这不是真正的语义 embedding，而是一个稳定、轻量、无模型依赖的向量近似。
    # 这样可以先把“向量排名 + RRF 融合”的接口做出来。
    counts: Counter[int] = Counter(stable_bucket(token) for token in tokens)
    norm = math.sqrt(sum(value * value for value in counts.values())) or 1.0
    return {index: value / norm for index, value in counts.items()}


def stable_bucket(token: str) -> int:
    # Python 内置 hash 每个进程会加盐，不适合做稳定测试。
    # 这里用 blake2b 保证同一个 token 每次都落到同一个桶。
    digest = blake2b(token.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big") % VECTOR_DIM


def cosine_sparse(left: dict[int, float], right: dict[int, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(index, 0.0) for index, value in left.items())


@dataclass
class DocumentChunk:
    doc_id: str
    text: str
    source: str
    token_counts: Counter[str]
    token_set: set[str]
    vector: dict[int, float]

    @property
    def length(self) -> int:
        return sum(self.token_counts.values())


class InMemoryRetriever:
    """带 BM25、轻量向量分数和 RRF 融合的内存检索器。

    hash vector 只是为了让仓库不下载模型也能跑。生产版本可以把 `_vector_ranking`
    替换成 embedding 模型和向量数据库，外层仍然返回同一个 Evidence API。
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
        # 同一个 doc_id 再次写入时先删除旧 chunk。
        # 否则重复上传会悄悄制造重复证据，影响检索分数和引用结果。
        self._chunks = [
            chunk
            for chunk in self._chunks
            if chunk.doc_id != doc_id and not chunk.doc_id.startswith(f"{doc_id}:")
        ]
        count = 0
        for index, chunk in enumerate(split_text(text)):
            tokens = tokenize(chunk)
            self._chunks.append(
                DocumentChunk(
                    doc_id=f"{doc_id}:{index}",
                    text=chunk,
                    source=source,
                    token_counts=Counter(tokens),
                    token_set=set(tokens),
                    vector=sparse_hash_vector(tokens),
                )
            )
            count += 1
        return count

    def list_documents(self) -> list[dict]:
        """按原始文档维度汇总当前知识库。

        内部 chunk id 形如 `doc_id:index`，对外展示时需要聚合回文档视角。
        """

        documents: dict[str, dict] = {}
        for chunk in self._chunks:
            root_doc_id = chunk.doc_id.rsplit(":", 1)[0]
            item = documents.setdefault(
                root_doc_id,
                {
                    "doc_id": root_doc_id,
                    "source": chunk.source,
                    "chunks": 0,
                    "tokens": 0,
                    "sample": chunk.text[:120],
                },
            )
            item["chunks"] += 1
            item["tokens"] += chunk.length
        return sorted(documents.values(), key=lambda item: item["doc_id"])

    def stats(self) -> dict:
        documents = self.list_documents()
        return {
            "documents": len(documents),
            "chunks": len(self._chunks),
            "tokens": sum(item["tokens"] for item in documents),
            "sources": sorted({item["source"] for item in documents}),
        }

    def clear_user_documents(self) -> int:
        """清空用户临时写入文档，保留内置知识和演示知识。"""

        before = len(self._chunks)
        self._chunks = [
            chunk
            for chunk in self._chunks
            if chunk.source in {"built_in", "demo_knowledge"}
        ]
        return before - len(self._chunks)

    def search(self, query: str, *, top_k: int = 5) -> list[Evidence]:
        # 对外只返回 Evidence，workflow 不关心底层检索器怎么实现。
        # 后续替换 Milvus、pgvector 或 Elasticsearch 时，上层代码不用改。
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        bm25_ranking = self._bm25_ranking(query_tokens)
        vector_ranking = self._vector_ranking(query_tokens)
        fused = self._rrf_fuse(
            [("bm25", bm25_ranking), ("vector", vector_ranking)],
            top_k=top_k,
        )
        return [
            Evidence(
                doc_id=chunk.doc_id,
                text=chunk.text,
                source=chunk.source,
                score=round(score, 4),
                metadata={
                    "fusion": "rrf",
                    "bm25_score": round(details.get("bm25", 0.0), 4),
                    "vector_score": round(details.get("vector", 0.0), 4),
                },
            )
            for chunk, score, details in fused
        ]

    def diagnose(self, query: str, *, top_k: int = 5) -> dict:
        """返回检索诊断信息，用于前端和面试展示。

        普通 `/api/chat` 只需要 Evidence；诊断接口会额外暴露 query tokens、
        原始 BM25/vector 排名和融合结果，方便解释“为什么召回这个 chunk”。
        """

        query_tokens = tokenize(query)
        bm25 = self._bm25_ranking(query_tokens)
        vector = self._vector_ranking(query_tokens)
        fused = self._rrf_fuse([("bm25", bm25), ("vector", vector)], top_k=top_k)
        return {
            "query": query,
            "tokens": query_tokens,
            "bm25": [
                {"doc_id": chunk.doc_id, "score": round(score, 4)}
                for chunk, score in bm25[:top_k]
            ],
            "vector": [
                {"doc_id": chunk.doc_id, "score": round(score, 4)}
                for chunk, score in vector[:top_k]
            ],
            "fused": [
                {
                    "doc_id": chunk.doc_id,
                    "score": round(score, 4),
                    "details": {key: round(value, 4) for key, value in details.items()},
                    "text": chunk.text,
                    "source": chunk.source,
                }
                for chunk, score, details in fused
            ],
        }

    def _bm25_ranking(self, query_tokens: list[str]) -> list[tuple[DocumentChunk, float]]:
        # BM25-style 分数适合精确业务词：错误码、产品名、API 名、表字段和实体名。
        if not self._chunks:
            return []
        total_docs = len(self._chunks)
        avgdl = sum(chunk.length for chunk in self._chunks) / total_docs
        query_counts = Counter(query_tokens)
        document_frequency: Counter[str] = Counter()
        for chunk in self._chunks:
            document_frequency.update(chunk.token_set)

        k1 = 1.5
        b = 0.75
        ranking: list[tuple[DocumentChunk, float]] = []
        for chunk in self._chunks:
            score = 0.0
            for term, query_tf in query_counts.items():
                tf = chunk.token_counts.get(term, 0)
                if tf == 0:
                    continue
                df = document_frequency[term]
                idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
                denominator = tf + k1 * (1 - b + b * chunk.length / max(avgdl, 1e-9))
                score += query_tf * idf * (tf * (k1 + 1)) / denominator
            if score > 0:
                ranking.append((chunk, score))
        return sorted(ranking, key=lambda item: item[1], reverse=True)

    def _vector_ranking(self, query_tokens: list[str]) -> list[tuple[DocumentChunk, float]]:
        # 如果项目升级为生产原型，优先把这个函数替换为真实 embedding + 向量库。
        query_vector = sparse_hash_vector(query_tokens)
        ranking = [
            (chunk, cosine_sparse(query_vector, chunk.vector))
            for chunk in self._chunks
        ]
        return sorted(
            ((chunk, score) for chunk, score in ranking if score > 0),
            key=lambda item: item[1],
            reverse=True,
        )

    @staticmethod
    def _rrf_fuse(
        ranking_groups: list[tuple[str, list[tuple[DocumentChunk, float]]]],
        *,
        top_k: int,
        rrf_k: int = 60,
    ) -> list[tuple[DocumentChunk, float, dict[str, float]]]:
        # RRF 使用排名而不是原始分数，因此不需要强行校准不同检索器的分数尺度。
        scores: defaultdict[str, float] = defaultdict(float)
        details: defaultdict[str, dict[str, float]] = defaultdict(dict)
        chunks: dict[str, DocumentChunk] = {}

        for label, ranking in ranking_groups:
            for rank, (chunk, raw_score) in enumerate(ranking, start=1):
                chunks[chunk.doc_id] = chunk
                scores[chunk.doc_id] += 1 / (rrf_k + rank)
                details[chunk.doc_id][label] = raw_score

        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
        return [
            (chunks[doc_id], score, details[doc_id])
            for doc_id, score in ordered
        ]


retriever = InMemoryRetriever()
