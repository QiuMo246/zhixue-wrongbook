"""MCP 通道端到端演示：**通过真正的 MCP 工具调用**跑完整条业务链路。

和 tools/acceptance.py 的区别
-----------------------------
acceptance.py 直接调 Python 函数（单元级）；
本脚本走 MCP 协议调工具（集成级）——证明「宿主模型看到的接口」是能用的，
而不只是「我写的函数能跑」。

链路：
    zx_import_export_file（通道 A 造数据）
      → get_questions（宿主取数据）
      → zx_knowledge_points（标知识点前先查词表）
      → submit_analysis（宿主提交结论，走三道闸门）
      → submit_analysis 故意提交非法结论（验证会被拒）
      → zx_subjects（可诊断科目清单）
      → zx_diagnosis 诊断闸门七态（缺科目 / 科目未确认 / 缺范围 / 范围非法
         / 范围未确认 / 该科无数据 / 该范围无数据）+ 审计留痕
      → zx_profile（学情画像 + 薄弱项）
      → check_practice（生成题确定性校验）
      → submit_solution（宿主自解 + 比对）
      → zx_export_paper（导出练习卷）
      → zx_review_queue / zx_sync_log

跑法：
    .venv/Scripts/python tools/mcp_e2e.py

用临时库，跑完自动清理，**不会碰你真实的 data/wrongbook.db**。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="zx_mcp_e2e_", dir=str(ROOT / "data")))
# 关键：把数据路径指到临时目录，绝不碰真实库
os.environ["ZX_DB_PATH"] = str(TMP / "e2e.db")
os.environ["ZX_IMAGES_DIR"] = str(TMP / "images")
os.environ["ZX_TAXONOMY"] = str(ROOT / "data" / "taxonomy.yaml")
# 同样关键：凭据存储**不属于**数据库，光改 ZX_DB_PATH 保护不了它。
# 踩过的坑（2026-09-24）：下面会调 zx_session_clear，当时真的把用户存在
# Windows 凭据管理器里的 zx_cookie 删掉了。这里把命名空间整体挪到一次性名字上。
os.environ["ZX_CRED_SERVICE"] = "zhixue-wrongbook-e2e"
os.environ["ZX_CRED_KEY"] = "zx_cookie_e2e"
os.environ["ZX_CRED_FILE"] = str(TMP / ".session_e2e.bin")

RESULTS: list[tuple[str, bool, str]] = []


def log(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def text_of(res) -> str:
    """从 MCP 的 CallToolResult 里取出文本。"""
    for block in getattr(res, "content", []) or []:
        if getattr(block, "type", "") == "text":
            return block.text
    return str(res)


async def main() -> int:
    import server

    def call(name, args):
        return server.mcp.call_tool(name, args)

    print("=" * 68)
    print("MCP 通道端到端演示")
    print("=" * 68)
    print(f"临时数据目录：{TMP}")

    # ---- 1. 列工具 ----
    tools = await server.mcp.list_tools()
    names = sorted(t.name for t in tools)
    log("MCP 工具可枚举", len(names) >= 12, f"{len(names)} 个：{', '.join(names)}")

    # ---- 2. 通道 A 导入（造一个导出文件） ----
    export_file = TMP / "export.txt"
    export_file.write_text(
        "第一次月考 数学\n\n"
        "1. 已知关于 x 的一元二次方程 x^2 - 3x + m = 0 有两个不相等的实数根。\n"
        "答案：m < 9/4\n"
        "解析：由判别式 Δ = 9 - 4m > 0 得 m < 9/4。\n"
        "学生答案：m <= 9/4\n"
        "得分：3/8\n"
        "难度：0.62\n\n"
        "2. 计算 (-2)^3 + 5 的值\n"
        "答案：-3\n"
        "学生答案：-3\n"
        "得分：5/5\n",
        encoding="utf-8")
    r = json.loads(text_of(await call("zx_import_export_file", {
        "path": str(export_file), "subject": "数学",
        "exam_name": "第一次月考", "exam_date": "2026-09-15",
        "grade": "九年级上"})))
    log("zx_import_export_file 导入成功", r.get("ok") and r["imported"]["added"] == 2,
        f"added={r.get('imported', {}).get('added')}, "
        f"置信度统计={r.get('parse', {}).get('low_confidence')} 道低置信度")

    # ---- 3. get_questions ----
    r = json.loads(text_of(await call("get_questions", {"subject": "数学"})))
    log("get_questions 返回题目数据", r["count"] == 2,
        f"{r['count']} 题；第一条含题干={bool(r['questions'][0]['question']['stem_text'])}")
    fp = r["questions"][0]["fingerprint"]
    log("返回给宿主的数据里带指纹（提交时要回传）", bool(fp), fp)

    # ---- 3b. zx_knowledge_points（标知识点前先查词表，别猜） ----
    r = json.loads(text_of(await call("zx_knowledge_points", {})))
    log("zx_knowledge_points 总览可查（含历史 / 道法）",
        r.get("ok") is True
        and {"历史", "道法"} <= {s["subject"] for s in r["subjects"]},
        f"{r.get('subject_count')} 学科 / {r.get('point_count')} 知识点")
    r = json.loads(text_of(await call("zx_knowledge_points",
                                      {"subject": "数学", "chapter": "一元二次方程"})))
    log("按「学科 + 章节」列出知识点",
        r.get("ok") is True and "数学/一元二次方程/公式法与判别式" in r["points"],
        f"{r.get('count')} 个，例：{r['points'][:2]}")
    r = json.loads(text_of(await call("zx_knowledge_points",
                                      {"query": "判别式", "subject": "数学"})))
    log("按关键词搜索知识点（子串优先，模糊兜底）",
        r.get("count", 0) >= 1
        and all(m.startswith("数学/") for m in r["matches"]),
        str(r.get("matches"))[:90])
    r = json.loads(text_of(await call("zx_knowledge_points", {"subject": "生物"})))
    log("词表里没有的学科给出明确错误 + 可选学科",
        r.get("ok") is False and "历史" in (r.get("subjects") or []),
        r.get("error"))

    # ---- 4. submit_analysis 正例 ----
    r = json.loads(text_of(await call("submit_analysis", {
        "fingerprint": fp,
        "error_type": "概念不清",
        "knowledge_points": "数学/一元二次方程/公式法与判别式",
        "evidence": "「m <= 9/4」——把判别式大于零写成了大于等于零，临界情况判断错误",
        "confidence": 0.82,
        "analyzed_by": "host:mcp-e2e",
        "prompt_version": "analyze-v3"})))
    log("submit_analysis 正例通过并落库", r.get("ok") is True,
        f"知识点={r.get('stored', {}).get('knowledge_points')}")

    # ---- 5. submit_analysis 负例（必须被拒） ----
    r = json.loads(text_of(await call("submit_analysis", {
        "fingerprint": fp,
        "error_type": "粗心",
        "knowledge_points": "数学/一元二次方程/判别式的符号",
        "evidence": "学生不太认真",
        "confidence": 0.9,
        "analyzed_by": "host:mcp-e2e",
        "prompt_version": "analyze-v3"})))
    log("submit_analysis 非法结论被拒（枚举/词表/证据三道闸门）",
        r.get("ok") is False and len(r.get("errors", [])) >= 3,
        f"{len(r.get('errors', []))} 条错误：{r.get('errors')}")

    # ---- 6. 诊断闸门：科目 + 试卷范围，两问都要答 ------------------------
    # 2026-09-24 新增「必须先问科目」；2026-09-25 扩展为「还必须先问
    # 分析哪些试卷的错题」（类型 × 时间两个维度）。
    r = json.loads(text_of(await call("zx_subjects", {})))
    log("zx_subjects 列出可诊断科目（含题数与是否可诊断）",
        r.get("ok") is True
        and any(s["subject"] == "数学" and s["has_questions"] for s in r["subjects"]),
        f"{len(r['subjects'])} 个候选，库里有数据的：{r['with_questions']}")

    r = json.loads(text_of(await call("zx_diagnosis", {})))
    log("zx_diagnosis 缺科目被拒，并返回可直接念给用户的 ask_user",
        r.get("ok") is False and r.get("needs_subject") is True
        and "科目" in r.get("ask_user", ""), r.get("ask_user"))

    r = json.loads(text_of(await call("zx_diagnosis", {"subject": "数学"})))
    log("zx_diagnosis 有科目但未确认，同样被拒（user_confirmed 缺省 false）",
        r.get("ok") is False and r.get("needs_confirmation") is True,
        r.get("error"))

    r = json.loads(text_of(await call("zx_diagnosis",
                                      {"subject": "数学", "user_confirmed": True})))
    log("zx_diagnosis 只给科目、不给试卷范围 → needs_scope（2026-09-25 新增）",
        r.get("ok") is False and r.get("needs_scope") is True
        and "范围" in r.get("ask_user", ""), str(r.get("ask_user"))[:80])
    log("拒绝时带回可选范围（类型 × 时间）与各自题数，宿主照着问即可",
        bool(r.get("paper_types")) and bool(r.get("time_scopes"))
        and all("questions" in x for x in r["paper_types"]),
        f"类型 {len(r.get('paper_types') or [])} 项 / 时间 {len(r.get('time_scopes') or [])} 项")

    r = json.loads(text_of(await call("zx_diagnosis",
                                      {"subject": "数学", "user_confirmed": True,
                                       "paper_types": ["全部"], "time_scope": "全部"})))
    log("给了范围但未声明已确认 → needs_scope_confirmation",
        r.get("ok") is False and r.get("needs_scope_confirmation") is True,
        r.get("error"))

    r = json.loads(text_of(await call("zx_diagnosis",
                                      {"subject": "数学", "user_confirmed": True,
                                       "paper_types": ["全部"], "time_scope": "全部",
                                       "scope_confirmed": True})))
    log("两问都答后进**披露门禁**（包三）：先要出境同意，不直接吐题面",
        r.get("ok") is False and r.get("disclosure_required") is True
        and "egress" in r.get("disclosure", {})
        and "ask_user" in r,
        f"pii_found={r.get('disclosure', {}).get('pii_found')}")

    r2 = json.loads(text_of(await call("zx_diagnosis",
                                       {"subject": "数学", "user_confirmed": True,
                                        "paper_types": ["全部"], "time_scope": "全部",
                                        "scope_confirmed": True,
                                        "disclosure_confirmed": True})))
    log("披露确认后放行，返回经 PII 打码的样题与 audit_id",
        r2.get("ok") is True and bool(r2.get("audit_id"))
        and r2.get("profile", {}).get("subject_filter") == "数学"
        and bool(r2.get("scope", {}).get("label"))
        and isinstance(r2.get("redaction"), dict),
        f"audit_id={r2.get('audit_id')} 范围={r2.get('scope', {}).get('label')} "
        f"样本题={len(r2.get('sample_questions', []))} 道 "
        f"打码={r2.get('redaction', {}).get('applied')}")

    r3 = json.loads(text_of(await call("zx_diagnosis",
                                       {"subject": "数学", "user_confirmed": True,
                                        "paper_types": ["全部"], "time_scope": "全部",
                                        "scope_confirmed": True,
                                        "stats_only": True})))
    log("stats_only=true：只做统计诊断，题面原文不出境",
        r3.get("ok") is True and r3.get("stats_only") is True
        and r3.get("sample_questions") == []
        and bool(r3.get("profile", {}).get("kp_mastery")),
        f"audit_id={r3.get('audit_id')}")

    r = json.loads(text_of(await call("zx_diagnosis_log", {})))
    log("zx_diagnosis_log 留痕含科目 + 范围 + 三处声明（含披露确认）",
        r.get("count") == 2
        and r["logs"][0]["subject"] == "数学"
        and r["logs"][0]["user_confirmed"] is True
        and r["logs"][0]["scope_confirmed"] is True
        and r["logs"][0]["time_scope"] == "全部"
        and r["logs"][0]["disclosure_confirmed"] is False   # stats_only 那条
        and r["logs"][1]["disclosure_confirmed"] is True,   # 全量诊断那条
        f"{r.get('count')} 条（倒序）："
        f"{[(x['disclosure_confirmed'], x['time_scope']) for x in r['logs']]}")

    r = json.loads(text_of(await call("zx_diagnosis",
                                      {"subject": "数学", "user_confirmed": True,
                                       "paper_types": ["午练"], "time_scope": "全部",
                                       "scope_confirmed": True})))
    log("选中的范围里没有题 → no_data_in_scope（不悄悄放宽成「全部」）",
        r.get("ok") is False and r.get("no_data_in_scope") is True
        and "放宽" in str(r.get("hint", "")), r.get("error"))

    r = json.loads(text_of(await call("zx_diagnosis",
                                      {"subject": "历史", "user_confirmed": True,
                                       "paper_types": ["全部"], "time_scope": "全部",
                                       "scope_confirmed": True})))
    log("zx_diagnosis 该科无数据时明确拒绝（不静默给一份空画像）",
        r.get("ok") is False and r.get("no_data") is True, r.get("error"))

    r = json.loads(text_of(await call("zx_diagnosis",
                                      {"subject": "政治", "user_confirmed": True,
                                       "paper_types": ["全部"], "time_scope": "全部",
                                       "scope_confirmed": True})))
    log("科目别名归一化（政治 → 道法）", r.get("subject") == "道法", str(r.get("subject")))

    # ---- 6b. zx_profile ----
    r = json.loads(text_of(await call("zx_profile",
                                      {"subject": "数学", "user_confirmed": True,
                                       "paper_types": ["全部"], "time_scope": "全部",
                                       "scope_confirmed": True})))
    log("zx_profile 输出学情画像", r.get("ok") is True
        and "kp_mastery" in r and "method" in r,
        f"知识点 {len(r['kp_mastery'])} 个，样本不足 {len(r['insufficient_samples'])} 个"
        f"（样本量门槛生效）")
    r = json.loads(text_of(await call("zx_profile", {"subject": "数学"})))
    log("zx_profile 同样过闸门（未确认即拒，绕不过去）",
        r.get("ok") is False and r.get("needs_confirmation") is True, r.get("error"))
    r = json.loads(text_of(await call("zx_profile",
                                      {"subject": "数学", "user_confirmed": True})))
    log("zx_profile 也要求试卷范围（两道闸门一致，不能挑软的绕）",
        r.get("ok") is False and r.get("needs_scope") is True, r.get("error"))

    # ---- 7. check_practice ----
    good = json.dumps({"gen_id": "p_001", "qtype": "解答题",
                       "knowledge_points": ["数学/一元二次方程/公式法与判别式"],
                       "difficulty": 0.6, "steps": 3}, ensure_ascii=False)
    r = json.loads(text_of(await call("check_practice",
                                      {"fingerprint": fp, "candidate": good})))
    log("check_practice 正例通过", r.get("ok") is True,
        f"Jaccard={[i['value'] for i in r['checks'] if i['name']=='知识点 Jaccard']}")
    bad = json.dumps({"gen_id": "p_002", "qtype": "填空题",
                      "knowledge_points": ["数学/二次函数/最值问题"],
                      "difficulty": 0.9}, ensure_ascii=False)
    r = json.loads(text_of(await call("check_practice",
                                      {"fingerprint": fp, "candidate": bad})))
    log("check_practice 负例被拒（题型/知识点/超纲）", r.get("ok") is False,
        f"{len(r.get('errors', []))} 条错误")

    # ---- 8. submit_solution ----
    r = json.loads(text_of(await call("submit_solution", {
        "fingerprint": fp, "submitted_answer": "m < 9/4",
        "standard_answer": "m < 9/4", "gen_id": "p_001", "record": True})))
    log("submit_solution 比对一致并记录练习历史",
        r.get("comparison", {}).get("verdict") == "match"
        and r.get("history_recorded") == "correct",
        f"verdict={r.get('comparison', {}).get('verdict')}")

    # ---- 9. zx_export_paper（包六：答案层验证门禁） ------------------------
    # 先做答案层验证拿 strength，再出卷 —— weak 不许冒充 strong。
    r = json.loads(text_of(await call("zx_practice_verify", {
        "generated_answer": "k < 25/4", "standard_answer": "k < 25/4"})))
    log("zx_practice_verify 逐字一致 → exact（强验证）",
        r.get("strength") == "exact" and r.get("ok") is True, r.get("detail"))

    r = json.loads(text_of(await call("zx_practice_verify", {
        "generated_answer": "4 - 10 + 6", "self_check": "2^2 - 5*2 + 6 = 0"})))
    log("回代等式成立 → numeric（强验证）",
        r.get("strength") == "numeric" and r.get("verdict") == "match",
        r.get("detail"))

    r = json.loads(text_of(await call("zx_practice_verify", {
        "generated_answer": "x = 2", "self_check": "2^2 - 5*2 + 7 = 0"})))
    log("回代不成立 → mismatch（答案大概率错了）",
        r.get("verdict") == "mismatch" and r.get("ok") is False
        and r.get("error_code") == "practice_gate", r.get("detail"))

    r = json.loads(text_of(await call("zx_practice_verify", {
        "generated_answer": "见解析过程", "standard_answer": "同上，化简即可"})))
    log("成段文字 → undecidable（不猜，如实记 weak）",
        r.get("strength") in ("weak", "undecidable") and r.get("ok") is True,
        r.get("detail"))

    # 没做过答案层验证就声称 verified=True → 整卷拒绝
    unverified_items = json.dumps([{
        "gen_id": "p_bad", "subject": "数学", "qtype": "解答题",
        "knowledge_points": ["数学/一元二次方程/公式法与判别式"],
        "kp": ["数学/一元二次方程/公式法与判别式"], "difficulty": 0.6,
        "stem_html": "<p>未验证的题</p>", "answer": "k < 25/4",
        "verified": True, "attempts": 1,
    }], ensure_ascii=False)
    r = json.loads(text_of(await call("zx_export_paper", {
        "items": unverified_items, "title": "不应生成的卷子"})))
    log("zx_export_paper 诚实门禁：没强验证却称 verified → 整卷拒绝",
        r.get("ok") is False and r.get("error_code") == "practice_gate"
        and any("p_bad" in e for e in r.get("errors", [])),
        str(r.get("errors"))[:100])

    items = json.dumps([{
        "gen_id": "p_001", "subject": "数学", "qtype": "解答题",
        "knowledge_points": ["数学/一元二次方程/公式法与判别式"],
        "kp": ["数学/一元二次方程/公式法与判别式"],
        "difficulty": 0.6,
        "stem_html": "<p>已知方程 x^2 - 5x + k = 0 有两个不相等的实数根，求 k 的取值范围。</p>",
        "answer": "k < 25/4", "analysis": "由 Δ = 25 - 4k > 0 得 k < 25/4。",
        "verified": True, "attempts": 1, "source_topic": fp[:12],
        "strength": "exact",
        "verification": [{"name": "题型一致", "kind": "hard", "passed": True, "value": "解答题"},
                         {"name": "知识点 Jaccard", "kind": "hard", "passed": True, "value": 1.0}],
    }], ensure_ascii=False)
    r = json.loads(text_of(await call("zx_export_paper", {
        "items": items, "title": "MCP 演示练习卷",
        "out_path": str(TMP / "paper.html")})))
    log("zx_export_paper 生成练习卷", r.get("ok") and Path(r["html"]).exists(),
        r.get("html"))

    # ---- 10. review_queue / sync_log ----
    r = json.loads(text_of(await call("zx_review_queue", {})))
    log("zx_review_queue 可调用", "items" in r, f"{r.get('count')} 条待复核")
    r = json.loads(text_of(await call("zx_sync_log", {})))
    log("zx_sync_log 可调用", "logs" in r, f"{r.get('count')} 条日志")

    # ---- 10b. 两段式知识点路径（文档歧义处：示例用两段，规范说三段） ----
    r = json.loads(text_of(await call("submit_analysis", {
        "fingerprint": fp,
        "error_type": "概念不清",
        "knowledge_points": "一元二次方程/公式法与判别式",   # 故意只写两段
        "evidence": "「m <= 9/4」——判别式大于零写成大于等于零",
        "confidence": 0.8,
        "analyzed_by": "host:mcp-e2e",
        "prompt_version": "analyze-v3"})))
    kps = r.get("stored", {}).get("knowledge_points", [])
    log("两段式知识点路径被解析并归一化为三段",
        r.get("ok") and kps == ["数学/一元二次方程/公式法与判别式"],
        f"存入={kps}")

    # ---- 10c. 导出错题本（md / json 两条分支都没测过） ----
    for fmt in ("md", "json"):
        out_file = str(TMP / f"wrongbook.{fmt}")
        r = json.loads(text_of(await call("zx_export_wrongbook",
                                          {"fmt": fmt, "out_path": out_file})))
        ok = r.get("ok") and Path(r["path"]).exists() and r.get("count", 0) > 0
        log(f"zx_export_wrongbook(fmt={fmt}) 导出成功", ok,
            f"{r.get('path')}（{r.get('count')} 题）")
    r = json.loads(text_of(await call("zx_export_wrongbook", {"fmt": "csv"})))
    log("不支持的 fmt 给出可选值提示", r.get("ok") is False
        and "md / xlsx / json" in r.get("error", ""), r.get("error"))

    # ---- 10d. 会话清除（必须在隔离的凭据命名空间里跑） ----
    # 回归背景（2026-09-24）：这里原来直接调 zx_session_clear，而它删的是
    # **全局**凭据 —— 把用户真实保存的 zx_cookie 删掉了。现在先确认命名空间
    # 已经被隔离，再放一条假 Cookie 进去，让这个断言真的有意义。
    from adapters import session as _sess
    isolated = (_sess.SERVICE_NAME != "zhixue-wrongbook"
                and _sess.KEY_NAME != "zx_cookie")
    log("凭据命名空间已隔离（不会碰到真实 zx_cookie）", isolated,
        f"service={_sess.SERVICE_NAME} key={_sess.KEY_NAME} "
        f"file={_sess.FALLBACK_PATH.name}")

    _sess.set_cookie("token=e2e-fake; loginUserName=e2e; userName=e2e")
    seeded = bool(_sess.get_cookie())
    log("先塞一条假 Cookie 进临时命名空间（让下面的断言不空转）", seeded, "")

    r = json.loads(text_of(await call("zx_session_clear", {})))
    log("zx_session_clear 可调用且幂等", r.get("ok") is True, str(r.get("removed")))
    log("清除后临时命名空间里确实读不到 Cookie了",
        _sess.get_cookie() is None, "")

    r2 = json.loads(text_of(await call("zx_session_clear", {})))
    log("重复清除不报错（幂等）", r2.get("ok") is True, str(r2.get("removed")))

    # ---- 10e. 工具清单不变量（包五，2026-09-26，移植自 qwen 分支） ----
    # 背景：README 与验收报告曾写「20 个工具」，实际 server.py 已有 22 个
    # @mcp.tool —— 文档漂移发生过不止一次。qwen 分支的解法是把「工具清单」
    # 本身做成机制不变量：新加工具不更新这张表，测试直接红。
    EXPECTED_TOOLS = sorted([
        "zx_session_set", "zx_session_status", "zx_session_clear",
        "zx_account_set", "zx_account_clear",
        "zx_list_exams", "zx_sync", "zx_import_export_file",
        "zx_browser_start", "zx_browser_stop", "zx_sync_browser",
        "get_questions", "zx_knowledge_points",
        "submit_analysis", "submit_solution", "check_practice",
        "zx_practice_verify",
        "zx_subjects", "zx_profile", "zx_diagnosis", "zx_diagnosis_log",
        "zx_review_queue", "zx_export_paper", "zx_export_wrongbook",
        "zx_purge", "zx_sync_log",
    ])
    extra = sorted(set(names) - set(EXPECTED_TOOLS))
    missing = sorted(set(EXPECTED_TOOLS) - set(names))
    log("工具清单不变量：tools/list 与登记表逐项相等",
        names == EXPECTED_TOOLS,
        ("多出 %r —— 请同步更新 mcp_e2e.EXPECTED_TOOLS / README / 验收报告"
         % extra) if extra else
        ("缺失 %r" % missing) if missing else
        f"{len(names)} 个工具，与登记表一致")

    # ---- 10f. 出口 PII 扫描（包五）：不该带个人信息的出口绝不能带 ----
    # 与 qwen 分支「全工具禁 PII」不同：本架构里 get_questions 把题面交给
    # 宿主模型是**设计内**的（分析必须读题），所以扫描范围限定在
    # **元数据/聚合类出口**——它们的职责里根本没有出现学生原文的理由。
    # 先造一道含 PII 的题（第二场考试），证明扫描不是空转：
    pii_file = TMP / "export_pii.txt"
    pii_file.write_text(
        "错题回卷 数学\n\n"
        "1. 计算 (3x-2)(3x+2) 的结果。（学生：张小明，阳光中学，家长电话"
        "13812345678，邮箱 zhangxm@example.com）\n"
        "答案：9x^2 - 4\n"
        "学生答案：9x^2 + 4\n"
        "得分：0/4\n",
        encoding="utf-8")
    r = json.loads(text_of(await call("zx_import_export_file", {
        "path": str(pii_file), "subject": "数学",
        "exam_name": "错题回卷", "exam_date": "2026-09-20"})))
    log("含 PII 的题已入库（扫描前提）",
        r.get("ok") and r["imported"]["added"] == 1,
        f"added={r.get('imported', {}).get('added')}")
    CANARIES = ["13812345678", "张小明", "阳光中学", "zhangxm@example.com"]
    r = json.loads(text_of(await call("get_questions", {"subject": "数学"})))
    seed_ok = all(c in json.dumps(r, ensure_ascii=False) for c in CANARIES)
    log("扫描不空转：get_questions（设计内的题面出口）确实含 PII 原文",
        seed_ok, "题面按设计原样出境，由宿主在对话层负责不外传")

    # 元数据 / 聚合类出口逐个扫：
    SCAN_TARGETS = ["zx_sync_log", "zx_diagnosis_log", "zx_session_status",
                    "zx_subjects", "zx_knowledge_points", "zx_review_queue"]
    for t in SCAN_TARGETS:
        payload = await call(t, {})
        blob = text_of(payload)
        leak = [c for c in CANARIES if c in blob]
        log(f"出口 PII 扫描：{t}", not leak,
            f"泄漏：{leak}" if leak else "未发现 PII 原文")

    # ---- 11. 确认 MCP 内零模型调用 ----
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    banned = ["openai", "anthropic", "claude", "gpt", "dashscope", "zhipu",
              "ollama", "litellm", "chat.completions", "messages.create"]
    hit = [b for b in banned if b in src.lower()]
    log("MCP 数据面零模型调用（静态检查 server.py）", not hit,
        f"命中禁用词：{hit}" if hit else "未出现任何模型 SDK / 端点")

    # ---- 12. 清理 ----
    r = json.loads(text_of(await call("zx_purge", {"confirm": True})))
    log("zx_purge 真删临时库", r.get("ok") is True, str(r.get("removed")))
    shutil.rmtree(TMP, ignore_errors=True)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 68)
    print(f"汇总：{passed}/{len(RESULTS)} 通过")
    for n, ok, d in RESULTS:
        if not ok:
            print(f"  FAIL {n} — {d}")
    print("=" * 68)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
