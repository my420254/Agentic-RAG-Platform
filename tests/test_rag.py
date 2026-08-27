from app.rag.chunker import split_text
from app.rag.retriever import InMemoryRetriever


def test_split_text_uses_overlap():
    chunks = split_text("abcdef" * 100, max_chars=100, overlap=20)
    assert len(chunks) > 1
    assert chunks[0][-20:] == chunks[1][:20]


def test_retriever_returns_ranked_evidence():
    retriever = InMemoryRetriever()
    retriever.add_document("doc", "Redis 可以保存 Agent 的短期记忆和 checkpoint。")
    evidence = retriever.search("Redis Agent checkpoint")
    assert evidence
    assert evidence[0].score >= evidence[-1].score
