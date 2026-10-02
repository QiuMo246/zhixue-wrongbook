"""结构化错误与协商话术（包四，移植自 qwen 分支的 ZxError 设计）。

为什么：`_guard` 此前把一切异常收敛成 `{"ok": false, "error": "<字符串>"}`，
缺什么、下一步该干什么全靠宿主模型自由发挥 —— 这违背本项目
「数据面 / 推理面分离」的第一原则（server.py:1-11）：凡是需要"理解"的活
都不该交给猜。qwen 分支把失败输出当**正式产物**设计：错误码 + 缺什么 +
建议动作，宿主照着 SKILL.md 的话术表跟用户协商，而不是吐堆栈。

向后兼容承诺：`error` 字段仍是人类可读字符串（现有测试与文档都依赖
这个形状），`error_code` / `missing` / `suggested_action` 是**新增的兄弟键**，
不做替换。普通异常不带这三个键，形状与从前完全一致。

错误码清单（协商话术表：skill/zhixue-wrongbook/SKILL.md「错误码协商表」）：
    auto_login_failed          自动登录失败（网络不通 / 密码错 / 风控验证码）
    session_expired            会话失效且没有可用的自动重登手段
    no_safe_storage            没有可用的安全存储后端（拒绝明文是设计）
    dependency_missing         可选依赖未安装（如 openpyxl）
    fingerprint_drift          接口响应结构漂移（包二），宁可不解析
    disclosure_not_confirmed   出网披露未获用户确认（包三），降级仅统计
    practice_gate              生成题未过确定性门禁（包六），改题重来
    no_data                    范围内没有数据（不是错误，是需要先补数据）
    unexpected                 兜底：没归类的不预期异常
"""

from __future__ import annotations

CODE_AUTO_LOGIN_FAILED = "auto_login_failed"
CODE_SESSION_EXPIRED = "session_expired"
CODE_NO_SAFE_STORAGE = "no_safe_storage"
CODE_DEPENDENCY_MISSING = "dependency_missing"
CODE_FINGERPRINT_DRIFT = "fingerprint_drift"
CODE_DISCLOSURE_NOT_CONFIRMED = "disclosure_not_confirmed"
CODE_PRACTICE_GATE = "practice_gate"
CODE_NO_DATA = "no_data"
CODE_UNEXPECTED = "unexpected"


class ZxError(Exception):
    """带结构化协商字段的工具错误。

    `missing`：缺什么（输入、数据、确认、依赖）；
    `suggested_action`：宿主该做什么（按优先级排列，第一条通常是首选）。
    两者都必须是"宿主能直接执行或转述"的具体动作，不许写空话。
    """

    def __init__(self, message: str, *, code: str = CODE_UNEXPECTED,
                 missing: list[str] | None = None,
                 suggested_action: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.missing = list(missing or [])
        self.suggested_action = list(suggested_action or [])

    def to_payload(self) -> dict:
        """新增的兄弟键，与 `error` 字符串并存。"""
        return {"error_code": self.code,
                "missing": self.missing,
                "suggested_action": self.suggested_action}


def error_payload(exc: Exception) -> dict:
    """给 `_guard` / 内联 except 用的辅助：ZxError → 协商字段，普通异常 → {}。

    用法：`{"ok": False, "error": str(exc), **_error_payload(exc)}`
    —— 普通异常展开为空，JSON 形状与历史版本逐字节一致。
    """
    if isinstance(exc, ZxError):
        return exc.to_payload()
    return {}
