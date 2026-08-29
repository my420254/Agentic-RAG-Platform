from __future__ import annotations

"""演示知识库加载工具。

真实项目中，知识库通常来自对象存储、数据库或文档平台。这个展示项目把一组
Markdown 文档放在 `data/demo_knowledge`，用于稳定演示 RAG、Agent Harness、
故障工单和高并发排障等场景。
"""

from dataclasses import dataclass
from pathlib import Path

from app.rag.retriever import InMemoryRetriever


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DEMO_DIR = ROOT / "data" / "demo_knowledge"


@dataclass(frozen=True)
class DemoDocumentLoadResult:
    doc_id: str
    chunks: int
    path: str


def load_demo_knowledge(
    retriever: InMemoryRetriever,
    *,
    demo_dir: Path = DEFAULT_DEMO_DIR,
) -> list[DemoDocumentLoadResult]:
    """把仓库自带 Markdown 文档加载到检索器中。

    `retriever.add_document` 对同一个 doc_id 是幂等覆盖，因此这个函数可以在
    启动和前端“一键加载”按钮里重复调用。
    """

    if not demo_dir.exists():
        return []

    results: list[DemoDocumentLoadResult] = []
    for path in sorted(demo_dir.glob("*.md")):
        chunks = retriever.add_document(
            path.stem,
            path.read_text(encoding="utf-8"),
            source="demo_knowledge",
        )
        results.append(DemoDocumentLoadResult(doc_id=path.stem, chunks=chunks, path=str(path)))
    return results
