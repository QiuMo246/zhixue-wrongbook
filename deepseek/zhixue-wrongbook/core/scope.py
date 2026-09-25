"""试卷范围：给「诊断前必须确认分析哪些试卷的错题」这道闸门提供选项。

背景（2026-09-25 新增需求）
--------------------------
原规则只要求确认「哪一科」。但一科里的错题可能横跨几个月、几十份卷子 ——
只说「物理」，助手仍然得自己决定分析哪些，等于**范围还是模型替用户定的**。
所以补上第二问：**要分析哪些试卷里的错题**，并给两个正交的维度：

  维度一 · 按试卷类型：周测 / 午练 / 晚练 / 早读（+ 其他 / 全部）
  维度二 · 按时间：本周 / 上周 / 近两周 / 本月 / 近一月 / 全部

两个维度是**且**的关系：`午练 + 本周` = 本周的午练。

本模块负责「问什么」和「把用户的话翻译成过滤条件」；
「不给范围就不给数据」由 server.py 的闸门实施。**零模型调用。**

为什么类型靠 exam_name 关键字判定，而不是新加字段
------------------------------------------------
平台就是这么命名的（「午练-八年级-20260922」「20260918八年级周测」）。
加字段意味着要为每个学校维护一张映射表；关键字匹配至少是**看得见、
可解释**的 —— 用户问「为什么这份卷子算午练」，能答得上来。

为什么候选里必须有「其他」
--------------------------
库里还有「期末测试」「期中模拟」「阶段测试」这类卷子。只列四种类型的话，
这部分错题**永远选不到** —— 那比不筛还糟：用户会以为诊断覆盖了全部。
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .constants import (PAPER_TYPE_ALIASES, PAPER_TYPE_ALL, PAPER_TYPE_OTHER,
                        PAPER_TYPES, TIME_SCOPE_ALIASES, TIME_SCOPES)

# 一个「周」从周一起算（中国习惯）。date.weekday(): 周一=0
_WEEK_START_WEEKDAY = 0


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
def normalize_paper_types(value) -> list[str]:
    """把 str / list 归一化成规范类型列表。

    接受「周测」「周测,午练」「周测|午练」「['周测','午练']」等写法。
    **不认识的词原样保留**（交给闸门报错并告诉用户合法值），
    不静默丢弃 —— 静默丢弃会让「传错了」看起来像「筛过了」。
    """
    if value is None:
        return []
    if isinstance(value, str):
        raw = [x for x in re.split(r"[|,，、;；\s]+", value) if x.strip()]
    elif isinstance(value, (list, tuple, set)):
        raw = [str(x) for x in value]
    else:
        raw = [str(value)]

    out: list[str] = []
    for x in raw:
        k = x.strip()
        if not k:
            continue
        t = PAPER_TYPE_ALIASES.get(k) or PAPER_TYPE_ALIASES.get(k.lower()) or k
        if t not in out:
            out.append(t)
    return out


def normalize_time_scope(name: str | None) -> str:
    """把「这周 / 最近两周 / 不限」这类说法归一化到规范预设名。"""
    s = (name or "").strip()
    if not s:
        return ""
    return TIME_SCOPE_ALIASES.get(s) or TIME_SCOPE_ALIASES.get(s.lower()) or s


def valid_paper_types() -> list[str]:
    """合法取值（含 其他 / 全部），用于报错时告诉用户能填什么。"""
    return list(PAPER_TYPES) + [PAPER_TYPE_OTHER, PAPER_TYPE_ALL]


# ---------------------------------------------------------------------------
# 时间范围解析
# ---------------------------------------------------------------------------
def resolve_time_scope(name: str, since: str = "", until: str = "",
                       today: date | None = None) -> dict:
    """把预设名解析成闭区间日期。返回 {name, since, until, label}。

    since / until 是 `YYYY-MM-DD` 字符串（含当天）；「全部」两者都是空串。
    自定义范围：name 传「自定义」并同时给 since/until。
    """
    today = today or date.today()
    name = normalize_time_scope(name)

    if name == "全部":
        return {"name": "全部", "since": "", "until": "",
                "label": "全部时间（不按时间筛）"}

    # 显式给了日期就优先用（支持「自定义」和微调预设）
    if since or until:
        s = _norm_date(since)
        u = _norm_date(until) or s
        return {"name": name or "自定义", "since": s, "until": u,
                "label": f"{s or '最早'} ~ {u or '今天'}"}

    if name == "本周":
        s = today - timedelta(days=(today.weekday() - _WEEK_START_WEEKDAY) % 7)
        return {"name": name, "since": s.isoformat(), "until": today.isoformat(),
                "label": f"本周（{s.isoformat()} 起，周一起算）"}
    if name == "上周":
        this_mon = today - timedelta(
            days=(today.weekday() - _WEEK_START_WEEKDAY) % 7)
        s = this_mon - timedelta(days=7)
        u = this_mon - timedelta(days=1)
        return {"name": name, "since": s.isoformat(), "until": u.isoformat(),
                "label": f"上周（{s.isoformat()} ~ {u.isoformat()}）"}
    if name == "近两周":
        s = today - timedelta(days=13)
        return {"name": name, "since": s.isoformat(), "until": today.isoformat(),
                "label": f"近两周（{s.isoformat()} 起）"}
    if name == "本月":
        s = today.replace(day=1)
        return {"name": name, "since": s.isoformat(), "until": today.isoformat(),
                "label": f"本月（{s.isoformat()} 起）"}
    if name == "近一月":
        s = today - timedelta(days=29)
        return {"name": name, "since": s.isoformat(), "until": today.isoformat(),
                "label": f"近一月（{s.isoformat()} 起）"}

    # 到这里说明 name 既不是预设、也没给日期 → 交给闸门报错
    return {"name": name, "since": "", "until": "", "label": "",
            "unknown": True}


def _norm_date(s: str) -> str:
    """把 2026/9/1、20260901、2026-09-01 都归一成 2026-09-01。"""
    s = (s or "").strip()
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    m = re.match(r"^(\d{4})\D+(\d{1,2})\D+(\d{1,2})$", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s


def resolve_scope(paper_types, time_scope: str, since: str = "",
                  until: str = "", today: date | None = None) -> dict:
    """把用户给的两个维度合成一个可直接用于查询的 scope。

    闸门放行之后调用，得到的就是**这次诊断实际覆盖的范围** ——
    既要拿去过滤查询，也要原样写进审计日志（事后核对「覆盖了什么」）。
    """
    pts = normalize_paper_types(paper_types)
    rng = resolve_time_scope(time_scope, since, until, today=today)
    return {
        "paper_types": pts or [PAPER_TYPE_ALL],
        "time_scope": rng["name"] or "全部",
        "since": rng["since"],
        "until": rng["until"],
        "label": " + ".join(
            [("、".join(pts) if pts else "全部类型"), rng["label"] or "全部时间"]),
    }


# ---------------------------------------------------------------------------
# 选项清单（给宿主问用户用）
# ---------------------------------------------------------------------------
def paper_type_options(store, subject: str = "") -> dict:
    """各试卷类型在本地库里有多少道题（可按科目限定）。"""
    counts = store.counts_by_paper_type(subject or None)
    rows = [{"type": t, "questions": int(counts.get(t, 0))} for t in PAPER_TYPES]
    rows.append({"type": PAPER_TYPE_OTHER,
                 "questions": int(counts.get(PAPER_TYPE_OTHER, 0))})
    return {
        "paper_types": rows,
        "with_questions": [r["type"] for r in rows if r["questions"] > 0],
        "total": int(counts.get("__total__", 0)),
        "valid_values": valid_paper_types(),
    }


def time_scope_options(store, subject: str = "",
                       today: date | None = None) -> dict:
    """各时间预设在本库里覆盖多少道题。"""
    today = today or date.today()
    rows = []
    for name in TIME_SCOPES:
        r = resolve_time_scope(name, today=today)
        n = store.count_questions(subject=subject or None,
                                  date_from=r["since"], date_to=r["until"])
        rows.append({"scope": name, "questions": int(n), "label": r["label"]})
    return {
        "time_scopes": rows,
        "with_questions": [r["scope"] for r in rows if r["questions"] > 0],
        "valid_values": list(TIME_SCOPES),
        "today": today.isoformat(),
    }


def ask_user_scope_prompt(subject: str, paper_opts: dict, time_opts: dict,
                          purpose: str = "个性化诊断") -> str:
    """给宿主的「照读即可」话术 —— **两问一次问完**。

    为什么把两问写在同一段里：分开问会出现「用户答完科目，才发现还要答范围」
    的来回。一次说清两个维度，用户一次答完，助手一次拿到。

    注意：这里**不给推荐值**。推荐等于替用户决定，正是这道闸门要防的事。
    """
    pt = "、".join(f"{r['type']}（{r['questions']} 道）"
                   for r in paper_opts["paper_types"] if r["questions"] > 0)
    ts = "、".join(f"{r['scope']}（{r['questions']} 道）"
                   for r in time_opts["time_scopes"] if r["questions"] > 0)

    if not pt and not ts:
        return (f"要做{purpose}，我得先确认科目和试卷范围 —— "
                f"但本地还没有「{subject}」的错题数据。"
                f"请先用 zx_sync 同步（或 zx_import_export_file 导入），然后再来选。")

    return (
        f"要做{purpose}，我得先跟你确认**两件事**，都定了我才开始：\n"
        f"① 科目：{subject}（已确认）\n"
        f"② 错题范围 —— 你这次想让我分析哪些卷子里的错题？\n"
        f"   · 按**试卷类型**选：{pt or '本地暂无分类数据'}。可多选，也可以说「全部」。\n"
        f"   · 按**时间**选：{ts or '本地暂无按时间分布的数据'}。\n"
        f"   两个维度是「且」的关系 —— 比如选「午练 + 本周」，"
        f"就是只看本周的午练。\n"
        f"请把「试卷类型 + 时间范围」告诉我，我再开始。"
    )
