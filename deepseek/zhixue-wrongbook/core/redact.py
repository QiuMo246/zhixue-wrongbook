"""PII 前置脱敏（包三，移植自 qwen 分支的 privacy/redact.ts 设计）。

为什么要有它：错题数据虽然都在本地 SQLite，但诊断/分析时题面与作答
原文会进入宿主 AI 模型的上下文 —— 这就是「出网」。README 的隐私原则
（最小必要、不调同学信息接口）管住了采集侧，这一层管住**出境侧**：
不管学生有没有把姓名/手机号/学校写进题面或作答，出境前都先打码。

「脱敏是代码路径，不是提示词」（qwen 分支 redact.ts:5 的原话）——
靠提醒模型「注意脱敏」等于没脱敏。

设计取舍：
  * 模式只收**高置信**的 PII（手机号 / 身份证 / 邮箱 / 学校名 / 班级名），
    中文姓名没有词表根本没法可靠识别 —— 所以姓名走 `names` 显式传入
    （配置里登记学生真名后自动带上），识别不到就如实不识别，
    不假装「已脱敏」。
  * 占位符按 (类别, 原文) 稳定派生（sha1 前 6 位）：同一手机号在
    整段文本里换成同一个 `{PHONE_3f2a91}`，不破坏「证据必须是原文
    引号内子串」的校验逻辑（占位符只用在出境副本，库里原文不动）。
  * 误伤可控：模式刻意保守（如学校名只认「××中学/××小学」这类
    强后缀），漏报好过误报 —— 误报会把题干改得没法分析。
"""

from __future__ import annotations

import hashlib
import re

# (类别, 编译好的正则, 人话描述) —— 顺序即优先级，先匹配先占位
PII_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("PHONE", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "手机号"),
    ("IDCARD", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "身份证号"),
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
     "电子邮箱"),
    ("SCHOOL", re.compile(
        r"[\u4e00-\u9fa5]{2,15}(?:省|市|区|县)?[\u4e00-\u9fa5]{0,6}"
        r"(?:中学|小学|外国语学校|实验学校|高级中学|初级中学)"), "学校名"),
    ("CLASS", re.compile(
        r"(?:[七八九初高]{1,2}[一二三]?|\d{1,2})年级?[（(]?\d{1,3}[）)]?班"),
     "班级名"),
    ("STUID", re.compile(r"(?<![0-9A-Za-z])\d{10,12}(?![0-9A-Za-z])"),
     "疑似学号"),
]

CATEGORY_LABEL = {cat: desc for cat, _, desc in PII_PATTERNS}
CATEGORY_LABEL["NAME"] = "姓名（显式登记）"


def scan(text: str, names: list[str] | None = None) -> list[tuple[str, str]]:
    """返回文本里命中的 PII 列表 [(类别, 原文), ...]（不去重排序）。"""
    hits: list[tuple[str, str]] = []
    if not text:
        return hits
    phone_pat = dict((c, p) for c, p, _d in PII_PATTERNS)["PHONE"]
    for cat, pat, _desc in PII_PATTERNS:
        for m in pat.finditer(text):
            v = m.group(0)
            # 11 位手机号必然同时命中 10~12 位的「疑似学号」——
            # 学号让位给更具体的手机号类别，一个号码只报一次。
            if cat == "STUID" and phone_pat.fullmatch(v):
                continue
            hits.append((cat, v))
    for n in names or []:
        if n and n in text:
            hits.append(("NAME", n))
    return hits


def _placeholder(cat: str, original: str) -> str:
    tag = hashlib.sha1(f"{cat}\x00{original}".encode("utf-8")).hexdigest()[:6]
    return f"{{{cat}_{tag}}}"


def redact_text(text: str, names: list[str] | None = None) -> tuple[str, int]:
    """把文本里的 PII 换成稳定占位符。返回 (打码后的文本, 命中数)。

    同一 PII → 同一占位符（跨调用稳定），证据子串校验不受影响。
    库里的原文不动 —— 这一层只处理**出境副本**。
    """
    hits = scan(text, names)
    if not hits:
        return text, 0
    out = text
    for cat, original in hits:
        out = out.replace(original, _placeholder(cat, original))
    return out, len(hits)


def scan_payload(obj, names: list[str] | None = None,
                 _counter: dict | None = None) -> dict[str, int]:
    """递归扫 dict/list 里的所有字符串，返回 {类别: 命中次数}。

    用于出口披露清单：告诉用户「这次要交给 AI 的数据里发现了哪些
    类别的个人信息」，而不是把命中的原文列出来（那本身就又是一
    次出境）。
    """
    counter = _counter if _counter is not None else {}
    if isinstance(obj, dict):
        for v in obj.values():
            scan_payload(v, names, counter)
    elif isinstance(obj, list):
        for v in obj:
            scan_payload(v, names, counter)
    elif isinstance(obj, str):
        for cat, _original in scan(obj, names):
            counter[cat] = counter.get(cat, 0) + 1
    return counter


def redact_payload(obj, names: list[str] | None = None):
    """对整个 payload 做出境打码（返回新结构，不动原对象）。"""
    if isinstance(obj, dict):
        return {k: redact_payload(v, names) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_payload(v, names) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj, names)[0]
    return obj
