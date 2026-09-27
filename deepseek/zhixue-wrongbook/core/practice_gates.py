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

import ast
import math
import re

STRENGTH_EXACT = "exact"
STRENGTH_NUMERIC = "numeric"
STRENGTH_WEAK = "weak"
STRENGTH_UNDECIDABLE = "undecidable"

STRONG = {STRENGTH_EXACT, STRENGTH_NUMERIC}

# 允许出现在回代等式里的字符在 eval_expr 内用 fullmatch 白名单锁定；
# 其余符号（字母/汉字/下划线…）一律 undecidable，不猜。

# 数值预算（2026-09-27 修的真实 DoS）：self_check 是宿主可控输入，而 MCP 是
# stdio 单线程 —— 一次 `9^9^9=0` 的求值曾实测要耗 30 分钟量级，整个 server
# 被卡死。字符白名单只锁「能写什么」，锁不住「数值多大」，所以这里改用
# AST 白名单求值器，并对指数/中间结果设硬预算，超限一律拒判（undecidable，
# 不是报错 —— 拒判是诚实，报错会把整卷导出炸掉）。
_MAX_RESULT = 1e15        # 任何中间/最终结果的绝对值上限（与历史口径一致）
_MAX_EXPONENT = 100       # 幂运算指数上限（学校算术不会碰到）


class _ExprTooCostly(Exception):
    """表达式超出数值预算 —— 求值放弃，按 undecidable 处理。"""


def _ast_eval(node) -> float:
    """AST 白名单求值：只认 Constant 数字与 +-*/^ 四则，逐层检查预算。"""
    if isinstance(node, ast.Expression):
        return _ast_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):
        v = float(node.value)
        if not math.isfinite(v) or abs(v) > _MAX_RESULT:
            raise _ExprTooCostly
        return v
    if isinstance(node, ast.BinOp):
        left, right = _ast_eval(node.left), _ast_eval(node.right)
        if isinstance(node.op, ast.Pow):
            # 指数本身先设上限；底数大时进一步收紧，杜绝 9^9^7 这类
            # 「指数每 +1 耗时 ×30」的爆炸链（实测见优化.md #5）
            if abs(right) > _MAX_EXPONENT or (abs(left) > 1 and math.log10(abs(left)) * abs(right) > 15):
                raise _ExprTooCostly
            v = left ** right
        elif isinstance(node.op, ast.Add):
            v = left + right
        elif isinstance(node.op, ast.Sub):
            v = left - right
        elif isinstance(node.op, ast.Mult):
            v = left * right
        elif isinstance(node.op, ast.Div):
            if right == 0:
                raise _ExprTooCostly
            v = left / right
        elif isinstance(node.op, ast.Mod):
            if right == 0:
                raise _ExprTooCostly
            v = math.fmod(left, right)
        else:
            raise _ExprTooCostly
        if isinstance(v, complex) or not math.isfinite(v) or abs(v) > _MAX_RESULT:
            raise _ExprTooCostly
        return float(v)
    if isinstance(node, ast.UnaryOp):
        v = _ast_eval(node.operand)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return v
        raise _ExprTooCostly
    raise _ExprTooCostly


def eval_expr(expr: str) -> float | None:
    """白名单算术求值器：只认 数字 . + - * / ( ) ^ % 空格。

    返回数值；含任何白名单之外的字符（字母、汉字、下划线、连续符号）
    一律返回 None —— **绝不 eval**，这是安全边界不是性能取舍。
    `=` 出现在表达式里由调用方先拆分（本函数只算单边）。

    2026-09-27：从 eval(字符串) 改为 AST 白名单求值。原实现的字符白名单
    挡得住代码注入，挡不住 `9**9**9` 这种合法算术的指数爆炸（两轮实测
    分钟级到 30 分钟量级）；AST 版对指数与中间结果设硬预算，超限返回
    None（= undecidable），深嵌套括号导致的递归爆炸同样兜住。
    """
    s = (expr or "").replace("^", "**").replace("×", "*").replace("÷", "/")
    s = s.replace("%", "/100")
    s = re.sub(r"\s+", "", s)
    if not s or not re.fullmatch(r"[0-9.+\-*/()]+", s):
        return None
    try:
        tree = ast.parse(s, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    try:
        return _ast_eval(tree)
    except (_ExprTooCostly, OverflowError, ValueError, ZeroDivisionError,
            RecursionError, TypeError):
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
        * self_check 等式当场回代成立，或
        * answer + standard_answer（+可选 self_check）能当场重算出强验证。
    **不信任条目自带的 strength 字段**（2026-09-27 修的真实漏洞：宿主只要
    在 items 里写 strength="numeric" 就能空手过闸；甚至 zx_practice_verify
    验证失败返回的也是 strength=numeric —— 一次真失败产出的令牌恰恰能
    解锁这道门）。门禁内当场重算，声称的 strength 只是个说法。
    只有结构门禁（check_practice 的题型/知识点）通过、答案层没验证过的，
    一律拒绝以 verified=True 出卷 —— 要么去验证，要么如实标 False。
    返回错误字符串列表（空 = 全部放行）。
    """
    errors: list[str] = []
    for it in items:
        gen_id = it.get("gen_id", "?")
        if not it.get("verified"):
            continue
        claimed = it.get("strength")
        sc = it.get("self_check") or ""
        ans = it.get("answer") or it.get("generated_answer") or ""
        std = it.get("standard_answer") or it.get("standard") or ""
        if sc:
            eq = check_equation(sc)
            if eq["verdict"] == "match":
                continue
            if eq["verdict"] == "mismatch":
                errors.append(
                    f"{gen_id}: self_check 回代不成立（{eq['detail']}）——"
                    "答案大概率错了，禁止以 verified=True 出卷")
                continue
        if claimed in STRONG or ans or std:
            # 声称强验证 / 带了可比对原料 → 门禁内重跑，不认自报的档位
            res = verify_answer(ans, std, "")
            if res["verdict"] in ("match", "numeric_match"):
                continue
            if res["verdict"] == "mismatch":
                errors.append(
                    f"{gen_id}: 门禁内重跑答案验证不成立（{res['detail']}）——"
                    "禁止以 verified=True 出卷")
                continue
            errors.append(
                f"{gen_id}: 声称 verified=True（strength={claimed or '未给'}）"
                "但门禁内复算不出强验证 —— 条目没带 answer/standard_answer/"
                "self_check 原料，或原料验证不出 exact/numeric。"
                "先用 zx_practice_verify 验证并把原料带进条目，"
                "否则把 verified 改为 false")
            continue
        errors.append(
            f"{gen_id}: 声称 verified=True 但答案层验证强度为 "
            f"{claimed or '未验证（仅结构门禁）'} —— weak 不许冒充 strong。"
            "先用 zx_practice_verify 做答案层验证（exact/numeric）"
            "或提供能回代成立的 self_check，否则把 verified 改为 false")
    return errors
