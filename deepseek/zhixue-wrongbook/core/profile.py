"""学情统计：知识点掌握度、薄弱项、错因分布。**纯确定性计算，零模型调用。**

掌握度公式（架构文档 8.3，可复现）：

    掌握度(K) = Σ(w_i × score_i / full_i) / Σ(w_i)

      i    = 该知识点下的第 i 道题
      w_i  = 时间衰减权重：距今 ≤30 天 → 1.0；30~90 天 → 0.6；>90 天 → 0.3
      样本量门槛：n < 3 时输出「样本不足」，**不给数值**

这里有两个文档没写死、我做了明确选择的地方（都写进验收报告）：

1. 「距今」的基准日取**考试日期**（exam.date），缺失时退到 fetched_at。
   理由：掌握度反映的是「那段时间我学得怎么样」，用考试日期比用抓取日期
   更贴近真实学习轨迹。如果同一场考试补抓两次，用 fetched_at 会让
   权重突然变新，属于人为失真。
2. 得分率为 None 的题（满分缺失）**不计入**分母，但会被计数到
   excluded 里暴露出来——不静默丢弃数据。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterable

from .constants import (DECAY_MID_DAYS, DECAY_RECENT_DAYS, DECAY_W_MID,
                        DECAY_W_OLD, DECAY_W_RECENT, MASTERY_MIN_SAMPLES)
from .models import WrongQuestion
from .store import Store


def _parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip().replace("/", "-").replace("年", "-").replace("月", "-").replace("日", "")
    s = s.strip("-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s[:len(fmt) + 6].strip(), fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def decay_weight(ref: date | None, now: date) -> float:
    if ref is None:
        return DECAY_W_RECENT  # 没日期就不衰减，但会在输出里标 no_date
    days = (now - ref).days
    if days <= DECAY_RECENT_DAYS:
        return DECAY_W_RECENT
    if days <= DECAY_MID_DAYS:
        return DECAY_W_MID
    return DECAY_W_OLD


def reference_date(q: WrongQuestion) -> date | None:
    return _parse_date(q.exam.date) or _parse_date(q.fetched_at)


def mastery_for_kp(questions: Iterable[WrongQuestion], kp: str,
                   now: date | None = None) -> dict:
    now = now or datetime.now(timezone.utc).date()
    num = den = 0.0
    n = 0
    excluded = 0
    no_date = 0
    detail = []
    for q in questions:
        if not q.analysis or kp not in q.analysis.knowledge_points:
            continue
        if q.score.rate is None:
            excluded += 1
            continue
        ref = reference_date(q)
        if ref is None:
            no_date += 1
        w = decay_weight(ref, now)
        num += w * q.score.rate
        den += w
        n += 1
        detail.append({"id": q.id, "rate": round(q.score.rate, 3),
                       "weight": w, "date": (ref or "").__str__()})
    if n < MASTERY_MIN_SAMPLES:
        return {"kp": kp, "mastery": None, "n": n, "insufficient": True,
                "reason": f"样本量 {n} < {MASTERY_MIN_SAMPLES}，样本不足",
                "excluded": excluded, "no_date": no_date, "samples": detail}
    return {"kp": kp, "mastery": round(num / den, 4), "n": n,
            "insufficient": False, "excluded": excluded, "no_date": no_date,
            "samples": detail}


def error_type_distribution(questions: Iterable[WrongQuestion]) -> dict:
    dist: dict[str, int] = {}
    review = 0
    for q in questions:
        if not q.analysis:
            continue
        dist[q.analysis.error_type] = dist.get(q.analysis.error_type, 0) + 1
        if q.analysis.needs_review:
            review += 1
    total = sum(dist.values())
    return {
        "counts": dict(sorted(dist.items(), key=lambda kv: -kv[1])),
        "total": total,
        "needs_review": review,
        "ratio": {k: round(v / total, 3) for k, v in dist.items()} if total else {},
    }


def build_profile(store: Store, subject: str | None = None,
                  now: date | None = None,
                  weak_top: int = 10,
                  paper_types: list[str] | None = None,
                  date_from: str = "", date_to: str = "",
                  scope_label: str = "") -> dict:
    """生成学情画像。全部是计数与加权平均，没有模型参与。

    paper_types / date_from / date_to 是「试卷范围」过滤（2026-09-25 新增）。
    这几个参数**必须真的生效** —— 否则「诊断前先问范围」就只是句问话，
    用户选了「本周午练」却拿到全量结论，那比不问更糟。
    """
    now = now or datetime.now(timezone.utc).date()
    questions = store.query(subject=subject, exclude_low_confidence=True,
                            paper_types=paper_types,
                            date_from=date_from, date_to=date_to)

    kps: set[str] = set()
    for q in questions:
        if q.analysis:
            kps.update(q.analysis.knowledge_points)

    rows = [mastery_for_kp(questions, kp, now) for kp in sorted(kps)]
    measured = [r for r in rows if not r["insufficient"]]
    insufficient = [r for r in rows if r["insufficient"]]

    # 薄弱 = 掌握度升序（低分优先），样本量并列时样本多的更可信
    weak = sorted(measured, key=lambda r: (r["mastery"], -r["n"]))[:weak_top]

    excluded_low_conf = store.conn.execute(
        "SELECT COUNT(*) c FROM questions WHERE parse_confidence < 0.5"
    ).fetchone()["c"]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subject_filter": subject,
        "scope": {
            "paper_types": list(paper_types or []),
            "since": date_from, "until": date_to,
            "label": scope_label,
        },
        "question_count": len(questions),
        "excluded_low_parse_confidence": excluded_low_conf,
        "analyzed_count": sum(1 for q in questions if q.analysis),
        "unanalyzed_count": sum(1 for q in questions if not q.analysis),
        "kp_mastery": measured + insufficient,
        "weak_top": weak,
        "insufficient_samples": [r["kp"] for r in insufficient],
        "error_type_distribution": error_type_distribution(questions),
        "method": {
            "formula": "Σ(w_i × score_i/full_i) / Σ(w_i)",
            "decay": {f"<={DECAY_RECENT_DAYS}d": DECAY_W_RECENT,
                      f"{DECAY_RECENT_DAYS}~{DECAY_MID_DAYS}d": DECAY_W_MID,
                      f">{DECAY_MID_DAYS}d": DECAY_W_OLD},
            "min_samples": MASTERY_MIN_SAMPLES,
            "reference_date": "exam.date 优先，缺失时用 fetched_at",
        },
    }


def review_queue(store: Store) -> list[dict]:
    """需要人工复核的题：needs_review=true 或解析置信度低。"""
    out = []
    for q in store.query(exclude_low_confidence=False):
        reasons = []
        if q.analysis and q.analysis.needs_review:
            reasons.append("分析标记 needs_review")
        if q.parse_confidence < 0.5:
            reasons.append(f"解析置信度低({q.parse_confidence})")
        if q.analysis and q.analysis.confidence < 0.5:
            reasons.append(f"分析置信度低({q.analysis.confidence})")
        if reasons:
            out.append({"fingerprint": q.fingerprint(), "id": q.id,
                        "subject": q.subject, "exam": q.exam.name,
                        "reasons": reasons})
    return out
