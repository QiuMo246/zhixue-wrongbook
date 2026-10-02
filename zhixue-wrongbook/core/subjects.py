"""科目清单：给「个性化诊断前必须先问用户哪一科」这道闸门提供选项。

背景（2026-09-24 新增需求）
--------------------------
在用户让 AI 根据错题生成「个性化诊断」之前，助手必须**强制询问**
用户要诊断哪一科。这条规则要落地，需要两样东西：

  1. 一份「问什么」的候选清单 —— 由本模块给出；
  2. 一个「不确认就不给数据」的确定性闸门 —— 由 server.py 的
     `zx_diagnosis` / `zx_profile` 实施。

本模块只负责第 1 件事，**零模型调用**，只做数据拼装。

三个来源，拼装规则只写一次
--------------------------
  A. `constants.SUBJECT_ORDER`  标准学科顺序 —— 排序用，也是候选全集
  B. `taxonomy.yaml`            受控词表里的学科 —— 决定某科能不能做知识点分析
  C. 本地 SQLite                实际有错题的学科 —— 决定某科能不能真的诊断出东西

**为什么 B 和 C 要分开：** 库里可能有「历史」的错题，但受控词表里没有
历史的知识点。这一科**能列出来、能被用户选中**，却暂时做不了知识点级分析。
这件事必须如实告诉宿主（`in_taxonomy: false`），而不是假装可以。

为什么排序不按「题数」而是按固定学科顺序：如果按题数排，
就等于**数据在替用户做决定** —— 题最多的那科永远排第一，用户容易被带着走。
固定顺序对每一科都中立。
"""

from __future__ import annotations

from .constants import SUBJECT_ALIASES, SUBJECT_ORDER


def normalize_subject(name: str | None) -> str:
    """把「政治 / 道德与法治」这类别名归一化到规范名（道法）。"""
    s = (name or "").strip()
    return SUBJECT_ALIASES.get(s, s)


def order_key(subject: str) -> tuple[int, str]:
    """排序键：先按标准学科顺序，标准清单外的学科排最后（按名字）。"""
    try:
        return (SUBJECT_ORDER.index(subject), "")
    except ValueError:
        return (len(SUBJECT_ORDER), subject)


def subject_options(store, taxonomy) -> dict:
    """组装「可诊断科目清单」。

    参数
    ----
    store    : core.store.Store（提供 subject_stats()）
    taxonomy : core.taxonomy.Taxonomy（提供 subjects()）
    """
    stats = store.subject_stats()
    in_taxonomy = {normalize_subject(s) for s in taxonomy.subjects()}

    rows = []
    for name in sorted(set(stats) | in_taxonomy, key=order_key):
        st = stats.get(name) or {}
        qn = int(st.get("questions", 0))
        an = int(st.get("analyzed", 0))
        rows.append({
            "subject": name,
            "questions": qn,
            "analyzed": an,
            # 有「已分析」的题才算能诊断 —— 没分析就没有知识点，算不出掌握度
            "diagnosable": an > 0,
            "has_questions": qn > 0,
            "in_taxonomy": name in in_taxonomy,
        })

    return {
        "subjects": rows,
        "with_questions": [r["subject"] for r in rows if r["has_questions"]],
        "diagnosable": [r["subject"] for r in rows if r["diagnosable"]],
        "taxonomy_subjects": sorted(in_taxonomy, key=order_key),
        "standard_order": list(SUBJECT_ORDER),
        "library_total": sum(r["questions"] for r in rows),
    }


def ask_user_prompt(options: dict, purpose: str = "个性化诊断") -> str:
    """给宿主的「照读即可」话术。

    宿主可以直接把这句话念给用户，也可以用自己的话复述 ——
    但**不能跳过这一步**：`zx_diagnosis` 在没有用户确认前不会给任何数据。
    """
    rows = [r for r in options["subjects"] if r["has_questions"]]
    if not rows:
        return (f"要做{purpose}，我得先确认科目 —— 但本地还没有任何错题数据。"
                f"请先用 zx_sync 同步错题（或 zx_import_export_file 导入导出文件），"
                f"然后再来选科目。")
    picked = "、".join(f"{r['subject']}（{r['questions']} 道）" for r in rows)
    return (f"要做{purpose}，我得先确认一下科目 —— 你想诊断哪一科？"
            f"本地已有错题的科目：{picked}。"
            f"请告诉我要哪一科，我再开始。")
