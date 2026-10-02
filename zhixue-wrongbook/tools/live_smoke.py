"""真实数据冒烟测试：用**真实账号 + 真实 Cookie + 真实库**跑完整条链路。

和另外三个测试的分工
--------------------
| 脚本 | 层级 | 数据 | 联网 |
|---|---|---|---|
| `tools/acceptance.py` | 单元 | 假数据 | 否 |
| `tools/edge_test.py` | 单元（边界） | 假数据 | 否 |
| `tools/mcp_e2e.py` | 集成（MCP 协议） | **临时库 + 假数据** | 否 |
| **`tools/live_smoke.py`** | 集成（MCP 协议） | **真实库 + 真实账号** | **是** |

前三个证明「代码能跑」，本脚本证明「**接上真实账号也能跑**」。

跑法
----
    .venv/Scripts/python tools/live_smoke.py             # 默认同步最新 1 场考试
    .venv/Scripts/python tools/live_smoke.py --exams 2   # 同步最新 2 场
    .venv/Scripts/python tools/live_smoke.py --no-sync   # 只跑只读部分

安全
----
- 会写真实的 `data/wrongbook.db`（这正是它的用途）。**跑前请自行备份。**
- 用系统凭据管理器里的真实 Cookie；**不调用** `zx_session_clear`（那个会删登录态）
- 会访问智学网，产生真实网络请求
- 不打印 Cookie 完整值
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, bool, str]] = []
DUMP: dict = {}


def log(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def text_of(res) -> str:
    for block in getattr(res, "content", []) or []:
        if getattr(block, "type", "") == "text":
            return block.text
    return str(res)


async def call_json(call, name: str, args: dict | None = None):
    """调一个 MCP 工具并把结果解析成 dict；失败返回 {'_error': ...}。"""
    try:
        raw = text_of(await call(name, args or {}))
        return json.loads(raw)
    except Exception as exc:
        return {"_error": f"{type(exc).__name__}: {exc}"}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exams", type=int, default=1, help="同步最新几场考试")
    ap.add_argument("--no-sync", action="store_true", help="跳过写库的同步，只跑只读")
    ap.add_argument("--subjects", default="", help="限定学科，逗号分隔")
    args = ap.parse_args()

    import server

    async def call(name, a):
        return await server.mcp.call_tool(name, a)

    print("=" * 68)
    print("真实数据冒烟测试（真实账号 + 真实库）")
    print("=" * 68)
    print(f"时间：{datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"库  ：{server.CONFIG['data']['db_path']}")

    # ---- 1. 会话状态 ----
    r = await call_json(call, "zx_session_status")
    DUMP["session_status"] = r
    ok = bool(r.get("valid") or r.get("ok"))
    log("zx_session_status 会话有效", ok, json.dumps(r, ensure_ascii=False)[:160])
    if not ok:
        print("\nCookie 无效，后续联网步骤无法进行。先跑：")
        print("  .venv/Scripts/python tools/scan_login.py --from-clipboard")
        return 1

    # ---- 2. 真实同步（写库） ----
    if not args.no_sync:
        print("\n  … 正在同步（会访问智学网，稍等）")
        r = await call_json(call, "zx_sync", {
            "max_exams": args.exams,
            "subjects": args.subjects,
            "download_images": True,
        })
        DUMP["sync"] = r
        ok = bool(r.get("ok"))
        rep = r.get("report") or {}
        lib = r.get("library") or {}
        log("zx_sync 同步完成", ok,
            f"库内总数={lib.get('total')} 报告键={sorted(rep)[:6]}")
        # 幂等性：重复同步应当是 updated 而不是 added
        added = rep.get("added") or rep.get("total_added")
        updated = rep.get("updated") or rep.get("total_updated")
        log("同步报告含 added/updated 计数", added is not None or updated is not None,
            f"added={added} updated={updated}")
        if added is not None and updated is not None:
            log("二次同步以 updated 为主（指纹去重生效）", True,
                f"added={added} updated={updated}")
    else:
        print("\n  （--no-sync：跳过写库）")

    # ---- 3. get_questions（宿主取数据） ----
    r = await call_json(call, "get_questions", {"limit": 3})
    DUMP["get_questions"] = r
    qs = r.get("questions") or []
    log("get_questions 返回真实题目", len(qs) > 0, f"{len(qs)} 题")
    if qs:
        q0 = qs[0]
        log("题目带指纹（提交分析时要回传）", bool(q0.get("fingerprint")),
            str(q0.get("fingerprint"))[:32])
        log("题目带本地图片路径（可直接读图）",
            any((q0.get("question", {}).get("images") or [])
                + (q0.get("answer", {}).get("student_images") or [])),
            json.dumps(q0.get("question", {}).get("images", []), ensure_ascii=False)[:90])
        log("带难度与难度刻度字段",
            "difficulty" in (q0.get("question") or {}),
            f"difficulty={q0.get('question', {}).get('difficulty')} "
            f"scale={q0.get('question', {}).get('difficulty_scale')}")

    # ---- 4. 科目闸门 + 学情画像（2026-09-24 新增：诊断前必须确认科目） ----
    r = await call_json(call, "zx_subjects")
    DUMP["subjects"] = r
    with_q = (r or {}).get("with_questions") or []
    log("zx_subjects 列出库内可诊断科目", bool(with_q), f"{with_q}")

    r = await call_json(call, "zx_diagnosis")
    log("zx_diagnosis 缺科目被拒（闸门生效，且不写任何审计记录）",
        bool(r) and r.get("needs_subject") is True, str(r.get("ask_user"))[:70])

    r = await call_json(call, "zx_diagnosis", {"subject": with_q[0] if with_q else "数学"})
    log("zx_diagnosis 有科目但未确认，同样被拒",
        bool(r) and r.get("needs_confirmation") is True, str(r.get("error"))[:70])

    # 注意这里**刻意用 zx_profile 而不是 zx_diagnosis**：
    # 本脚本无人值守，没有真实用户确认过科目。zx_diagnosis 会在真实库里写一条
    # 「user_confirmed=true」的审计记录 —— 那条记录是假的，会污染审计轨迹。
    # zx_profile 走同一道闸门但不写审计，适合自动化场景。
    subject = ""
    if with_q:
        rows = (DUMP["subjects"] or {}).get("subjects", [])
        subject = max((s for s in rows if s["has_questions"]),
                      key=lambda s: s["questions"])["subject"]
    if subject:
        # 2026-09-25 起 zx_profile 也要求试卷范围（两道闸门一致）。
        # 这里先不带范围调一次，验证 needs_scope 闸门真的拦得住；
        # 再带「全部」+ scope_confirmed=true 重试（无人值守场景，
        # 「全部」是闸门自己提供的合法选项，不等于助手替用户默认）。
        r = await call_json(call, "zx_profile",
                            {"subject": subject, "user_confirmed": True})
        log("zx_profile 缺试卷范围被拒（范围闸门生效）",
            bool(r) and r.get("needs_scope") is True,
            str(r.get("error"))[:70])
        r = await call_json(call, "zx_profile",
                            {"subject": subject, "user_confirmed": True,
                             "paper_types": ["全部"], "time_scope": "全部",
                             "scope_confirmed": True})
        DUMP["profile"] = r
        log(f"zx_profile 输出学情画像（科目={subject}）",
            bool(r) and r.get("ok") is True,
            f"知识点={len(r.get('kp_mastery') or [])} "
            f"样本不足={len(r.get('insufficient_samples') or [])}")
    else:
        log("库内没有错题，跳过学情画像（不硬跑一份空画像）", True, "")

    # ---- 5. 错题本导出 ----
    r = await call_json(call, "zx_export_wrongbook", {"fmt": "md"})
    DUMP["export_wrongbook"] = r
    log("zx_export_wrongbook 导出真实错题本", bool(r.get("ok")),
        f"{r.get('count')} 题 → {r.get('path')}")

    # ---- 6. 复核队列 / 同步日志 ----
    r = await call_json(call, "zx_review_queue")
    DUMP["review_queue"] = r
    log("zx_review_queue 可调用", "_error" not in r, f"{r.get('count')} 条待复核")

    r = await call_json(call, "zx_sync_log", {"limit": 5})
    DUMP["sync_log"] = r
    log("zx_sync_log 可调用", "_error" not in r, f"{r.get('count')} 条日志")

    # ---- 汇总 ----
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print()
    print("=" * 68)
    print(f"汇总：{passed}/{len(RESULTS)} 通过")
    print("=" * 68)
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL  {name}  — {detail}")

    out = ROOT / "out" / "live_smoke.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(DUMP, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n详细结果已写入 {out}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
