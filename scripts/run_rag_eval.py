from __future__ import annotations

"""运行离线检索评测。

这个脚本不依赖启动 FastAPI，适合在 CI 或面试演示时快速证明检索链路有效。
"""

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.rag.evaluator import RetrievalEvalCase, run_retrieval_eval  # noqa: E402
from app.rag.retriever import InMemoryRetriever  # noqa: E402


def load_demo_corpus(retriever: InMemoryRetriever, demo_dir: Path) -> None:
    for path in sorted(demo_dir.glob("*.md")):
        retriever.add_document(path.stem, path.read_text(encoding="utf-8"), source="demo_knowledge")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(ROOT / "data" / "eval" / "retrieval_cases.json"))
    parser.add_argument("--demo-dir", default=str(ROOT / "data" / "demo_knowledge"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    retriever = InMemoryRetriever()
    load_demo_corpus(retriever, Path(args.demo_dir))
    raw_cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = [RetrievalEvalCase.from_dict(item) for item in raw_cases]
    result = run_retrieval_eval(retriever, cases, top_k=args.top_k)

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
