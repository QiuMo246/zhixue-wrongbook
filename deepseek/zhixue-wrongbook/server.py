"""MCP Server 入口 —— 数据面。

能力边界（架构文档第 1 节）：
  本文件里的任何代码**都不调用模型**。它只做四件事：
    1. 本地 HTTP 请求（智学网，仅 zx_* 系列）
    2. SQLite 读写
    3. 确定性计算（校验、统计、导出）
    4. 把结果交给宿主模型 / 接收宿主模型的结果

  「这道题在考什么」「学生为什么错了」——这些需要理解的事，全部是宿主的任务，
  通过 get_questions 拿数据、通过 submit_analysis 提交结论。
  这样推理才可审计：MCP 会拒绝不合法的结论（枚举外、词表外、证据定位不到）。

启动方式（stdio）：
    .venv/Scripts/python server.py
"""

from __future__ import annotations

import functools
import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- MCP SDK 兼容层 ---------------------------------------------------------
# mcp 2.x 把 FastMCP 改名为 MCPServer（mcp/server/mcpserver.py）；
# 1.x 是 mcp.server.fastmcp.FastMCP。两边都兼容，免得锁死版本。
try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # pragma: no cover - mcp < 2
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore

from adapters import auto_login
from adapters import session as session_store
from adapters import zhixue_web
from adapters import zhixuewang as zxw
from adapters.parsers import zhixue_export
from core.config import get_config
from core.constants import TIME_SCOPES
from core.errors import ZxError, error_payload as _error_payload
from core.export import (SOURCE_LABEL, try_pdf, write_json_report,
                         write_paper, wrongbook_markdown, wrongbook_xlsx)
from core.models import Analysis, HistoryEntry, PracticeRef
from core.profile import build_profile, review_queue
from core.store import Store
from core.scope import (ask_user_scope_prompt, normalize_paper_types,
                        normalize_time_scope, paper_type_options,
                        resolve_scope, time_scope_options, valid_paper_types)
from core.subjects import ask_user_prompt, normalize_subject, subject_options
from core.taxonomy import load_taxonomy
from core.validate import (compare_solution, validate_analysis,
                           validate_practice)

CONFIG = get_config()

SERVER_INSTRUCTIONS = """\
智学网错题助手（数据面）。给宿主模型用的错题数据接口。

推荐工作流：
  1. zx_session_set  ← 用户先给一次 Cookie（或 zx_session_status 看有没有）
  2. zx_list_exams   → 让用户选要同步哪场考试
  3. zx_sync         → 错题入库
  4. get_questions   → 拿错题原始数据（题干/标准答案/解析/学生作答图片）
  4b.zx_knowledge_points → 查受控词表里有哪些知识点（标知识点前先查，别猜）
  5. submit_analysis → 你分析完错因和知识点后提交，MCP 会校验并落库
  6. zx_subjects     → 列出可诊断科目
  7. zx_diagnosis    → 个性化诊断数据包（必须先向用户确认「科目 + 试卷范围」，
                       见下）
  8. check_practice  → 你出的题先过确定性校验
  9. submit_solution → 你自己解一遍，与标准答案比对
 10. zx_export_paper → 导出练习卷

⚠️ 硬规则：生成个性化诊断之前，必须先问用户**两件事**。

   ① 要诊断哪一科？
   ② 要分析**哪些试卷里的错题**？

   只问科目是不够的：一科的错题可能横跨几个月、几十份卷子
   （周测 / 午练 / 晚练 / 早读）。只说「物理」，「分析哪些卷子」
   仍然是助手替用户定的 —— 范围没被用户确认，等于没确认。

   试卷范围按两个维度选，两者是「且」的关系：
     维度一 · 按试卷类型：周测 / 午练 / 晚练 / 早读 / 其他 / 全部（可多选）
     维度二 · 按时间：本周 / 上周 / 近两周 / 本月 / 近一月 / 全部
             也可用 since / until 给自定义区间（YYYY-MM-DD）

   zx_diagnosis / zx_profile 共七道检查，缺任何一个都一律拒绝，
   并返回一句可直接念给用户的 ask_user 话术：
     缺科目 → needs_subject；科目未确认 → needs_confirmation
     缺范围 → needs_scope；范围取值非法 → invalid_scope
     范围未确认 → needs_scope_confirmation
     该科无数据 → no_data；该范围无数据 → no_data_in_scope

   不要默认「全部科目」或「全部试卷」；不要挑库里题最多的那一科；
   不要凭上一轮上下文猜；范围里没题时**不要自己放宽成「全部」**。
   正确顺序：zx_subjects 拿清单 → 问科目 → 问范围 → 得到明确答复 →
   带 user_confirmed=true + scope_confirmed=true 再调。
   返回的画像**只覆盖用户选定的范围**（真的过滤，不是提示）。
   每次通过的诊断都会写进 diagnosis_log（含范围），
   用 zx_diagnosis_log 可以事后核对这两条规则有没有被绕过。

重要：错题的题干、标准答案、解析、学生作答会被发送到你所使用的 AI 模型
进行处理。如果你不希望这些内容离开本机，请使用本地模型。
"""

mcp = _Server(
    name="zhixue-wrongbook",
    instructions=SERVER_INSTRUCTIONS,
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _store() -> Store:
    return Store(CONFIG.path("db_path"), CONFIG.path("images_dir"))


def _abs_images(paths: list[str]) -> list[str]:
    """把图片相对路径转成绝对路径，宿主读图要用。"""
    out = []
    for p in paths or []:
        if not p:
            continue
        path = Path(p)
        if path.is_absolute() or p.startswith("http"):
            out.append(p)
        else:
            out.append(str(CONFIG.path("images_dir") / p))
    return out


def _question_payload(q) -> dict:
    """给宿主的题目数据。刻意把「给宿主看的」和「给存储的」分开：
    宿主需要绝对图片路径和纯文本，存储不需要。"""
    return {
        "fingerprint": q.fingerprint(),
        "id": q.id,
        "source": q.source,
        "source_label": SOURCE_LABEL.get(q.source, q.source),
        "parse_confidence": q.parse_confidence,
        "subject": q.subject,
        "grade": q.grade,
        "exam": {"name": q.exam.name, "date": q.exam.date},
        "question": {
            "stem_html": q.question.stem_html,
            "stem_text": q.stem_text,
            "images": _abs_images(q.question.images),
            "type": q.question.type,
            "difficulty": q.question.difficulty,
            "difficulty_scale": q.question.difficulty_scale,
            "class_score_rate": q.question.class_score_rate,
        },
        "answer": {
            "student_text": q.answer.student_text,
            "student_text_plain": q.student_text,
            "student_images": _abs_images(q.answer.student_images),
            "standard": q.answer.standard,
            "standard_plain": q.standard_text,
            "analysis_html": q.answer.analysis_html,
        },
        "score": {"got": q.score.got, "full": q.score.full,
                  "rate": q.score.rate},
        "analysis": q.analysis.model_dump() if q.analysis else None,
        "history": [h.model_dump() for h in q.history],
        "has_student_answer": bool(q.answer.student_text or q.answer.student_images),
    }


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _as_list(value, seps: str = "|") -> list[str]:
    """把「列表型参数」的各种写法统一成 list[str]。

    接受：数组 / JSON 数组字符串 / 用 `seps` 分隔的字符串 / 单个值 / None。

    为什么要宽容（2026-09-25 实测的缺陷）
    ------------------------------------
    架构文档第 7 节把 `knowledge_points` / `evidence` 画成**数组**
    （`["一元二次方程/判别式", ...]`），但工具签名原来只写 `str`。
    宿主照文档传数组，会在**调用层**被 pydantic 拒绝 ——
    而且吐的是一屏 `ValidationError` 堆栈，调用方完全看不懂。

    实测（同一个 server 的 4 个工具都中招）：
      submit_analysis.knowledge_points / evidence、zx_sync.subjects、
      zx_export_paper.items、check_practice.candidate
      —— 传 `[]` 全部 ❌ ToolError，传 `"[]"` 才 ✅。

    ⚠️ 关于分隔符：**每个调用点保留自己原来的分隔符**，不统一。
    因为 `evidence` 里可能引用含逗号的原文（「学生把 3,4 看成 3.4」），
    若对它按逗号切分，会把一条证据切成两条 —— 那是新的静默错误。
    所以 `seps` 由调用方显式传：submit_analysis 用 `|`，zx_sync 用 `,`。
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out = []
        for x in value:
            t = str(x).strip()
            if t:
                out.append(t)
        return out
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                parsed = json.loads(s)
            except ValueError:
                parsed = None
            if isinstance(parsed, list):
                out = []
                for x in parsed:
                    t = str(x).strip()
                    if t:
                        out.append(t)
                return out
        for sep in seps:
            if sep in s:
                return [p.strip() for p in s.split(sep) if p.strip()]
        return [s]
    t = str(value).strip()
    return [t] if t else []


def _guard(fn):
    """把工具体内**未预期**的异常收敛成结构化错误，不让它抛穿到 MCP 层。

    为什么需要（2026-09-24 实测暴露）：MCP 客户端会把未捕获异常统一包成
    `UnexpectedToolError: Error executing tool <name>`。工具自己精心写好的
    可读提示会被这层包装碾掉 —— 最典型的是 zx_export_wrongbook(fmt="xlsx")：
    requirements.txt 里明写「没装 openpyxl 也能跑，只是会给出明确提示」，
    core/export.py 也确实抛了「未安装 openpyxl，请执行 pip install openpyxl」，
    但这句话在 MCP 边界被吃掉了，宿主只看到一句没有上下文的 UnexpectedToolError。

    同时修掉接口契约的不一致：修之前 16 个工具里 5 个返回
    {"ok": false, "error": ...}、11 个抛异常，宿主得写两套错误处理。
    加上这层之后，**任何工具失败都返回同一形状的 JSON**。

    只兜 Exception，不兜 BaseException —— KeyboardInterrupt / SystemExit
    属于该往上走的，不能吞。

    包四（2026-09-26，移植自 qwen 分支）：ZxError 会额外带上
    `error_code` / `missing` / `suggested_action` 三个兄弟键，
    宿主照 SKILL.md 的话术表跟用户协商，不用自己从报错字符串里猜。
    普通异常不带这三个键，返回形状与历史版本完全一致。
    """
    tool_name = fn.__name__

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def _awrapped(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except ZxError as exc:
                return _json({"ok": False, "tool": tool_name,
                              "error": exc.message, **_error_payload(exc)})
            except Exception as exc:
                return _json({"ok": False, "tool": tool_name,
                              "error": f"{type(exc).__name__}: {exc}"})
        return _awrapped

    @functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ZxError as exc:
            return _json({"ok": False, "tool": tool_name,
                          "error": exc.message, **_error_payload(exc)})
        except Exception as exc:
            return _json({"ok": False, "tool": tool_name,
                          "error": f"{type(exc).__name__}: {exc}"})
    return _wrapped


# ---------------------------------------------------------------------------
# 诊断闸门：个性化诊断前必须向用户确认「科目」+「试卷范围」
# ---------------------------------------------------------------------------
# 需求（2026-09-24 新增）：在用户让 AI 根据错题生成「个性化诊断」之前，
# 助手必须**强制询问**用户要诊断哪一科，而不是默认全部或替用户挑。
#
# 需求（2026-09-25 扩展）：**只问科目不够。** 一科的错题可能横跨几个月、
# 几十份卷子（周测 / 午练 / 晚练 / 早读），只说「物理」的话，
# 「分析哪些卷子」仍然是模型替用户定的 —— 范围没被用户确认，等于没确认。
# 所以补上第二问，并给两个正交维度：
#     维度一 按试卷类型：周测 / 午练 / 晚练 / 早读（+ 其他 / 全部）
#     维度二 按时间：本周 / 上周 / 近两周 / 本月 / 近一月 / 全部
# 两问都拿到明确答复，才放行。
#
# 这道闸门能做什么、不能做什么（说清楚，不含糊）：
#   ✅ 能：让「不给科目 + 不给范围就拿不到数据」成为确定性事实 —— 宿主绕不过去；
#   ✅ 能：把「该问什么」以 ask_user 话术的形式直接塞给宿主，省得它自己编；
#   ✅ 能：让返回的画像**真的只覆盖用户选的范围**（不是只写一句提示）；
#   ✅ 能：把每次诊断的科目、范围、两处确认声明写进 diagnosis_log，事后可查；
#   ❌ 不能：验证用户**真的**被问过。没有任何代码能验证这件事 ——
#           user_confirmed / scope_confirmed 是宿主的两句声明，本工具只负责
#           让这两句声明留下痕迹，并让「不问就调」在日志里显形。
#           真正让人被问到的，是 Skill 里的硬规则 + 宿主模型老实执行。
# ---------------------------------------------------------------------------
def _diagnosis_gate(store: Store, subject: str, user_confirmed: bool,
                    paper_types=None, time_scope: str = "",
                    scope_confirmed: bool = False,
                    since: str = "", until: str = "",
                    purpose: str = "个性化诊断") -> dict | None:
    """返回 None = 放行；返回 dict = 直接作为工具结果返回（拒绝）。

    检查顺序是有意的，共六道，**先问完再查数据**：
      ① 缺科目 → ② 科目未确认 → ③ 缺范围 → ④ 范围取值非法
      → ⑤ 范围未确认 → ⑥ 该科目无数据 → ⑦ 该范围内无数据

    为什么「数据检查」排在最后：反过来的话，用户会被问一科、
    答完才被告知「这科没数据」，白问一轮。范围同理 ——
    要等两问都答完，才告诉他「你选的这个范围里没题」。
    """
    subject = normalize_subject(subject)
    options = subject_options(store, load_taxonomy())

    # ---- ①② 科目 --------------------------------------------------------
    if not subject:
        return {
            "ok": False,
            "needs_subject": True,
            "error": (f"缺少科目：{purpose}必须先向用户确认科目，"
                      f"不能默认「全部」，也不能替用户挑。"),
            "ask_user": ask_user_prompt(options, purpose),
            "subjects": options["subjects"],
            "with_questions": options["with_questions"],
        }

    if not user_confirmed:
        return {
            "ok": False,
            "needs_confirmation": True,
            "subject": subject,
            "error": (f"科目「{subject}」没有经过用户确认：{purpose}之前必须先问用户，"
                      f"拿到明确答复后带 user_confirmed=true 重试。"),
            "ask_user": (f"请先向用户确认：是否要对「{subject}」做{purpose}？"
                         f"等用户明确回答之后再继续。"),
            "hint": ("user_confirmed=true 的含义是「我已经问过用户，并得到了明确答复」。"
                     "它是一句声明，不是一句许可 —— 没问过就不要传 true。"
                     "每次通过的诊断都会写进 diagnosis_log（zx_diagnosis_log 可查）。"),
            "subjects": options["subjects"],
        }

    # ---- ③④⑤ 试卷范围（两个维度）----------------------------------------
    pts = normalize_paper_types(paper_types)
    scope = normalize_time_scope(time_scope)
    paper_opts = paper_type_options(store, subject)
    time_opts = time_scope_options(store, subject)

    if not pts and not scope:
        return {
            "ok": False,
            "needs_scope": True,
            "subject": subject,
            "error": (f"缺少试卷范围：{purpose}还必须向用户确认**分析哪些试卷里的错题**，"
                      f"不能默认「全部」—— 那是模型替用户定的范围。"),
            "ask_user": ask_user_scope_prompt(subject, paper_opts, time_opts, purpose),
            "paper_types": paper_opts["paper_types"],
            "time_scopes": time_opts["time_scopes"],
            "how_to_call": ("拿到答复后，带 paper_types（如 [\"午练\",\"晚练\"] 或 "
                            "[\"全部\"]）与 time_scope（如 \"本周\"/\"全部\"）"
                            "再调一次，并把 scope_confirmed 置为 true。"),
        }

    bad_types = [t for t in pts if t not in valid_paper_types()]
    if bad_types or (scope and scope not in TIME_SCOPES):
        return {
            "ok": False,
            "invalid_scope": True,
            "subject": subject,
            "error": (f"试卷范围取值不合法："
                      f"{'试卷类型 ' + str(bad_types) + ' ' if bad_types else ''}"
                      f"{'时间 ' + repr(scope) + ' ' if scope and scope not in TIME_SCOPES else ''}"
                      f"不在允许的取值里。"),
            "valid_paper_types": valid_paper_types(),
            "valid_time_scopes": list(TIME_SCOPES),
            "ask_user": ask_user_scope_prompt(subject, paper_opts, time_opts, purpose),
        }

    if not scope_confirmed:
        rng = resolve_scope(pts, scope, since, until)
        return {
            "ok": False,
            "needs_scope_confirmation": True,
            "subject": subject,
            "scope": {"paper_types": pts, "time_scope": scope or "全部",
                      "label": rng["label"]},
            "error": (f"试卷范围没有经过用户确认：{purpose}之前必须先问用户"
                      f"「要分析哪些试卷的错题」，拿到明确答复后带 "
                      f"scope_confirmed=true 重试。"),
            "ask_user": (f"请先向用户确认：这次{purpose}要分析哪些试卷里的错题"
                         f"（按类型：{'/'.join(valid_paper_types())}；"
                         f"按时间：{'/'.join(TIME_SCOPES)}）？"
                         f"等用户明确回答之后再继续。"),
            "hint": ("scope_confirmed=true 的含义是「我已经问过用户试卷范围，"
                     "并得到了明确答复」。和 user_confirmed 一样，它是声明不是许可。"
                     "两者都会写进 diagnosis_log。"),
        }

    # ---- ⑥⑦ 数据检查（最后做，别让用户白答）------------------------------
    if not any(r["subject"] == subject and r["has_questions"]
               for r in options["subjects"]):
        return {
            "ok": False,
            "no_data": True,
            "subject": subject,
            "error": f"本地库里没有「{subject}」的错题，做不了{purpose}。",
            "hint": ("先用 zx_sync(subjects=...) 同步该科目，"
                     "或用 zx_import_export_file 导入官方导出文件。"),
            "with_questions": options["with_questions"],
        }

    rng = resolve_scope(pts, scope, since, until)
    in_scope = store.count_questions(subject=subject,
                                     paper_types=rng["paper_types"],
                                     date_from=rng["since"], date_to=rng["until"])
    if in_scope == 0:
        return {
            "ok": False,
            "no_data_in_scope": True,
            "subject": subject,
            "scope": {"paper_types": rng["paper_types"],
                      "time_scope": rng["time_scope"], "label": rng["label"]},
            "error": (f"「{subject}」在「{rng['label']}」这个范围里没有错题，"
                      f"换一个范围试试。"),
            "ask_user": ask_user_scope_prompt(subject, paper_opts, time_opts, purpose),
            "paper_types": paper_opts["paper_types"],
            "time_scopes": time_opts["time_scopes"],
            "hint": "别直接放宽成「全部」—— 把可选范围给用户，让他重新选。",
        }

    return None


# ===========================================================================
# 会话
# ===========================================================================
@mcp.tool(description="设置/更新智学网 Cookie 会话。Cookie 存系统凭据管理器，不落明文文件。"
                      "会用一次真实请求验证 Cookie 是否有效。")
@_guard
def zx_session_set(cookie: str, verify: bool = True) -> str:
    cookie = (cookie or "").strip()
    try:
        saved = session_store.set_cookie(cookie)
    except Exception as exc:
        return _json({"ok": False, "error": str(exc) if isinstance(exc, ZxError)
                      else f"{type(exc).__name__}: {exc}",
                      **_error_payload(exc)})

    out = {"ok": True, "stored": saved}
    if verify:
        # 先做一次「会话还认吗」的探测，再决定怎么报错。
        # 直接 try: login() 的话，Cookie 失效时会漏出库的
        # `TypeError: 'NoneType' object is not subscriptable` —— 看不懂（2026-09-25 修）。
        probe = zhixue_web.session_check(cookie)
        if probe.get("status") == "expired":
            out["verified"] = False
            out["error"] = (f"Cookie 已保存，但服务端不认："
                            f"errorCode={probe.get('error_code')}"
                            f"（{probe.get('error_info')}）。")
            out["hint"] = ("常见原因：Cookie 复制不完整 / 已过期 / 缺少 loginUserName。"
                           "请在浏览器里重新登录智学网，"
                           "F12 → Console 执行 copy(document.cookie) 后重试。")
            return _json(out)
        if probe.get("status") == "unreachable":
            out["verified"] = None
            out["error"] = "网络不通，没能验证：" + str(probe.get("detail"))
            out["hint"] = "Cookie 已经存下来了。网络恢复后调 zx_session_status 再确认一次。"
            return _json(out)
        try:
            account = zxw.login(cookie)
            student = zxw.to_student(account)
            latest = student.get_latest_exam()
            out["verified"] = True
            out["role"] = probe.get("role")
            out["latest_exam"] = {"id": latest.id, "name": latest.name}
        except Exception as exc:
            out["verified"] = False
            out["verify_error"] = f"{type(exc).__name__}: {exc}"
            out["hint"] = ("服务端认得这个 Cookie，但登录流程出错 —— "
                           "这条更像是缺陷，请把它发出来。")
    return _json(out)


@mcp.tool(description="检查会话状态。只返回首尾几个字符，不会泄露完整 Cookie。"
                      "会区分三种情况：会话有效 / 会话已失效（Cookie 过期，该重新登录）"
                      "/ 网络不通（Cookie 可能还好好的，别急着重新登录）。")
@_guard
def zx_session_status() -> str:
    st = session_store.status()
    if not st.get("has_cookie"):
        return _json(st)

    cookie = session_store.get_cookie()

    # 先用一次只读请求问服务端「这个会话还认吗」。
    #
    # 为什么不直接 try: login()（2026-09-25 修的真实缺陷）：
    # 库在会话失效时抛 `TypeError: 'NoneType' object is not subscriptable`
    # （zhixuewang/account.py:18 —— 服务端返回 result=null，库直接对它取 ["role"]）。
    # 那个报错分不清「Cookie 过期」和「代码坏了」，使用者完全没法处理。
    probe = zhixue_web.session_check(cookie)
    status = probe.get("status")

    if status == "unreachable":
        st["valid"] = None
        st["error"] = "网络不通，无法判断会话是否有效：" + str(probe.get("detail"))
        st["hint"] = ("这不代表 Cookie 失效 —— 请先检查网络/代理再重试，"
                      "不要急着重新登录。")
        return _json(st)

    if status == "expired":
        # 2026-09-25 新增：失效时先尝试用本机存档的账密自动重登
        cred = auto_login.load_credentials()
        if cred:
            try:
                cookie = auto_login.login_with_password(*cred)
                session_store.set_cookie(cookie)
                st["valid"] = True
                st["auto_relogin"] = True
                st["note"] = "Cookie 已失效，已用本机存档的账号密码自动重新登录。"
                return _json(st)
            except Exception as exc:
                st["auto_relogin_error"] = str(exc) if isinstance(exc, ZxError) \
                    else f"{type(exc).__name__}: {exc}"
                st.update(_error_payload(exc))
        st["valid"] = False
        st["error"] = (f"会话已失效：服务端返回 errorCode={probe.get('error_code')}"
                       f"（{probe.get('error_info')}）。")
        st["hint"] = ("存档账密自动重登失败（见 auto_relogin_error，可能密码改了）。"
                      "更新存档：运行 tools/setup_account.py，或在 AI 助手里调 "
                      "zx_account_set。")
        return _json(st)

    if status != "valid":
        st["valid"] = None
        st["error"] = "无法判断会话状态：" + str(probe.get("detail"))
        st["hint"] = "请把这条信息发出来，它可能是一个需要修的缺陷。"
        return _json(st)

    # 会话确实有效，再走完整登录流程拿考试列表
    try:
        account = zxw.login(cookie)
        student = zxw.to_student(account)
        latest = student.get_latest_exam()
        st["valid"] = True
        st["role"] = probe.get("role")
        st["latest_exam"] = {"id": latest.id, "name": latest.name}
    except Exception as exc:
        # 会话探测通过了却登录失败 —— 这才是「可能是代码问题」的情况
        st["valid"] = False
        st["error"] = f"{type(exc).__name__}: {exc}"
        st["hint"] = ("会话本身是有效的（服务端认得这个 Cookie），"
                      "但登录流程出错 —— 这条更像是缺陷，请把它发出来。")
    return _json(st)


@mcp.tool(description="清除已保存的 Cookie（从系统凭据管理器删除）。")
@_guard
def zx_session_clear() -> str:
    return _json(session_store.delete_cookie())


def _ensure_cookie() -> str:
    """返回可用 Cookie；失效且有存档账密时自动重登（2026-09-25 新增）。

    失败时返回 JSON 字符串 —— 调用方用 startswith("{") 判断并原样返回。
    """
    try:
        return auto_login.ensure_session()[0]
    except Exception as exc:
        return _json({
            "ok": False, "error": str(exc) if isinstance(exc, ZxError)
            else f"{type(exc).__name__}: {exc}",
            **_error_payload(exc),
            "hint": "运行 .venv/Scripts/python tools/setup_account.py 录入一次"
                    "账号密码，之后 Cookie 失效会自动重登，全程无需手动登录。",
        })


@mcp.tool(description="录入智学网账号密码（本机加密存储，keyring/DPAPI，不落明文）。"
                      "录入后立即登录一次并保存会话；此后 Cookie 失效会自动重登，"
                      "用户全程只需操作这一次。")
@_guard
def zx_account_set(account: str, password: str) -> str:
    try:
        stored = auto_login.save_credentials(account, password)
        cookie = auto_login.login_with_password(account.strip(), password)
        saved = session_store.set_cookie(cookie)
        return _json({"ok": True, "stored_credentials": stored,
                      "session": saved,
                      "note": "已登录并保存会话；此后失效会自动重登。"})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc) if isinstance(exc, ZxError)
                      else f"{type(exc).__name__}: {exc}",
                      **_error_payload(exc)})


@mcp.tool(description="清除本机存档的账号密码（不影响已保存的 Cookie）。")
@_guard
def zx_account_clear() -> str:
    return _json(auto_login.delete_credentials())


# ===========================================================================
# 取数
# ===========================================================================
@mcp.tool(description="拉取考试列表（需要有效会话）。先调这个让用户选要同步哪场考试。")
@_guard
def zx_list_exams(limit: int = 20) -> str:
    cookie = _ensure_cookie()
    if isinstance(cookie, str) and cookie.startswith("{"):
        return cookie          # _ensure_cookie 返回的是错误 JSON
    try:
        student = zxw.to_student(zxw.login(cookie))
        exams = zxw.list_exams(student, limit=limit)
    except Exception as exc:
        return _json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return _json({
        "ok": True, "count": len(exams), "exams": exams,
        "note": "date 来自接口的 examCreateDateTime（库的 Exam 没有考试日期字段），"
                "date_is_approx=true 表示这是近似值。",
    })


@mcp.tool(description="同步错题入库。这是唯一联网且写库的工具。"
                      "subjects 传学科名列表，留空同步全部。"
                      "三种写法都接受：数组 [\"数学\"]、JSON 数组字符串 '[\"数学\"]'、"
                      "逗号分隔 \"数学,物理\"。exam_ids 同理。"
                      "**不会清空已有的分析结果**（重新同步只刷新题目内容）。")
@_guard
def zx_sync(subjects: str | list[str] = "", max_exams: int = 5,
            exam_ids: str | list[str] = "", download_images: bool = True) -> str:
    cookie = _ensure_cookie()
    if isinstance(cookie, str) and cookie.startswith("{"):
        return cookie          # _ensure_cookie 返回的是错误 JSON
    subj_list = _as_list(subjects, ",") or None
    exam_list = _as_list(exam_ids, ",") or None
    store = _store()
    try:
        report = zxw.sync(store, cookie, subjects=subj_list,
                          max_exams=max_exams, exam_ids=exam_list,
                          download=download_images)
    except Exception as exc:
        return _json({"ok": False, "error": str(exc) if isinstance(exc, ZxError)
                      else f"{type(exc).__name__}: {exc}",
                      **_error_payload(exc),
                      "hint": "先跑 zx_session_status 确认 Cookie 是否有效。"})
    finally:
        report_counts = store.counts()
        store.close()
    return _json({"ok": True, "report": report, "library": report_counts})


@mcp.tool(description="导入官方导出的错题文件（通道 A，完全合规，不碰账号）。"
                      "支持 pdf / docx / txt / md。")
@_guard
def zx_import_export_file(path: str, subject: str, exam_name: str,
                          exam_date: str = "", grade: str = "") -> str:
    p = Path(path)
    if not p.exists():
        return _json({"ok": False, "error": f"文件不存在：{path}"})
    try:
        questions, stats = zhixue_export.parse_file(
            p, subject=subject, exam_name=exam_name,
            exam_date=exam_date or None, grade=grade or None)
    except Exception as exc:
        return _json({"ok": False, "error": str(exc) if isinstance(exc, ZxError)
                      else f"{type(exc).__name__}: {exc}",
                      **_error_payload(exc)})
    store = _store()
    added = updated = failed = 0
    for q in questions:
        try:
            if store.upsert(q) == "added":
                added += 1
            else:
                updated += 1
        except Exception:
            failed += 1
    counts = store.counts()
    store.close()
    return _json({"ok": True, "parse": stats,
                  "imported": {"added": added, "updated": updated, "failed": failed},
                  "library": counts,
                  "note": "低解析置信度（<0.5）的题会被统计自动排除，"
                          "并出现在 zx_review_queue 里。"})


# ===========================================================================
# 给宿主数据 / 收宿主结论
# ===========================================================================
@mcp.tool(description="返回错题原始数据给宿主模型（题干、标准答案、解析、学生作答图片路径）。"
                      "这是宿主的输入，不是结论。")
@_guard
def get_questions(subject: str = "", exam: str = "", kp: str = "",
                  only_unanalyzed: bool = False, needs_review: bool = False,
                  limit: int = 20, include_low_confidence: bool = False) -> str:
    store = _store()
    try:
        items = store.query(subject=subject or None, exam=exam or None,
                            kp=kp or None, only_unanalyzed=only_unanalyzed,
                            needs_review=True if needs_review else None,
                            exclude_low_confidence=not include_low_confidence,
                            limit=limit)
        payload = [_question_payload(q) for q in items]
        counts = store.counts()
    finally:
        store.close()
    return _json({
        "count": len(payload), "questions": payload, "library": counts,
        "note": "图片路径是本地绝对路径，可直接读图。"
                "题干/答案/作答会进入模型上下文——这是设计上的显式声明，不是意外。",
    })


@mcp.tool(description="查询知识点受控词表（只读，零模型调用）。三种用法："
                      "① 不传参数 → 各学科章节数/知识点数总览；"
                      "② 传 subject（可再传 chapter）→ 该学科或该章节的全部知识点路径；"
                      "③ 传 query → 按关键词找路径（子串优先，模糊兜底）。"
                      "**被 submit_analysis 以「不在受控词表内」拒绝时，"
                      "用这个工具查正确写法，不要靠猜。** 词表只能选、不能造。")
@_guard
def zx_knowledge_points(subject: str = "", chapter: str = "",
                        query: str = "", limit: int = 400) -> str:
    tax = load_taxonomy()
    subject = normalize_subject(subject)
    n = max(1, min(int(limit), 1000))

    if (query or "").strip():
        hits = tax.search(query, subject or None, n=n)
        return _json({
            "ok": True, "query": query, "subject": subject or None,
            "count": len(hits), "matches": hits,
            "note": ("子串命中优先、模糊兜底。如果一条都没有，说明词表里确实没有 —— "
                     "那就如实标 needs_review，或者先在 data/taxonomy.yaml 里补一行，"
                     "**不要编一个看起来像的名字**。"),
        })

    if subject:
        ch_paths = tax.chapters(subject)
        if not ch_paths:
            return _json({"ok": False,
                          "error": f"受控词表里没有学科「{subject}」。",
                          "subjects": tax.subjects(),
                          "hint": "先调 zx_knowledge_points()（不传参数）看有哪些学科。"})
        if chapter:
            want = (chapter if chapter.startswith(subject + "/")
                    else f"{subject}/{chapter}")
            paths = tax.points_in_chapter(want)
            if not paths:
                return _json({"ok": False,
                              "error": f"「{subject}」下没有章节「{chapter}」。",
                              "chapters": [c.split("/", 1)[1] for c in ch_paths]})
            return _json({"ok": True, "subject": subject, "chapter": want,
                          "count": len(paths), "points": paths})
        rows = [{"chapter": c.split("/", 1)[1], "chapter_path": c,
                 "points": tax.points_in_chapter(c)} for c in ch_paths]
        return _json({
            "ok": True, "subject": subject, "chapter_count": len(rows),
            "point_count": sum(len(r["points"]) for r in rows), "chapters": rows,
            "note": ("提交时用完整路径「学科/章节/知识点」；"
                     "两段式「章节/知识点」也接受，但要求在该学科内唯一命中。"),
        })

    rows = [{"subject": s, "chapters": len(tax.chapters(s)),
             "points": sum(1 for p in tax.all_paths if p.startswith(s + "/"))}
            for s in tax.subjects()]
    return _json({
        "ok": True, "version": tax.version, "updated_at": tax.updated_at,
        "subject_count": len(rows), "point_count": len(tax.all_paths),
        "subjects": rows,
        "note": "传 subject 看某学科全部知识点；传 query 按关键词找路径。",
    })


@mcp.tool(description="提交错因分析结果。MCP 会做三道确定性校验："
                      "错因在 8 类枚举内、知识点在 taxonomy.yaml 内、证据能在题干/作答中定位。"
                      "校验不通过会拒绝并说明原因。"
                      "knowledge_points / evidence 三种写法都接受："
                      '数组 ["a","b"]、JSON 数组字符串 \'["a","b"]\'、竖线分隔 "a|b"。')
@_guard
def submit_analysis(fingerprint: str, error_type: str,
                    knowledge_points: str | list[str],
                    evidence: str | list[str], confidence: float,
                    analyzed_by: str = "", prompt_version: str = "",
                    needs_review: bool = False) -> str:
    store = _store()
    try:
        q = store.get(fingerprint)
        if q is None:
            return _json({"ok": False, "error": f"库里没有指纹为 {fingerprint} 的题。"
                                                f"先用 get_questions 取题。"})
        payload = {
            "error_type": error_type,
            "knowledge_points": _as_list(knowledge_points, "|"),
            "evidence": _as_list(evidence, "|"),
            "confidence": confidence,
            "needs_review": needs_review,
            "analyzed_by": analyzed_by or CONFIG["host"]["model_id"],
            "prompt_version": prompt_version or CONFIG["host"]["prompt_version"],
        }
        res = validate_analysis(q, payload, load_taxonomy())
        if not res.ok:
            return _json({"ok": False, "rejected": True, "errors": res.errors,
                          "warnings": res.warnings,
                          "checks": [i.to_dict() for i in res.items]})
        n = res.normalized
        analysis = Analysis(
            error_type=n["error_type"],
            knowledge_points=n.get("knowledge_points", []),
            evidence=n.get("evidence", payload["evidence"]),
            confidence=n["confidence"],
            needs_review=n["needs_review"],
            analyzed_by=n["analyzed_by"],
            prompt_version=n["prompt_version"],
        )
        ok = store.set_analysis(fingerprint, analysis)
        return _json({"ok": ok, "stored": analysis.model_dump(),
                      "warnings": res.warnings,
                      "checks": [i.to_dict() for i in res.items]})
    finally:
        store.close()


@mcp.tool(description="提交你对生成题的独立解答，与标准答案做确定性比对（字符串/数值）。"
                      "可比对不了会返回 undecidable，不硬判对错。"
                      "**注意比对基准**：不传 standard_answer 时，基准是"
                      "「该指纹对应错题」的标准答案；要校验生成题，"
                      "必须把生成题自己声称的答案传进 standard_answer。"
                      "record=true 时同时写入练习历史。")
@_guard
def submit_solution(fingerprint: str, submitted_answer: str,
                    gen_id: str = "", standard_answer: str = "",
                    record: bool = False, result_override: str = "") -> str:
    store = _store()
    try:
        q = store.get(fingerprint)
        if q is None:
            return _json({"ok": False, "error": f"库里没有指纹为 {fingerprint} 的题。"})
        standard = standard_answer or q.answer.standard or ""
        cmp_res = compare_solution(submitted_answer, standard)
        out = {"ok": True, "comparison": cmp_res,
               "baseline": {
                   "source": ("standard_answer（调用方显式传入）" if standard_answer
                              else f"指纹对应错题 {q.id} 的标准答案（默认）"),
                   "value": (standard or "")[:120],
               },
               "target": {"id": q.id, "subject": q.subject}}
        # 2026-09-24 实测踩到的坑：想校验「生成题」却忘了传 standard_answer，
        # 于是拿生成题的答案去和**另一道题**（目标错题）的标准答案比，
        # 稳稳得到 mismatch —— 但这个 mismatch 只说明「两题答案不同」，
        # 毫无校验意义。更糟的是 record=True 会把这个假结论写进练习历史。
        # 所以这里显式告警，而不是让它安静地错下去。
        if gen_id and not standard_answer:
            out["warning"] = (
                f"带了 gen_id={gen_id} 但没传 standard_answer，"
                f"比对基准是目标错题 {q.id} 的标准答案，不是生成题 {gen_id} 的答案。"
                f"本次的 mismatch 只说明两道题答案不同，没有校验意义。"
                f"要校验生成题，请把生成题自己声称的答案传进 standard_answer。")
            out["baseline"]["suspect"] = True
        if gen_id:
            store.add_practice(fingerprint, PracticeRef(
                gen_id=gen_id, verified=cmp_res["verdict"] in ("match", "numeric_match")))
            out["practice_recorded"] = gen_id
        if record:
            result = result_override or {
                "match": "correct", "numeric_match": "correct",
                "mismatch": "wrong", "undecidable": "partial",
            }.get(cmp_res["verdict"], "partial")
            store.add_history(fingerprint, HistoryEntry(
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                result=result))
            out["history_recorded"] = result
        return _json(out)
    finally:
        store.close()


@mcp.tool(description="校验一道生成题是否与目标错题同知识点同难度。"
                      "硬约束：题型一致、知识点 Jaccard>=0.6、不超纲、难度在区间内。"
                      "难度刻度未核实时该项自动降级为软参考并说明。")
@_guard
def check_practice(fingerprint: str, candidate: str | dict) -> str:
    """candidate 是 JSON 字符串，也可以直接传对象：
    {"gen_id":"p_001","qtype":"解答题","knowledge_points":["数学/一元二次方程/公式法与判别式"],
     "difficulty":0.6,"steps":3,"stem_text":"...","target_steps":3}
    """
    store = _store()
    try:
        q = store.get(fingerprint)
        if q is None:
            return _json({"ok": False, "error": f"库里没有指纹为 {fingerprint} 的题。"})
        try:
            cand = json.loads(candidate) if isinstance(candidate, str) else candidate
        except ValueError as exc:
            return _json({"ok": False, "error": f"candidate 不是合法 JSON：{exc}"})
        res = validate_practice(cand, q, load_taxonomy())
        return _json({"ok": res.ok, "gen_id": cand.get("gen_id", ""),
                      "target": {"id": q.id, "subject": q.subject,
                                 "difficulty": q.question.difficulty,
                                 "difficulty_scale": q.question.difficulty_scale},
                      "errors": res.errors, "warnings": res.warnings,
                      "checks": [i.to_dict() for i in res.items]})
    finally:
        store.close()


# ===========================================================================
# 科目 / 个性化诊断（强制确认科目）
# ===========================================================================
@mcp.tool(description="列出可用于个性化诊断的科目（受控词表 ∪ 本地库），"
                      "含每科题数、已分析数、是否可诊断。"
                      "**生成个性化诊断之前必须先调它，把结果交给用户选，"
                      "不要自己替用户挑科目，也不要按题数多少排序暗示。**")
@_guard
def zx_subjects() -> str:
    store = _store()
    try:
        options = subject_options(store, load_taxonomy())
    finally:
        store.close()
    out = dict(options)
    out["ok"] = True
    out["ask_user"] = ask_user_prompt(options)
    out["note"] = ("diagnosable=true 的科目才有「已分析」的题，才算得出知识点掌握度；"
                   "has_questions=true 但 diagnosable=false 的科目要先分析"
                   "（get_questions → submit_analysis）。"
                   "in_taxonomy=false 表示受控词表里还没有该学科的知识点，"
                   "能选中但暂时做不了知识点级分析 —— 如实告诉用户，不要假装可以。")
    return _json(out)


@mcp.tool(description="学情统计（纯计数与加权平均，零模型调用）。"
                      "**这是硬闸门工具：调用前必须先问用户两件事 —— "
                      "① 科目（subject + user_confirmed=true）；"
                      "② 要分析哪些试卷的错题（paper_types + time_scope + "
                      "scope_confirmed=true）。** "
                      "paper_types 取 周测/午练/晚练/早读/其他/全部（可多选）；"
                      "time_scope 取 本周/上周/近两周/本月/近一月/全部。"
                      "两问缺任何一个都会被拒绝，并返回 ask_user 话术。"
                      "返回的画像**只覆盖用户选定的范围**。"
                      "掌握度公式与时间衰减权重见 core/profile.py；"
                      "样本量不足 3 的知识点只报「样本不足」，不给数值。")
@_guard
def zx_profile(subject: str = "", user_confirmed: bool = False,
               paper_types: str | list[str] = "",
               time_scope: str = "", scope_confirmed: bool = False,
               since: str = "", until: str = "",
               weak_top: int = 10) -> str:
    store = _store()
    try:
        rejected = _diagnosis_gate(store, subject, user_confirmed,
                                   paper_types=paper_types, time_scope=time_scope,
                                   scope_confirmed=scope_confirmed,
                                   since=since, until=until)
        if rejected:
            return _json(rejected)
        subject = normalize_subject(subject)
        rng = resolve_scope(normalize_paper_types(paper_types),
                            normalize_time_scope(time_scope), since, until)
        prof = build_profile(store, subject=subject, weak_top=weak_top,
                             paper_types=rng["paper_types"],
                             date_from=rng["since"], date_to=rng["until"],
                             scope_label=rng["label"])
        prof["review_queue"] = [r for r in review_queue(store)
                                if r["subject"] == subject]
        prof["library"] = store.counts()
        prof["ok"] = True
        prof["subject"] = subject
        return _json(prof)
    finally:
        store.close()


@mcp.tool(description="个性化诊断数据包：掌握度 + 薄弱项 + 错因分布 + 样本错题 + 待复核。"
                      "**这是「生成个性化诊断」的唯一入口，也是硬闸门。**"
                      "必须先问用户两件事，都拿到明确答复才能调："
                      "① 科目 —— subject + user_confirmed=true；"
                      "② **要分析哪些试卷的错题** —— paper_types + time_scope + "
                      "scope_confirmed=true。"
                      "paper_types 取 周测/午练/晚练/早读/其他/全部（可多选）；"
                      "time_scope 取 本周/上周/近两周/本月/近一月/全部；"
                      "也可用 since/until（YYYY-MM-DD）给自定义区间。"
                      "两个维度是「且」：paper_types=[\"午练\"] + time_scope=\"本周\" "
                      "= 只看本周的午练。"
                      "缺任何一问都会被拒绝并返回 ask_user 话术（含可选范围与题数）—— "
                      "请把那段话问给用户，拿到答复后再重试。"
                      "返回的数据**只覆盖用户选定的范围**，不会偷偷用全量。"
                      "通过时会写入 diagnosis_log，返回 audit_id 可事后核对。")
@_guard
def zx_diagnosis(subject: str = "", user_confirmed: bool = False,
                 paper_types: str | list[str] = "",
                 time_scope: str = "", scope_confirmed: bool = False,
                 since: str = "", until: str = "",
                 weak_top: int = 10, sample_limit: int = 3) -> str:
    store = _store()
    try:
        rejected = _diagnosis_gate(store, subject, user_confirmed,
                                   paper_types=paper_types, time_scope=time_scope,
                                   scope_confirmed=scope_confirmed,
                                   since=since, until=until)
        if rejected:
            return _json(rejected)
        subject = normalize_subject(subject)
        rng = resolve_scope(normalize_paper_types(paper_types),
                            normalize_time_scope(time_scope), since, until)
        prof = build_profile(store, subject=subject, weak_top=weak_top,
                             paper_types=rng["paper_types"],
                             date_from=rng["since"], date_to=rng["until"],
                             scope_label=rng["label"])
        samples = [_question_payload(q) for q in store.query(
            subject=subject, only_analyzed=True,
            paper_types=rng["paper_types"],
            date_from=rng["since"], date_to=rng["until"],
            limit=max(1, int(sample_limit)))]
        audit_id = store.log_diagnosis(
            subject=subject, user_confirmed=True,
            question_count=prof["question_count"],
            analyzed_count=prof["analyzed_count"],
            weak_top=[r["kp"] for r in prof["weak_top"]],
            host=CONFIG["host"]["model_id"],
            paper_types=rng["paper_types"], time_scope=rng["time_scope"],
            scope_confirmed=True)
        return _json({
            "ok": True,
            "audit_id": audit_id,
            "subject": subject,
            "scope": prof["scope"],
            "profile": prof,
            "sample_questions": samples,
            "review_queue": [r for r in review_queue(store)
                             if r["subject"] == subject],
            "how_to_write": (
                "把这些数据写成给初中生看的诊断报告："
                "① 先给结论（哪几个知识点最弱，按掌握度升序）；"
                "② 每个薄弱点讲清「你当时可能怎么想 → 卡在哪 → 正确思路」；"
                "③ insufficient=true 的知识点只能写「样本不足」，"
                "**绝对不许编一个掌握度数值**；"
                "④ 最后给下一步练什么（1~3 个知识点就够）。"
                "不要用「粗心」当结论，要落到具体错因。"
                "**开头要写明本次覆盖范围**（scope.label）—— "
                "用户选了范围，报告里就得让他看见这个范围。"
            ),
            "disclaimer": ("错题的题干、标准答案、解析、学生作答会进入"
                           "你所使用的 AI 模型上下文。不想外传请改用本地模型。"),
        })
    finally:
        store.close()


@mcp.tool(description="查看个性化诊断审计日志：每次诊断用了哪一科、"
                      "有没有声明「已与用户确认」、基于多少道题、薄弱项是什么。"
                      "用途是核对「诊断前先问用户科目」这条规则有没有被绕过。")
@_guard
def zx_diagnosis_log(limit: int = 20) -> str:
    store = _store()
    try:
        logs = store.diagnosis_logs(limit=limit)
    finally:
        store.close()
    return _json({
        "count": len(logs), "logs": logs,
        "note": ("user_confirmed / scope_confirmed 是宿主的两句声明，"
                 "不是系统验证过的结论 —— 没有任何代码能验证用户真的被问过。"
                 "本日志的作用是让这两句声明留下痕迹，让「不问就调」"
                 "在事后看得见。"
                 "paper_types / time_scope 记的是**这次诊断实际覆盖的范围**，"
                 "事后核对时它比用户原话更有用 —— "
                 "同一科选「本周午练」和选「全部」，结论可以完全不同。"),
    })


# ===========================================================================
# 统计与导出
# ===========================================================================
@mcp.tool(description="列出需要人工复核的题：分析标记 needs_review，或解析/分析置信度偏低。")
@_guard
def zx_review_queue() -> str:
    store = _store()
    try:
        items = review_queue(store)
    finally:
        store.close()
    return _json({"count": len(items), "items": items})


@mcp.tool(description="导出练习卷（HTML，可选 PDF）。items 是 JSON 数组，"
                      "每项含 gen_id/qtype/knowledge_points/difficulty/stem_html/"
                      "answer/analysis/verified/verification/source_topic。"
                      "items 可传数组或 JSON 字符串。"
                      "要 PDF 请传 want_pdf=true"
                      "（注意：不是 fmt —— fmt 是 zx_export_wrongbook 的参数；"
                      "本工具也认 fmt=\"pdf\" 作为兼容写法，但正统写法是 want_pdf）。"
                      "knowledge_points（或 kp）可传数组，也可传「|」分隔字符串；"
                      "verification 可传 check_practice 的 checks 数组，"
                      "也可直接传 submit_solution 的 verdict 字符串"
                      "（match/numeric_match/mismatch/undecidable）。")
@_guard
def zx_export_paper(items: str | list[dict], title: str = "错题同类练习卷",
                    out_path: str = "", want_pdf: bool = False,
                    fmt: str = "") -> str:
    # 兼容别名（2026-09-25 新增）：兄弟工具 zx_export_wrongbook 用的是 `fmt`，
    # 宿主很容易把那个习惯顺手套到这里。与其让它撞上「不认识的参数」，
    # 不如认下这个写法 —— 两个工具的参数名不一致本身就是个坑，
    # 但改名会破坏已有调用方，所以选择「认下两种写法 + 说清楚哪个是正统」。
    if fmt:
        f = fmt.strip().lower()
        if f in ("pdf", "html+pdf", "both"):
            want_pdf = True
        elif f in ("html", "md"):
            pass
        else:
            return _json({"ok": False,
                          "error": f"不支持的 fmt：{fmt}（本工具可选 html / pdf）"})
    try:
        data = json.loads(items) if isinstance(items, str) else items
    except ValueError as exc:
        return _json({"ok": False, "error": f"items 不是合法 JSON：{exc}"})
    if not isinstance(data, list) or not data:
        return _json({"ok": False, "error": "items 必须是非空数组"})
    for it in data:
        it.setdefault("kp", it.get("knowledge_points", []))
    try:
        path = write_paper(data, out_path or None, title=title)
    except Exception as exc:
        return _json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    out = {"ok": True, "html": path, "count": len(data)}
    if want_pdf:
        conv = try_pdf(path)
        out["pdf"] = conv
        # 「ok=true 不等于你要的东西生成了」—— 请求了 PDF 却没出来，
        # 必须显式说出来，不能只回一个 ok 让调用方自己猜。
        if not (isinstance(conv, dict) and conv.get("available")):
            out["warning"] = ("请求了 PDF 但没生成成功（本机没有可用的渲染器）。"
                              "HTML 已产出，可用浏览器 Ctrl+P 手动另存为 PDF。")
    return _json(out)


@mcp.tool(description="导出错题本表格。fmt 可选 md / xlsx / json。")
@_guard
def zx_export_wrongbook(fmt: str = "md", subject: str = "",
                        out_path: str = "") -> str:
    store = _store()
    try:
        items = store.query(subject=subject or None)
        if fmt == "md":
            text = wrongbook_markdown(items, title=f"{subject or '全部'}错题本")
            p = Path(out_path) if out_path else (ROOT / "out" /
                                                f"wrongbook_{datetime.now():%Y%m%d_%H%M%S}.md")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            return _json({"ok": True, "path": str(p), "count": len(items)})
        if fmt == "xlsx":
            p = out_path or str(ROOT / "out" / f"wrongbook_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
            path = wrongbook_xlsx(items, p)
            return _json({"ok": True, "path": path, "count": len(items)})
        if fmt == "json":
            p = out_path or str(ROOT / "out" / f"wrongbook_{datetime.now():%Y%m%d_%H%M%S}.json")
            write_json_report([_question_payload(q) for q in items], p)
            return _json({"ok": True, "path": p, "count": len(items)})
        return _json({"ok": False, "error": f"不支持的 fmt：{fmt}（可选 md / xlsx / json）"})
    finally:
        store.close()


@mcp.tool(description="清空本地数据（真删：数据库 + 图片 + WAL/SHM）。需要 confirm=true。")
@_guard
def zx_purge(confirm: bool = False) -> str:
    if not confirm:
        return _json({"ok": False,
                      "error": "zx_purge 需要 confirm=true。这会真删本地错题库和图片，不可恢复。"})
    store = _store()
    removed = store.purge(confirm=True)
    return _json({"ok": True, "removed": removed})


@mcp.tool(description="查看最近的同步日志（哪次同步加了多少题、有没有报错）。")
@_guard
def zx_sync_log(limit: int = 20) -> str:
    store = _store()
    try:
        logs = store.sync_logs(limit=limit)
    finally:
        store.close()
    return _json({"count": len(logs), "logs": logs})


def _install_unknown_arg_guard() -> dict:
    """让「传了不存在的参数名」变成明确错误，而不是静默忽略。

    为什么需要（2026-09-25 实测的真实缺陷）
    --------------------------------------
    pydantic 的参数模型默认 `extra='ignore'`，于是：

        zx_export_paper(items=..., fmt="pdf")

    里的 `fmt`（它属于另一个导出工具 `zx_export_wrongbook`）被**悄悄丢掉**，
    工具照常返回 `{"ok": true, ...}` —— 但 PDF 根本没生成。
    调用方拿着 ok=true 往下走，最后告诉用户「练习卷导出好了」。

    这是最危险的一类失败：**不报错，但结果是错的**。

    拦在哪
    ------
    `_tool_manager.call_tool` 是**唯一漏斗**，两条路径都经过它：

      · 直接调用（工具脚本 / 测试）  mcp.call_tool → _tool_manager.call_tool
      · 真实 MCP 协议 tools/call     _handle_call_tool → mcp.call_tool → 同一个

    所以只包这一个点就够。

    关于「碰了框架私有属性」
    ------------------------
    这是本项目唯一一处依赖框架内部结构（`_tool_manager`）的地方，因此做了两件事：
      1. 装不上时**只警告、不抛异常** —— 降级为「未知参数被忽略」，
         不能让一个加固措施反而把服务弄挂；
      2. `tools/edge_test.py` 里有一条回归检查盯着它 ——
         哪天库换了漏斗，那条检查会**失败**，而不是悄悄失效。
    """
    tm = getattr(mcp, "_tool_manager", None)
    if tm is None or not callable(getattr(tm, "call_tool", None)):
        print("[warn] 未能安装未知参数拦截：_tool_manager.call_tool 不存在。"
              "未知参数将按框架默认行为被忽略。", file=sys.stderr)
        return {"installed": False, "reason": "_tool_manager.call_tool 不存在"}

    try:
        from mcp.types import CallToolResult, TextContent
    except Exception as exc:  # pragma: no cover - 库结构变了
        print(f"[warn] 未能安装未知参数拦截：{type(exc).__name__}: {exc}",
              file=sys.stderr)
        return {"installed": False, "reason": "mcp.types 里找不到返回类型"}

    original = tm.call_tool

    async def call_tool_checked(name, arguments, *args, **kwargs):
        tool = tm._tools.get(name)
        if tool is not None:
            schema = getattr(tool, "parameters", None) or {}
            allowed = set((schema.get("properties") or {}))
            unknown = sorted(k for k in (arguments or {}) if k not in allowed)
            if unknown:
                payload = _json({
                    "ok": False,
                    "tool": name,
                    "error": f"不认识的参数：{'、'.join(unknown)}",
                    "accepted": sorted(allowed),
                    "hint": ("参数名写错了，或者这个工具本来就没有这个参数。"
                             "请只传 accepted 里列出的名字。"
                             "这里刻意**不忽略**未知参数 —— 静默忽略会变成"
                             "「返回 ok=true 但你要的东西根本没生成」。"),
                })
                return CallToolResult(content=[TextContent(type="text",
                                                          text=payload)])
        return await original(name, arguments, *args, **kwargs)

    tm.call_tool = call_tool_checked
    return {"installed": True, "tools": len(tm._tools)}


UNKNOWN_ARG_GUARD = _install_unknown_arg_guard()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
