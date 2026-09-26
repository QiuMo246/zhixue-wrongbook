"""出题验证门禁：强度分级 + 数值回代（包六，移植自 qwen 分支 practice/ 设计）。

为什么：`check_practice` 过的是**结构**门禁（题型/知识点/难度），
`submit_solution` 比对的是**宿主自己的解答**。生成题的**答案本身**
对不对，之前全靠宿主自觉 —— 这是「数据面/推理面分离」贯彻得最弱的一环。
qwen 分支的做法：把验证强度分成显式的三档，并且 **weak 不许冒充 strong**
（练习卷上「校验通过」四个字必须是算出来的，不是声称出来的）。

强度分级（verification strength）：
    exact    归一化后与标准答案完全一致                （强）
    numeric  数值逐项一致（容差内）或回代等式成立       （强）
    weak     只有结构门禁通过 / 证据不足               （弱 —— 不得标 verified）
    undecidable 两侧是成段文字等无法机器判定的情形     （弱 —— 不猜）

回代验证（self_check）：宿主把「生成题 + 它声称的答案」构造一个
代入等式（如答案 x=2，题含方程 x^2-5x+6=0 → "4-10+6=0"），本模块用
**白名单算术求值器**验证等式成立。这是 qwen MathVerifier（numeric 回代）
的最小完整移植：只认数字和 +-*/()^%.，任何其他符号直接拒判（undecidable），
绝不 eval 原始字符串。
"""

from __future__ import annotations

import re

STRENGTH_EXACT = "exact"
STRENGTH_NUMERIC = "numeric"
STRENGTH_WEAK = "weak"
STRENGTH_UNDECIDABLE = "undecidable"

STRONG = {STRENGTH_EXACT, STRENGTH_NUMERIC}

# 允许出现在回代等式里的字符在 eval_expr 内用 fullmatch 白名单锁定；
# 其余符号（字母/汉字/下划线…）一律 undecidable，不猜。


def eval_expr(expr: str) -> float | None:
    """白名单算术求值器：只认 数字 . + - * / ( ) ^ % 空格。

    返回数值；含任何白名单之外的字符（字母、汉字、下划线、连续符号）
    一律返回 None —— **绝不 eval**，这是安全边界不是性能取舍。
    `=` 出现在表达式里由调用方先拆分（本函数只算单边）。
    """
    s = (expr or "").replace("^", "**").replace("×", "*").replace("÷", "/")
    s = s.replace("%", "/100")
    s = re.sub(r"\s+", "", s)
    if not s or not re.fullmatch(r"[0-9.+\-*/()]+", s):
        return None
    try:
        # 求值前已用 fullmatch 锁定字符白名单（排除字母/属性注入），
        # 语法合法性交给 try/except 兜底；never eval 原始用户串以外的内容
        val = eval(s, {"__builtins__": {}}, {})  # noqa: S307 - 白名单字符已锁定
        if isinstance(val, (int, float)) and abs(float(val)) < 1e15:
            return float(val)
        return None
    except Exception:
        return None


def check_equation(equation: str) -> dict:
    """验证 `左=右` 型回代等式是否成立。返回 {verdict, strength, detail}。"""
    s = (equation or "").strip()
    if "=" not in s:
        return {"verdict": "undecidable", "strength": STRENGTH_UNDECIDABLE,
                "detail": "self_check 里没有 '='，构造不出可验证等式"}
    left, right = s.split("=", 1)
    lv, rv = eval_expr(left), eval_expr(right)
    if lv is None or rv is None:
        return {"verdict": "undecidable", "strength": STRENGTH_UNDECIDABLE,
                "detail": ("回代等式含白名单之外的符号，拒绝硬判 —— "
                           "请把等式化成纯算术式（数字与 +-*/()^.%）再试")}
    if abs(lv - rv) <= 1e-9 * max(1.0, abs(rv)):
        return {"verdict": "match", "strength": STRENGTH_NUMERIC,
                "detail": f"回代等式成立：{left.strip()} = {right.strip()} = {rv:g}"}
    return {"verdict": "mismatch", "strength": STRENGTH_NUMERIC,
            "detail": f"回代等式不成立：左={lv:g}，右={rv:g} —— 生成题的答案大概率错了"}


def verify_answer(generated_answer: str, standard_answer: str = "",
                  self_check: str = "") -> dict:
    """生成题答案的三层验证：回代等式 → 与标准答案比对 → 如实降级。

    返回 {"verdict", "strength", "detail"}；
    strength ∈ {exact, numeric, weak, undecidable}，只有前两档算 strong。
    """
    if self_check.strip():
        eq = check_equation(self_check)
        if eq["verdict"] == "match":
            return eq
        if eq["verdict"] == "mismatch":
            return eq
        # undecidable 继续往下走其他层
    a, b = (generated_answer or "").strip(), (standard_answer or "").strip()
    if not a:
        return {"verdict": "undecidable", "strength": STRENGTH_UNDECIDABLE,
                "detail": "生成题为空，无从验证"}
    if not b:
        return {"verdict": "undecidable", "strength": STRENGTH_WEAK,
                "detail": "没有标准答案可比对，也没有可回代的等式 —— 如实记 weak，不猜"}
    na, nb = a.replace("^", "**").replace("×", "*").replace("÷", "/").replace("%", "/100"), \
        b.replace("^", "**").replace("×", "*").replace("÷", "/").replace("%", "/100")
    if a == b:
        return {"verdict": "match", "strength": STRENGTH_EXACT,
                "detail": "与标准答案逐字一致"}
    na_v, nb_v = eval_expr(a), eval_expr(b)
    if na_v is not None and nb_v is not None:
        if abs(na_v - nb_v) <= 1e-6 * max(1.0, abs(nb_v)):
            return {"verdict": "numeric_match", "strength": STRENGTH_NUMERIC,
                    "detail": f"两侧均为纯算术式且数值一致（= {nb_v:g}）"}
        return {"verdict": "mismatch", "strength": STRENGTH_NUMERIC,
                "detail": f"两侧均为纯算术式但数值不同（{na_v:g} ≠ {nb_v:g}）"}
    return {"verdict": "undecidable", "strength": STRENGTH_WEAK,
            "detail": ("两侧含文字，无法机器判定 —— 请人工复核，"
                       "或给出可回代的纯算术等式（self_check）")}


def gate_export_items(items: list[dict]) -> list[str]:
    """练习卷导出前的诚实门禁：**weak 不许冒充 strong**。

    规则：条目声称 verified=True 时，必须携带答案层的强验证证据 ——
        * strength ∈ {exact, numeric}（由 zx_practice_verify 产出），或
        * self_check 等式当场回代成立。
    只有结构门禁（check_practice 的题型/知识点）通过、答案层没验证过的，
    一律拒绝以 verified=True 出卷 —— 要么去验证，要么如实标 False。
    返回错误字符串列表（空 = 全部放行）。
    """
    errors: list[str] = []
    for it in items:
        gen_id = it.get("gen_id", "?")
        if not it.get("verified"):
            continue
        strength = it.get("strength")
        if strength in STRONG:
            continue
        sc = it.get("self_check") or ""
        if sc:
            eq = check_equation(sc)
            if eq["verdict"] == "match":
                continue
            if eq["verdict"] == "mismatch":
                errors.append(
                    f"{gen_id}: self_check 回代不成立（{eq['detail']}）——"
                    "答案大概率错了，禁止以 verified=True 出卷")
                continue
        errors.append(
            f"{gen_id}: 声称 verified=True 但答案层验证强度为 "
            f"{strength or '未验证（仅结构门禁）'} —— weak 不许冒充 strong。"
            "先用 zx_practice_verify 做答案层验证（exact/numeric）"
            "或提供能回代成立的 self_check，否则把 verified 改为 false")
    return errors
