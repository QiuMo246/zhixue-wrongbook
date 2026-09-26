"""接口结构指纹与改版预警（包二，移植自 qwen 分支的设计）。

问题：通道 B 绑死第三方库字段、通道 C 是自己逆出来的接口（参数标注
VERIFY），平台悄悄改返回结构时，现状是**静默采回错数据写库** ——
最危险的失败模式：不报错，只是悄悄变错。

qwen 分支的做法（src/collect/fingerprint.ts）：每个关键接口的响应
算一份「结构指纹」—— 只看字段路径形状，不看内容值；与库里的基线比对，
漂移就**宁可不解析**，把「静默错数据」变成「显式报警」。

这里的对应实现：
    shape_signature(data)  递归提取 `路径:类型` 签名（值不进指纹，
                           同样的数据结构换数字/换文本，指纹不变）
    check_response(...)    由 ZhixueWebClient._get 在每个响应后调用：
                           首次见到该端点 → 登记基线（如实标注是首次）；
                           与基线一致 → 放行；
                           漂移 → 抛 ZxError(fingerprint_drift)，
                           绝不把可疑数据交给上层写库。

为什么指纹不含值：平台改版改的是**结构**（字段改名、层级移动、类型变化），
值的波动（分数、日期、题干）每天都不一样，混进来指纹天天漂，等于没有指纹。
"""

from __future__ import annotations

import os

from core.errors import CODE_FINGERPRINT_DRIFT, ZxError

# 测试 / 离线验收需要确定性：设 ZX_FINGERPRINT_OFF=1 时 check_response
# 只登记不比对（e2e 用的临时库没有基线，逐次联网调用会误报漂移）。
def enabled() -> bool:
    return os.environ.get("ZX_FINGERPRINT_OFF", "") != "1"


def _type_name(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "num"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "obj"
    return type(v).__name__


def shape_signature(data, _prefix: str = "$") -> list[str]:
    """递归提取 `路径:类型` 列表（排序后返回）。

    列表取首个元素的形状（空列表记为 `[]:list`）；列表内多态元素
    （第 1 个是对象第 2 个是字符串）只反映首个 —— 平台接口的列表
    都是同质的，多态本身就是改版信号，靠内容层校验兜底。
    """
    sig: set[str] = set()

    def walk(v, prefix):
        if isinstance(v, dict):
            if not v:
                sig.add(f"{prefix}:{{}}")
                return
            for k, item in v.items():
                walk(item, f"{prefix}.{k}")
        elif isinstance(v, list):
            if not v:
                sig.add(f"{prefix}[]:empty")
                return
            walk(v[0], f"{prefix}[]")
        else:
            sig.add(f"{prefix}:{_type_name(v)}")

    walk(data, _prefix)
    return sorted(sig)


def diff(expected: list[str], actual: list[str]) -> dict:
    """基线 vs 实际：新增了哪些字段路径、消失了哪些。"""
    return {
        "added": sorted(set(actual) - set(expected)),
        "removed": sorted(set(expected) - set(actual)),
    }


class FingerprintStore:
    """endpoint_fingerprint 表的读写（由 core.store.Store 建表）。

    单独一个小类而不是塞进 Store：指纹是通道 C（zhixue_web）的基础设施，
    而 Store 的构造参数/迁移逻辑不想被它牵动。
    """

    def __init__(self, conn):
        self.conn = conn
        conn.execute("""
            CREATE TABLE IF NOT EXISTS endpoint_fingerprint (
                endpoint      TEXT PRIMARY KEY,
                signature     TEXT NOT NULL,
                sample_count  INTEGER NOT NULL DEFAULT 1,
                updated_at    TEXT NOT NULL
            )""")

    def baseline(self, endpoint: str) -> list[str] | None:
        row = self.conn.execute(
            "SELECT signature FROM endpoint_fingerprint WHERE endpoint = ?",
            (endpoint,)).fetchone()
        return row[0].split("\n") if row else None

    def register(self, endpoint: str, signature: list[str], now: str) -> None:
        self.conn.execute(
            "INSERT INTO endpoint_fingerprint (endpoint, signature, "
            "sample_count, updated_at) VALUES (?, ?, 1, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET signature = excluded.signature, "
            "sample_count = sample_count + 1, updated_at = excluded.updated_at",
            (endpoint, "\n".join(signature), now))

    def bump(self, endpoint: str, now: str) -> None:
        self.conn.execute(
            "UPDATE endpoint_fingerprint SET sample_count = sample_count + 1, "
            "updated_at = ? WHERE endpoint = ?", (now, endpoint))


def check_response(store_fp: FingerprintStore | None, endpoint: str,
                   data, now: str) -> dict:
    """通道 C 每个响应过一遍：登记基线 / 校验漂移。

    返回 {"status": "baseline_registered" | "ok"}；
    漂移时抛 ZxError(fingerprint_drift) —— 上层把可疑响应拦下，
    绝不让它继续流向解析和写库。
    """
    actual = shape_signature(data)
    if store_fp is None or not enabled():
        return {"status": "ok", "signature": actual}
    expected = store_fp.baseline(endpoint)
    if expected is None:
        store_fp.register(endpoint, actual, now)
        return {"status": "baseline_registered", "signature": actual}
    if expected == actual:
        store_fp.bump(endpoint, now)
        return {"status": "ok", "signature": actual}
    d = diff(expected, actual)
    raise ZxError(
        f"智学网接口 {endpoint} 的返回结构发生了变化"
        f"（新增字段路径 {len(d['added'])} 个 / 消失 {len(d['removed'])} 个）。"
        "这通常是平台改版 —— 继续解析可能采回错数据，已按设计拦截。",
        code=CODE_FINGERPRINT_DRIFT,
        missing=[f"接口 {endpoint} 的结构基线核对（基线 {len(expected)} 条 vs "
                 f"实际 {len(actual)} 条）"],
        suggested_action=[
            "不要重试 —— 结构漂移不是网络抖动，重试没有意义",
            "把本条 error 原文发给维护者核对接口改动",
            f"新结构字段路径（新增）：{d['added'][:8]}",
            f"消失的字段路径：{d['removed'][:8]}",
        ])
