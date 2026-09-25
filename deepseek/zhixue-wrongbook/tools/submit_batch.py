"""批量提交错因分析：读一个 JSON 数组，逐条调 submit_analysis，汇总闸门结果。

为什么要有它
------------
分析 20+ 道错题时，一道一道手写 `mcp_cli.py submit_analysis '{...}'` 既啰嗦
又容易把 JSON 引号写坏。把「一批分析」写成一个 JSON 文件再跑本脚本，
既省事又能留下可审计的输入快照。

用法
----
    .venv/Scripts/python tools/submit_batch.py D:/末秋/_tmp/batch1_payload.json
    .venv/Scripts/python tools/submit_batch.py batch1.json --dry-run
    .venv/Scripts/python tools/submit_batch.py batch1.json --by "workbuddy:v4.1"

输入格式（数组，每条一个题）
---------------------------
    [{"fingerprint": "...", "error_type": "概念不清",
      "knowledge_points": ["英语/其他语法/词义辨析"],
      "evidence": ["...「原文片段」..."],
      "confidence": 0.7, "needs_review": false}, ...]

`analyzed_by` / `prompt_version` 可逐条给；不给就用 `--by` 和 config 里的
`host.prompt_version`。这两项是硬闸门，不能空。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def text_of(res) -> str:
    for block in getattr(res, "content", []) or []:
        if getattr(block, "type", "") == "text":
            return block.text
    return str(res)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("payload", help="JSON 数组文件")
    ap.add_argument("--by", default="workbuddy:deepseek-v4.1-flash",
                    help="analyzed_by（可追溯性，硬闸门）")
    ap.add_argument("--prompt-version", default="",
                    help="默认取 config 的 host.prompt_version")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不提交")
    args = ap.parse_args()

    import server

    items = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = [items]
    pv = (args.prompt_version
          or getattr(getattr(server.CONFIG, "host", None), "prompt_version", "")
          or "analyze-v3")

    print(f"待提交 {len(items)} 条 | analyzed_by={args.by} | prompt_version={pv}")
    if args.dry_run:
        print(json.dumps(items, ensure_ascii=False, indent=1))
        return 0

    ok_n = 0
    for i, it in enumerate(items, 1):
        # knowledge_points / evidence 现在**数组和字符串都接受**（2026-09-25 修：
        # 此前签名只写 str，传数组会在调用层被 pydantic 挡掉并吐一屏 ValidationError）。
        # 这里仍然拼成 `|` 分隔的字符串，是为了兼容老输入文件、也让日志更好读；
        # 传数组同样能过。
        kps = it.get("knowledge_points") or []
        evs = it.get("evidence") or []
        if isinstance(kps, str):
            kps = [kps]
        if isinstance(evs, str):
            evs = [evs]
        for frag in list(kps) + list(evs):
            if "|" in str(frag):
                print(f"  ⚠ 第 {i} 条片段含 `|`，会被错误切分：{str(frag)[:40]}")
        payload = {
            "fingerprint": it["fingerprint"],
            "error_type": it.get("error_type", ""),
            "knowledge_points": "|".join(str(x) for x in kps),
            "evidence": "|".join(str(x) for x in evs),
            "confidence": it.get("confidence", 0.0),
            "needs_review": bool(it.get("needs_review", False)),
            "analyzed_by": it.get("analyzed_by") or args.by,
            "prompt_version": it.get("prompt_version") or pv,
        }
        res = await server.mcp.call_tool("submit_analysis", payload)
        raw = text_of(res)
        try:
            data = json.loads(raw)
        except Exception:
            print(f"\n[{i}] {payload['fingerprint'][:16]}  ← 非 JSON 返回")
            print(raw[:800])
            continue
        ok = bool(data.get("ok"))
        ok_n += ok
        tag = "PASS" if ok else "FAIL"
        print(f"\n[{i}] {tag}  {payload['fingerprint'][:16]}  "
              f"{payload['error_type']}  conf={payload['confidence']}")
        for e in data.get("errors") or []:
            print(f"      ✗ {e}")
        for w in data.get("warnings") or []:
            print(f"      ⚠ {w}")
        norm = data.get("normalized") or {}
        if norm.get("knowledge_points"):
            print(f"      kp={norm['knowledge_points']}")
    print(f"\n汇总：{ok_n}/{len(items)} 通过")
    return 0 if ok_n == len(items) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
