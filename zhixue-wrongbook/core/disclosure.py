"""出网披露清单与持久授权（移植自 qwen 分支 privacy/disclosure.ts 的设计）。

deepseek 侧原本只有 `zx_diagnosis(disclosure_confirmed=true)` 这道**无状态**
门禁：模型每次自己传一个布尔，系统既不记录用户到底同意了「哪些字段出境」，
也不在下次调用时复用。qwen 的解法把它升级成三件事，本模块照搬：

  1. **逐字段披露清单**（MANIFESTS）：不再是一句「题面会出境」，而是把
     会离开本机的字段一条条列清楚（题干 / 标准答案 / 学生作答 / 图片……），
     连「已知做不到、需人工兜底」的部分（limitations）也如实写进清单，
     而不是藏在注释里。
  2. **持久授权 + 清单变更即失效**（get_consent 的 manifest_stale）：授权是
     对着**某一份清单**给的，存进 consent 表的是用户当初批准的那份快照。
     清单一旦增删字段，旧同意不再覆盖新内容 —— 等同未决，必须重新征求。
  3. **降级是代码路径**（require_consent 的返回值）：用户拒绝 → 该能力降级为
     「仅统计、不解释」，这是 require_consent 返回的结构，不是提示词约定。

诚实边界（enforced 字段）：并非每个 scope 都设了硬门禁。
  * analysis —— 在 zx_diagnosis 处**强制执行**（未授权不返回样题原文）。
  * vlm_ocr / export —— 目前**仅告知**：get_questions / zx_export_* 按既有
    设计直接返回原文与图片路径（「分析必须读题」），不设阻断，以免破坏其
    契约。清单照样列出、照样可授权，但 `enforced=false` 如实标明它不拦截 ——
    一个不拦截的门禁若假装拦截，比没有门禁更糟。
"""

from __future__ import annotations

import json

from core.errors import CODE_DISCLOSURE_NOT_CONFIRMED

# ---------------------------------------------------------------------------
# 逐字段披露清单：每个 scope = 一类出网行为。
# fields 逐条列出「会离开本机的内容」；limitations 写「已知做不到、需人工兜底」
# 的部分；on_decline 写「用户拒绝后降级成什么形态」。
# ---------------------------------------------------------------------------
MANIFESTS: dict[str, dict] = {
    "analysis": {
        "scope": "analysis",
        "title": "错因分析与知识点标注（样题原文送宿主模型）",
        "receiver": "你所使用的 AI 编程助手接的云端模型服务（非本项目控制）",
        "enforced": True,
        "fields": [
            {"field": "题干文本 stem_text",
             "note": "出境副本已按 redact.py 前置脱敏，高置信 PII 换成稳定占位符"},
            {"field": "标准答案 standard_answer", "note": "仅当平台/用户提供时存在"},
            {"field": "解析 analysis", "note": "题面附带的讲解原文"},
            {"field": "学生作答 student_answer", "note": "逐字引用作为错因证据"},
            {"field": "考试名 exam_name", "note": "可能含学校/年级/班级字样"},
        ],
        "limitations": [
            "redact.py 的模式识别是尽力而为：没命中 ≠ 没有个人信息；中文姓名"
            "无词表无法可靠识别，需在 config 的 student_names 里显式登记才打码",
            "模型上下文的留存策略由宿主服务决定，本项目无法约束",
        ],
        "on_decline": ("降级为仅统计、不解释：zx_diagnosis 仍可用（stats_only=true，"
                       "纯本地聚合知识点掌握度与错因分布），但不返回样题原文、"
                       "不产生逐题错因标签"),
    },
    "vlm_ocr": {
        "scope": "vlm_ocr",
        "title": "原卷与手写作答图片读图（送宿主视觉模型）",
        "receiver": "宿主侧调用的视觉模型服务",
        "enforced": False,
        "fields": [
            {"field": "题目/原卷图片", "note": "落盘前已由 core/strip.py 剥掉 EXIF/GPS"},
            {"field": "学生手写作答图片", "note": "含笔迹，敏感度最高"},
        ],
        "limitations": [
            "人脸检测与区域打码尚未实现：含人像的图片请勿走此路径，需用户自行确认",
            "图片内的手写姓名无法由文本正则覆盖，需人工在提交前涂改",
            "本 scope 目前不设硬门禁：get_questions 按设计直接返回图片本地路径",
        ],
        "on_decline": ("改用结构化文本录入（手打题干/作答），或只做不含图片的统计诊断"),
    },
    "export": {
        "scope": "export",
        "title": "导出练习卷 / 错题本文件（含题面原文）",
        "receiver": "写成本地文件；文件随后是否外传由用户决定",
        "enforced": False,
        "fields": [
            {"field": "题干 / 答案 / 解析原文", "note": "导出文件正文"},
            {"field": "考试名 / 学科", "note": "文件抬头与分组"},
        ],
        "limitations": [
            "本 scope 目前不设硬门禁：zx_export_* 按设计直接产出含原文的文件",
            "导出文件本身不再二次脱敏 —— 它是给用户看的成品，不是出境副本",
        ],
        "on_decline": "不导出，或仅导出不含题面原文的统计摘要",
    },
}

SCOPES = list(MANIFESTS.keys())


def manifest_text(scope: str) -> str:
    """清单的规范化 JSON —— 存进 consent 表做「变更即失效」比对的基准。

    sort_keys 保证字段顺序不影响指纹；同一份清单永远得到同一串。
    """
    return json.dumps(MANIFESTS[scope], ensure_ascii=False, sort_keys=True)


def get_consent(store, scope: str) -> dict:
    """返回 {scope, granted, decided_at, manifest_stale, enforced}。

    manifest_stale=True 表示：库里存的授权是对着**旧清单**给的，当前清单已变，
    旧同意不再覆盖 —— 等同未决，require_consent 会要求重新出示。
    """
    enforced = MANIFESTS[scope]["enforced"]
    row = store.get_consent_row(scope)
    if not row:
        return {"scope": scope, "granted": False, "decided_at": None,
                "manifest_stale": False, "enforced": enforced}
    if row.get("manifest_json") != manifest_text(scope):
        return {"scope": scope, "granted": False, "decided_at": None,
                "manifest_stale": True, "enforced": enforced}
    return {"scope": scope, "granted": bool(row.get("granted")),
            "decided_at": row.get("decided_at"), "manifest_stale": False,
            "enforced": enforced}


def record_consent(store, scope: str, granted: bool) -> dict:
    """写入一条授权，快照当前清单。返回写入后的状态。"""
    store.record_consent(scope, granted, manifest_text(scope))
    return get_consent(store, scope)


def require_consent(store, scope: str) -> dict:
    """强制 scope 的授权。返回：
      * {"ok": True}                                  —— 已授权且清单未变
      * {"ok": False, "state": ..., "manifest": ...,
         "error_code": ..., "suggested_action": [...]} —— 未决/已拒/清单已变

    state ∈ {undecided, declined, stale}。调用方（zx_diagnosis）据此决定是
    返回披露清单请用户确认，还是按 on_decline 降级。
    """
    st = get_consent(store, scope)
    if st["granted"]:
        return {"ok": True}
    manifest = MANIFESTS[scope]
    if st["manifest_stale"]:
        state = "stale"
        detail = "披露清单内容与用户当初批准的已不同（新增或改写了字段），旧同意不再覆盖"
    elif st["decided_at"] is None:
        state = "undecided"
        detail = "披露清单尚未向用户出示并取得决定"
    else:
        state = "declined"
        detail = "用户已拒绝该出网范围"
    suggested = ([f"把下面 manifest 的 fields/limitations 原样念给用户，取得是/否后调 "
                  f"zx_consent(scope=\"{scope}\", granted=true/false)"]
                 if state in ("undecided", "stale")
                 else [f"用户已拒绝 {scope} 出网，按 on_decline 继续：{manifest['on_decline']}"])
    return {"ok": False, "state": state, "detail": detail,
            "manifest": manifest,
            "error_code": CODE_DISCLOSURE_NOT_CONFIRMED,
            "suggested_action": suggested}


def consent_summary(store) -> list[dict]:
    """所有 scope 的当前授权状态（zx_consent_manifest 用它给用户看全貌）。"""
    return [get_consent(store, s) for s in SCOPES]
