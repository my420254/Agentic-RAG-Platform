from __future__ import annotations

"""把 data/demo_knowledge 下的 Markdown 文档写入本地 API。"""

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def post_json(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://localhost:18080")
    parser.add_argument("--demo-dir", default=str(ROOT / "data" / "demo_knowledge"))
    args = parser.parse_args()

    demo_dir = Path(args.demo_dir)
    for path in sorted(demo_dir.glob("*.md")):
        result = post_json(
            f"{args.api_base.rstrip('/')}/api/ingest",
            {
                "doc_id": path.stem,
                "text": path.read_text(encoding="utf-8"),
                "source": "demo_knowledge",
            },
        )
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
