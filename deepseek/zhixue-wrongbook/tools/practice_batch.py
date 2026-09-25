"""出题流程的批量执行器：对每条生成题先过 check_practice，再跑 submit_solution。

对应 SKILL.md 场景 3 的第 5~6 步：
  5. 每题都要 check_practice 过一遍（硬约束失败 → 改题重来，最多 3 次）
  6. 自己解一遍，用 submit_solution 与标准答案比对

用法
----
    .venv/Scripts/python tools/practice_batch.py payload.json

输入格式（数组）
---------------
    [{"fingerprint": "母题指纹",
      "gen_id": "p_001",
      "candidate": {"gen_id":"p_001","qtype":"单选题",
                    "knowledge_points":[...],"difficulty":0.9,
                    "stem_text":"..."},
      "submitted_answer": "B",      # 我独立解出来的答案
      "standard_answer": "B"},      # 生成题自己声称的答案

注意：`standard_answer` 必须传。不传的话 submit_solution 会拿生成题的答案去和
**母题**的标准答案比，得到的 mismatch 没有校验意义（server.py 里对此有显式告警）。
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
    args = ap.parse_args()

    import server

    items = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = [items]

    print(f"待校验 {len(items)} 道生成题\n")
    ok_n = 0
    for i, it in enumerate(items, 1):
        fp = it["fingerprint"]
        cand = it["candidate"]
        gid = cand.get("gen_id") or it.get("gen_id") or f"p_{i:03d}"
        cand["gen_id"] = gid
        print("=" * 72)
        print(f"[{i}] {gid}  ← 母题 {fp[:16]}  qtype={cand.get('qtype')}  "
              f"diff={cand.get('difficulty')}")

        res = await server.mcp.call_tool("check_practice", {
            "fingerprint": fp, "candidate": json.dumps(cand, ensure_ascii=False)})
        try:
            chk = json.loads(text_of(res))
        except Exception:
            print("  check_practice 返回非 JSON：", text_of(res)[:400])
            continue
        ok = bool(chk.get("ok"))
        print(f"  check_practice → {'PASS' if ok else 'FAIL'}")
        for item in chk.get("checks") or []:
            flag = "✓" if item["passed"] else ("✗" if item["kind"] == "hard" else "·")
            print(f"     {flag} [{item['kind']}] {item['name']}: {item['value']}  {item['detail']}")
        for e in chk.get("errors") or []:
            print(f"     ✗ {e}")
        for w in chk.get("warnings") or []:
            print(f"     ⚠ {w}")
        if not ok:
            print("  → 硬约束未通过，需改题重来（不计入交付）")
            continue

        res = await server.mcp.call_tool("submit_solution", {
            "fingerprint": fp,
            "submitted_answer": it["submitted_answer"],
            "standard_answer": it["standard_answer"],
            "gen_id": gid,
        })
        try:
            sol = json.loads(text_of(res))
        except Exception:
            print("  submit_solution 返回非 JSON：", text_of(res)[:400])
            continue
        cmp_ = sol.get("comparison") or {}
        verdict = cmp_.get("verdict")
        print(f"  submit_solution → verdict={verdict}  ({cmp_.get('reason')})")
        print(f"     我方答案: {cmp_.get('submitted_norm')}")
        print(f"     生成题答案: {cmp_.get('standard_norm')}")
        for k in ("warning", "practice_recorded", "history_recorded"):
            if sol.get(k):
                print(f"     ⚠ {k}: {sol[k]}")
        if verdict in ("match", "numeric_match"):
            ok_n += 1
        else:
            print("  → 未得到确定性一致结论，需人工确认（不静默放过）")
    print("\n" + "=" * 72)
    print(f"汇总：{ok_n}/{len(items)} 道生成题通过校验并与答案比对一致")
    return 0 if ok_n == len(items) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
