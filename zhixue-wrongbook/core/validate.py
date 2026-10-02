"""确定性校验层：submit_analysis / check_practice / submit_solution 的核心。

这是整个架构里最要紧的一块——「可审计的推理」就落在这里。
宿主模型可以自由发挥，但它的结论必须过三道确定性闸门才会落库：

1. 错因必须是 8 类枚举之一
2. 知识点必须能在 taxonomy.yaml 里解析到（只能选，不能造）
3. 证据必须能在题干/标准答案/解析/学生作答里定位到

本模块**不含任何模型调用**，纯字符串与数值计算。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .constants import (DIFFICULTY_TOLERANCE, ERROR_TYPES, JACCARD_MIN,
                        STEP_DIFF_MAX)
from .models import WrongQuestion, html_to_text, squash
from .taxonomy import Taxonomy

# ---------------------------------------------------------------------------
# 结果容器
# ---------------------------------------------------------------------------


@dataclass
class CheckItem:
    """单个闸门的检查结果。kind: hard=必须通过, soft=仅参考。"""
    name: str
    kind: str
    passed: bool
    value: Any = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "passed": self.passed,
                "value": self.value, "detail": self.detail}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    normalized: dict = field(default_factory=dict)
    items: list[CheckItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings,
                "normalized": self.normalized,
                "items": [i.to_dict() for i in self.items]}


# ---------------------------------------------------------------------------
# 文本定位工具
# ---------------------------------------------------------------------------
_QUOTE_PAIRS = [("「", "」"), ("“", "”"), ("『", "』"), ("`", "`"),
                ("\"", "\""), ("'", "'"), ("《", "》")]


def extract_quotes(text: str) -> list[str]:
    """从证据里抽出被引号包住的片段。这些是「必须能定位」的硬引文。"""
    found: list[str] = []
    for left, right in _QUOTE_PAIRS:
        start = 0
        while True:
            i = text.find(left, start)
            if i < 0:
                break
            j = text.find(right, i + len(left))
            if j < 0:
                break
            frag = text[i + len(left):j].strip()
            if frag:
                found.append(frag)
            start = j + len(right)
    return found


def longest_common_substring_len(a: str, b: str, cap: int = 4000) -> int:
    """最长公共子串长度（滑动窗口 + 集合剪枝，够用且不慢）。"""
    a, b = a[:cap], b[:cap]
    if not a or not b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    lo, hi = 0, len(a)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        windows = {a[i:i + mid] for i in range(0, len(a) - mid + 1)}
        if any(w in b for w in windows if w):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


# ---------------------------------------------------------------------------
# 闸门 1~3：submit_analysis
# ---------------------------------------------------------------------------
def validate_analysis(question: WrongQuestion, payload: dict,
                      taxonomy: Taxonomy) -> ValidationResult:
    """校验宿主提交的错因分析。

    payload 期望字段：
      error_type: str                  —— 必填，8 类枚举之一
      knowledge_points: list[str]      —— 必填，非空
      evidence: list[str]              —— 必填，非空，需可定位
      confidence: float                —— 必填，0~1
      needs_review: bool               —— 可选，默认 False
      analyzed_by: str                 —— 必填（可追溯性）
      prompt_version: str              —— 必填（可追溯性）
    """
    res = ValidationResult(ok=True)
    norm: dict = {}

    # --- 错因枚举 ---
    et = (payload.get("error_type") or "").strip()
    if et not in ERROR_TYPES:
        res.ok = False
        res.errors.append(
            f"error_type「{et}」不在受控枚举内。合法值：{'、'.join(ERROR_TYPES)}")
        res.items.append(CheckItem("错因枚举", "hard", False, et, "不在 8 类枚举内"))
    else:
        norm["error_type"] = et
        res.items.append(CheckItem("错因枚举", "hard", True, et, ""))

    # --- 知识点（词表闸门） ---
    raw_kps = payload.get("knowledge_points") or []
    if isinstance(raw_kps, str):
        raw_kps = [raw_kps]
    resolved, kp_errors = [], []
    for raw in raw_kps:
        info, reason = taxonomy.resolve(str(raw), subject=question.subject)
        if info is None:
            kp_errors.append(reason)
        elif info.path not in resolved:
            resolved.append(info.path)
    if not raw_kps:
        kp_errors.append("knowledge_points 为空——每道题至少要标 1 个知识点")
    if kp_errors:
        res.ok = False
        res.errors.extend(kp_errors)
        res.items.append(CheckItem("知识点在词表内", "hard", False, raw_kps,
                                   "；".join(kp_errors)))
    else:
        norm["knowledge_points"] = resolved
        res.items.append(CheckItem("知识点在词表内", "hard", True, resolved, ""))
        # 提示：跨学科标注很可能是标错了
        cross = [kp for kp in resolved
                 if kp.split("/")[0] != question.subject]
        if cross:
            res.warnings.append(
                f"知识点学科与题目学科（{question.subject}）不一致：{cross}")

    # --- 证据可定位 ---
    evidences = payload.get("evidence") or []
    if isinstance(evidences, str):
        evidences = [evidences]
    evidences = [str(e).strip() for e in evidences if str(e).strip()]
    corpus = squash(question.corpus_for_evidence())
    student_img_only = bool(question.answer.student_images) and not question.student_text

    if not evidences:
        res.ok = False
        res.errors.append("evidence 为空——必须给出至少一条证据")
        res.items.append(CheckItem("证据可定位", "hard", False, None, "未提供证据"))
    elif not corpus:
        # 题目是纯图片（题干和作答都只有图），文本定位在原理上做不到。
        # 诚实处理：不假装通过，也不误判为造假，标记为「无法校验」，
        # 并强制 needs_review=True，让人去看原图。
        res.warnings.append(
            "该题无可用文本（题干/作答均为图片），证据无法做字符串定位，"
            "已强制标记 needs_review=true")
        res.items.append(CheckItem("证据可定位", "soft", False, None,
                                   "无文本语料，无法校验（已转人工复核）"))
        norm["evidence_unverifiable"] = True
    else:
        bad = []
        short_hits = []
        for ev in evidences:
            quotes = extract_quotes(ev)
            targets = quotes or [ev]
            hit = False
            matched_len = 0
            for t in targets:
                st = squash(t)
                if not st:
                    continue
                if st in corpus:
                    hit = True
                    matched_len = max(matched_len, len(st))
                    break
                # 没整段命中，看最长公共子串够不够长（>=6 字）
                lcs = longest_common_substring_len(st, corpus)
                if lcs >= 6:
                    hit = True
                    matched_len = max(matched_len, lcs)
                    break
            if not hit:
                bad.append(ev)
            elif matched_len < 4:
                short_hits.append(ev)
        if bad:
            res.ok = False
            res.errors.append(
                "以下证据无法在题干/标准答案/解析/学生作答中定位："
                + "；".join(f"「{b}」" for b in bad)
                + "。证据必须是原文片段（可用引号引用），不能是主观描述。")
            res.items.append(CheckItem("证据可定位", "hard", False, bad, "定位失败"))
        else:
            norm["evidence"] = evidences
            res.items.append(CheckItem("证据可定位", "hard", True, evidences, ""))
            if short_hits:
                # 像「A」「D」这种单字符引文，虽然字面上能在语料里找到，
                # 但 1~3 个字符的巧合命中概率很高，校验强度不足。
                # 不否决，但必须说出来——这是「通过了但不可信」的情况。
                res.warnings.append(
                    "以下证据的引用片段过短（<4 字），字符串定位可能只是巧合命中，"
                    "建议改为引用选项原文或完整句子：" + "；".join(f"「{s}」" for s in short_hits))
            if student_img_only:
                res.warnings.append(
                    "学生作答为图片（手写），文本比对不能反映书写细节，"
                    "主观题错因只宜给倾向性判断")

    # --- 置信度 ---
    try:
        conf = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = -1.0
    if not 0.0 <= conf <= 1.0:
        res.ok = False
        res.errors.append(f"confidence 必须是 0~1 的数值，收到 {payload.get('confidence')!r}")
        res.items.append(CheckItem("置信度范围", "hard", False, conf, ""))
    else:
        norm["confidence"] = conf
        res.items.append(CheckItem("置信度范围", "hard", True, conf, ""))
        if conf < 0.5:
            res.warnings.append(f"置信度偏低（{conf}），已建议人工复核")

    # --- needs_review 与低置信度的一致性 ---
    needs_review = bool(payload.get("needs_review", False))
    if conf < 0.5:
        needs_review = True
    norm["needs_review"] = needs_review

    # --- 可追溯性 ---
    for fld in ("analyzed_by", "prompt_version"):
        val = (payload.get(fld) or "").strip()
        if not val:
            res.ok = False
            res.errors.append(
                f"{fld} 不能为空——分析结果必须可追溯到「谁、用哪版提示词」产生的")
        else:
            norm[fld] = val
    res.items.append(CheckItem(
        "可追溯性(analyzed_by/prompt_version)", "hard",
        bool(norm.get("analyzed_by") and norm.get("prompt_version")),
        f"{norm.get('analyzed_by', '')} / {norm.get('prompt_version', '')}", ""))

    res.normalized = norm
    return res


# ---------------------------------------------------------------------------
# 闸门 4：check_practice（生成题校验的确定性部分）
# ---------------------------------------------------------------------------
def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def validate_practice(candidate: dict, target: WrongQuestion,
                      taxonomy: Taxonomy,
                      difficulty_metric=None) -> ValidationResult:
    """校验一道生成题是否与目标错题「同知识点同难度」。

    candidate 期望字段：
      gen_id, qtype, knowledge_points, difficulty, steps(可选), stem_text(可选)

    difficulty_metric: 可选，注入一个 (candidate_text, target) -> float 的
      相似度函数（文本/嵌入）。**仅作软参考，不作为闸门**——
      这是 v1 的教训：数学题换个数字，文本相似度就暴跌。
    """
    res = ValidationResult(ok=True)

    # --- 硬约束 1：题型一致 ---
    ctype = (candidate.get("qtype") or "").strip()
    ok_type = ctype == target.question.type
    res.items.append(CheckItem("题型一致", "hard", ok_type, ctype,
                               "" if ok_type else f"目标题型为 {target.question.type}"))
    if not ok_type:
        res.ok = False
        res.errors.append(f"题型不一致：生成题是「{ctype}」，目标题是「{target.question.type}」")

    # --- 解析生成题的知识点 ---
    raw_kps = candidate.get("knowledge_points") or []
    if isinstance(raw_kps, str):
        raw_kps = [raw_kps]
    gen_kps, kp_err = set(), []
    for raw in raw_kps:
        info, reason = taxonomy.resolve(str(raw), subject=target.subject)
        if info is None:
            kp_err.append(reason)
        else:
            gen_kps.add(info.path)
    if kp_err:
        res.ok = False
        res.errors.extend(kp_err)
    if not gen_kps:
        res.ok = False
        res.errors.append("生成题未提供有效知识点，无法校验")

    tgt_kps = set(target.analysis.knowledge_points) if target.analysis else set()
    if not tgt_kps:
        res.ok = False
        res.errors.append(
            "目标错题尚未分析（没有知识点），无法做同类题校验。"
            "请先对目标题调用 submit_analysis。")

    # --- 硬约束 2：知识点 Jaccard >= 0.6 ---
    j = jaccard(gen_kps, tgt_kps)
    ok_j = j >= JACCARD_MIN and bool(tgt_kps)
    res.items.append(CheckItem("知识点 Jaccard", "hard", ok_j, round(j, 3),
                               f"阈值 >= {JACCARD_MIN}"))
    if not ok_j:
        res.ok = False
        res.errors.append(
            f"知识点重合度不足：Jaccard={j:.2f} < {JACCARD_MIN}。"
            f"生成题={sorted(gen_kps)}，目标题={sorted(tgt_kps)}")

    # --- 硬约束 3：超纲检查（知识点落在目标章节内） ---
    tgt_chapters = {"/".join(kp.split("/")[:2]) for kp in tgt_kps}
    out_of_scope = []
    for kp in gen_kps:
        chap = "/".join(kp.split("/")[:2])
        if chap not in tgt_chapters:
            out_of_scope.append(kp)
    ok_scope = not out_of_scope
    res.items.append(CheckItem("超纲检查", "hard", ok_scope, sorted(gen_kps),
                               f"目标章节={sorted(tgt_chapters)}"))
    if not ok_scope:
        res.ok = False
        res.errors.append(
            f"疑似超纲：{out_of_scope} 不在目标章节 {sorted(tgt_chapters)} 内")

    # --- 硬约束 4：难度落在 ±0.15 ---
    # 前提是难度刻度已核实（0~1）。刻度未核实时**降级为软参考**并明说，
    # 不拿一个错的阈值假装闸门有效（见 docs/字段核实报告.md §3.1）。
    td = target.question.difficulty
    cd = candidate.get("difficulty")
    scale_ok = getattr(target.question, "difficulty_scale", "unknown") in ("0-1",)
    gate_kind = "hard" if scale_ok else "soft"
    try:
        cd = float(cd) if cd is not None else None
    except (TypeError, ValueError):
        cd = None
    if td is None or cd is None:
        res.items.append(CheckItem("难度区间", "soft", False, cd,
                                   "缺少难度数据，无法校验（平台未提供或生成题未给）"))
        res.warnings.append("难度数据缺失，本项未校验")
    else:
        diff = abs(cd - td)
        ok_d = diff <= DIFFICULTY_TOLERANCE
        res.items.append(CheckItem("难度区间", gate_kind, ok_d, round(diff, 3),
                                   f"目标 {td}，生成 {cd}，允许 ±{DIFFICULTY_TOLERANCE}"
                                   + ("" if scale_ok else "；⚠ 难度刻度未核实，本项仅作参考")))
        if not ok_d:
            if scale_ok:
                res.ok = False
                res.errors.append(
                    f"难度偏离过大：|{cd} - {td}| = {diff:.2f} > {DIFFICULTY_TOLERANCE}")
            else:
                res.warnings.append(
                    f"难度偏离 {diff:.2f}，但难度刻度未核实（config.yaml 的 "
                    f"difficulty.scale），本次不作否决。核实后本项会变成硬约束。")

    # --- 软参考 1：解题步骤数差 ---
    ts = candidate.get("steps")
    # 目标题步骤数：优先取分析里给的，缺失则不算
    tgt_steps = candidate.get("target_steps")
    if ts is not None and tgt_steps is not None:
        try:
            d = abs(int(ts) - int(tgt_steps))
            ok_s = d <= STEP_DIFF_MAX
            res.items.append(CheckItem("步骤数差", "soft", ok_s, d,
                                       f"阈值 <= {STEP_DIFF_MAX}（仅参考）"))
            if not ok_s:
                res.warnings.append(f"解题步骤数相差 {d} 步，略高于参考阈值")
        except (TypeError, ValueError):
            res.items.append(CheckItem("步骤数差", "soft", False, None, "步骤数不是整数"))
    else:
        res.items.append(CheckItem("步骤数差", "soft", False, None,
                                   "缺少步骤数信息，未计算（仅参考）"))

    # --- 软参考 2：文本/嵌入相似度 ---
    if difficulty_metric is not None:
        try:
            sim = float(difficulty_metric(candidate.get("stem_text") or "", target))
            res.items.append(CheckItem("文本相似度", "soft", True, round(sim, 3),
                                       "仅作参考，不作为闸门"))
        except Exception as exc:  # 相似度是可选增强，坏了不能拖垮主流程
            res.items.append(CheckItem("文本相似度", "soft", False, None,
                                       f"计算失败：{exc}"))
    else:
        res.items.append(CheckItem("文本相似度", "soft", False, None,
                                   "未注入相似度函数（默认关闭）"))

    res.normalized = {"gen_id": candidate.get("gen_id", ""),
                      "knowledge_points": sorted(gen_kps),
                      "jaccard": round(j, 3)}
    return res


# ---------------------------------------------------------------------------
# 闸门 5：submit_solution（答案确定性比对）
# ---------------------------------------------------------------------------
_UNIT_MAP = {
    "厘米": "cm", "米": "m", "分米": "dm", "毫米": "mm", "千米": "km",
    "克": "g", "千克": "kg", "吨": "t", "毫升": "ml", "升": "l",
    "秒": "s", "分钟": "min", "小时": "h", "度": "deg",
}
_FULLWIDTH = str.maketrans("０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
                           "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ＋－＝／（）",
                           "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                           "abcdefghijklmnopqrstuvwxyz+-=/()")


def normalize_answer(text: str | None) -> str:
    """答案归一化：全角转半角、去空白、单位统一、去掉常见前缀。"""
    if not text:
        return ""
    s = html_to_text(text).translate(_FULLWIDTH)
    for zh, en in _UNIT_MAP.items():
        s = s.replace(zh, en)
    s = s.replace("，", ",").replace("。", ".").replace("：", ":")
    s = squash(s).lower()
    for prefix in ("答案:", "答:", "answer:", "="):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s


def _extract_numbers(text: str) -> list[float]:
    out = []
    for m in re.findall(r"-?\d+(?:\.\d+)?", text):
        try:
            out.append(float(m))
        except ValueError:
            pass
    return out


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
PROSE_CJK_MIN = 12     # 归一化后中文超过这个字数，就当成「成段文字」答案


def _looks_like_prose(norm: str) -> bool:
    """判断归一化后的答案是不是「成段文字」而不是可字符串比对的短答案。

    为什么要单独判（2026-09-24 实测暴露）：原来的规则只有 `len(b) > 60`。
    一道证明题的标准答案归一化后正好 50 字，漏过阈值被**硬判成 mismatch**——
    于是宿主写出的正确证明被判「错」，还经 `submit_solution(record=True)`
    写进了练习历史。比对的可靠区间本来就只覆盖「选项字母 / 数值 / 词 /
    分号分隔的填空」，成段文字必须返回 undecidable，交给人工或宿主复核。

    两类成段文字都要认出来：
      · 中文解析式答案（证明过程、实验结论）—— 按中文数量判
      · 英文长答案（任务型阅读的开放题）—— 没有中文，只能按长度判
    """
    if len(norm) > 60:
        return True
    return len(_CJK_RE.findall(norm)) >= PROSE_CJK_MIN


def compare_solution(submitted: str, standard: str,
                     rel_tol: float = 1e-6) -> dict:
    """确定性比对宿主解答与标准答案。

    返回 verdict ∈ {match, numeric_match, mismatch, undecidable}
    undecidable = 任一侧是成段文字（比如长篇解析），此时不硬判对错，
    而是交给宿主/人工——**不猜**。
    """
    a, b = normalize_answer(submitted), normalize_answer(standard)
    if not a or not b:
        return {"verdict": "undecidable", "reason": "答案为空或无法归一化",
                "submitted_norm": a, "standard_norm": b}
    if a == b:
        return {"verdict": "match", "reason": "归一化后完全一致",
                "submitted_norm": a, "standard_norm": b}

    # 成段文字判定必须排在 numeric_match **之前**（2026-09-24 实测修正）。
    # 原来的顺序是先 numeric_match、后成段文字，结果是：一道证明题，
    # 宿主写「…=8n，n为整数，故8n是8的倍数」、标准答案写
    # 「…=8n，因为n为整数，所以8n是8的倍数」——两边数字序列恰好一样
    # （都是 4,2,4,1,4,2,-4,1,8,8,8），于是被判 numeric_match。
    # 可这跟本函数文档写的「任一侧是成段文字…不硬判对错」直接矛盾：
    # 证明题的数字序列撞车纯属偶然，撞上了也不代表推导对。
    # 顺序调过来之后，成段文字一律 undecidable，符合「不猜」的原则。
    if _looks_like_prose(a) or _looks_like_prose(b):
        return {"verdict": "undecidable",
                "reason": "答案含成段文字（解析/证明/结论），无法做字符串级判定，"
                          "请人工或宿主复核",
                "submitted_norm": a, "standard_norm": b}

    na, nb = _extract_numbers(a), _extract_numbers(b)
    if na and nb and len(na) == len(nb):
        if all(abs(x - y) <= rel_tol * max(1.0, abs(y)) for x, y in zip(na, nb)):
            return {"verdict": "numeric_match", "reason": "数值逐项一致（容差内）",
                    "submitted_norm": a, "standard_norm": b}

    return {"verdict": "mismatch", "reason": "归一化后不一致",
            "submitted_norm": a, "standard_norm": b}
