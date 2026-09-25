"""通道 B：现成库 zhixuewang 封装（主路径）。

本文件的所有字段映射都来自 **对库源码的实读**，
证据见 `docs/字段核实报告.md`（每条都带 文件:行号）。
不照文档猜字段——文档里已经有 3 处与源码不符，本文件按源码写。

关键修正（相对架构文档）：
  1. Cookie **不把原始字符串交给库**，自己稳健解析成 dict 再传
     （库的字符串解析对 ";" 分隔符和值里的 "=" 都不健壮）
  2. `difficulty` 是 int，刻度未知 → 交给 config 决定是否归一化
  3. `standard_answer` 注释标为「网址」→ 检测并回退到 answer_html
  4. `ErrorBookTopic.subject_name` 实际是试卷名 → 学科名以 get_subjects 为准
  5. `get_errorbook` 第二参数 paperId/topicSetId 存疑 → 失败自动重试
"""

from __future__ import annotations

import importlib.metadata
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from adapters.parsers.normalize import (download_images, make_id,
                                        normalize_question)
from adapters.parsers.zhixue_export import (ANSWER_TYPE_MEANING,
                                            qtype_from_answer_type)
from core.config import get_config
from core.models import WrongQuestion
from core.store import Store

URL_RE = re.compile(r"^https?://", re.I)


def _as_url_list(raw: Any) -> list[str]:
    """把「可能是 JSON 字符串的图片字段」统一成 URL 列表。

    为什么需要（2026-09-24 实测真实数据才发现）：
    `ErrorBookTopic.image_answer` 的类型标注写的是 `List[str]`，
    但库只是把接口的 `imageAnswer` 原样透传（student.py:844），
    而接口返回的其实是**JSON 编码的字符串**，形如：

        '["https://zhixue-sc.oss-.../AfterCorrect_xxx.jpg?Expires=...&Signature=..."]'

    原来的写法是「是 str 就包成单元素列表」，于是得到
    `['["https://..."]']` —— 带着方括号和引号去 `requests.get`，必然失败。
    后果很严重：**学生手写作答图片一张都没存下来**，
    而手写作答正是错因分析最关键的证据。

    另外这些 OSS 链接带 `Expires` + `Signature` 签名，**会过期**，
    所以必须尽快下载到本地，只存 URL 等于没存。
    """
    if raw is None or raw == "":
        return []
    items: list[Any]
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        s = str(raw).strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                parsed = json.loads(s)
                items = list(parsed) if isinstance(parsed, list) else [s]
            except (ValueError, TypeError):
                items = [s]
        else:
            items = [s]

    out: list[str] = []
    for it in items:
        if not it:
            continue
        t = str(it).strip()
        # 列表元素本身还可能是 JSON 字符串（多套了一层），再剥一次
        if t.startswith("[") and t.endswith("]"):
            try:
                parsed = json.loads(t)
                if isinstance(parsed, list):
                    out.extend(str(x).strip() for x in parsed if x)
                    continue
            except (ValueError, TypeError):
                pass
        out.append(t)
    return out

# 库版本会写进 source_version。接口一变，新旧数据可比性受影响，
# 所以这个字段必须记录「这条数据是哪版库抓的」。
try:
    LIB_VERSION = f"zhixuewang=={importlib.metadata.version('zhixuewang')}"
except Exception:
    LIB_VERSION = "zhixuewang==unknown"

SOURCE_VERSION = f"{LIB_VERSION}+adapter-b1"

# 智学网接口返回「暂时未收集到试题信息」时的错误码（见 student.py:830 注释）
ERR_NO_TOPIC = 40217


# ---------------------------------------------------------------------------
# Cookie 处理
# ---------------------------------------------------------------------------
class CookieError(ValueError):
    pass


def parse_cookie_string(raw: str) -> dict[str, str]:
    """把浏览器复制的 Cookie 字符串稳健地解析成 dict。

    为什么不直接用库的解析（account.py:56-58）：
      - 它按 "; "（分号+空格）切分，没有空格就整串当一个键
      - 它用 dict(item.split("="))，值里含 "=" 会抛 ValueError
    这里按 ";" 切分、按**第一个** "=" 分割键值，两种写法都能吃。
    """
    raw = (raw or "").strip()
    if not raw:
        raise CookieError("Cookie 为空")
    raw = raw.strip().strip(";")
    out: dict[str, str] = {}
    bad = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            bad.append(part)
            continue
        k, _, v = part.partition("=")   # 只切第一个 "="，值里的 "=" 保留
        k, v = k.strip(), v.strip()
        if k:
            out[k] = v
    if not out:
        raise CookieError(
            "没能从这段文本里解析出任何 Cookie 键值对。"
            "请确认复制的是「浏览器开发者工具 → 网络 → 请求头 → Cookie」那一整行，"
            "形如 token=xxx; userName=xxx; loginUserName=xxx; ...")
    return out


def check_cookie_dict(d: dict[str, str]) -> list[str]:
    """返回警告列表。缺 loginUserName 是硬错误（库会 KeyError）。"""
    warnings = []
    if "loginUserName" not in d:
        raise CookieError(
            "Cookie 里缺少 `loginUserName` 字段，zhixuewang 库会因此直接报错"
            "（account.py:59）。请重新完整复制 Cookie。")
    for key in ("token", "userName"):
        if key not in d:
            warnings.append(f"Cookie 里没有 `{key}`，可能复制不完整")
    return warnings


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------
def login(raw_cookie: str) -> Any:
    """用 Cookie 登录，返回 zhixuewang 的 Account 对象。"""
    from zhixuewang import login_cookie
    cookie_dict = parse_cookie_string(raw_cookie)
    check_cookie_dict(cookie_dict)
    return login_cookie(cookie_dict)   # 传 dict，绕过库的脆弱字符串解析


def to_student(account: Any):
    """把 Account 转成学生账号；不是学生账号时给人话提示。"""
    role = getattr(account, "role", None)
    role_name = getattr(role, "value", str(role))
    if role_name and role_name != "student":
        raise PermissionError(
            f"这个 Cookie 对应的账号角色是「{role_name}」，不是学生账号。"
            "本工具只支持学生账号（任务书第 4 节的约束）。")
    return account.to_student()


# ---------------------------------------------------------------------------
# 考试 / 学科
# ---------------------------------------------------------------------------
def _exam_date(exam: Any) -> tuple[str | None, bool]:
    """考试日期。库的 Exam 没有日期字段（models.py:321-336），
    只能用 create_time（接口的 examCreateDateTime，student.py:261）近似。
    返回 (日期字符串, 是否是近似值)。
    """
    ct = getattr(exam, "create_time", None)
    if not ct:
        return None, True
    try:
        return datetime.fromtimestamp(float(ct) / 1000 if float(ct) > 1e11 else float(ct),
                                     tz=timezone.utc).strftime("%Y-%m-%d"), True
    except (TypeError, ValueError, OSError):
        return None, True


def list_exams(student: Any, limit: int | None = None) -> list[dict]:
    """考试列表。每项含 id / name / grade_code / is_final / date / date_is_approx。"""
    exams = list(student.get_exams() or [])
    out = []
    for e in exams[:limit] if limit else exams:
        date, approx = _exam_date(e)
        out.append({"id": e.id, "name": e.name,
                    "grade_code": getattr(e, "grade_code", ""),
                    "is_final": bool(getattr(e, "is_final", False)),
                    "date": date, "date_is_approx": approx,
                    "create_time": getattr(e, "create_time", None)})
    return out


def list_subjects(student: Any, exam: Any) -> list[dict]:
    """学科列表。注意 Subject.id 来自接口的 paperId（student.py:358），
    正好是 get_errorbook 请求里 paperId 参数需要的值。"""
    subs = list(student.get_subjects(exam) or [])
    return [{"name": s.name, "paper_id": s.id, "code": getattr(s, "code", ""),
             "standard_score": getattr(s, "standard_score", 0)} for s in subs]


def _latest_exam_topic_set_ids(student: Any) -> tuple[str | None, dict[str, str]]:
    """从 get_latest_exam() 里取「学科名 → topicSetId」。

    为什么需要这个：get_latest_exam 构造 Subject 时用的是 topicSetId
    （student.py:248），而 get_subjects 用的是 paperId（student.py:358）。
    两者都可能被当成 get_errorbook 的第二个参数，源码里无法判定哪个对
    （形参叫 topic_set_id，请求键名叫 paperId）。所以留一条重试路径。

    **返回 (最新考试的 id, 映射)** —— 这个 exam_id 很关键：
    topicSetId 是「某场考试的某学科」的标识，**不能跨考试用**。
    只有正在同步的考试就是最新考试时，这条重试路径才有意义。
    否则会拿 A 考试的 topicSetId 去查 B 考试，得到一个看似成功实则错乱的结果。
    """
    try:
        latest = student.get_latest_exam()
        return (latest.id,
                {s.name: s.id for s in (getattr(latest, "subjects", []) or [])})
    except Exception:
        return None, {}


# ---------------------------------------------------------------------------
# 错题本
# ---------------------------------------------------------------------------
def _looks_like_url(s: str | None) -> bool:
    return bool(s and URL_RE.match(s.strip()))


def fetch_errorbook_raw(student: Any, exam: Any, subject: dict,
                        topic_set_id: str | None = None) -> tuple[list[Any], str]:
    """调用 get_errorbook，返回 (错题列表, 实际生效的参数名)。

    第二个参数先按 paperId 试；报 40217 时用 topicSetId 再试一次。
    生效的是哪个会写进同步报告——这是可验证的降级，不是猜测。
    """
    try:
        return list(student.get_errorbook(exam.id, subject["paper_id"]) or []), "paperId"
    except Exception as exc:
        if topic_set_id and _is_no_topic_error(exc):
            return (list(student.get_errorbook(exam.id, topic_set_id) or []),
                    "topicSetId(重试)")
        raise


def _is_no_topic_error(exc: Exception) -> bool:
    """库在 errorCode != 0 时抛裸 Exception，data 是 dict（student.py:831）。"""
    data = getattr(exc, "args", (None,))
    if data and isinstance(data[0], dict):
        return data[0].get("errorCode") == ERR_NO_TOPIC
    return "40217" in str(exc) or "暂时未收集到试题信息" in str(exc)


def topic_to_raw(topic: Any, subject_name: str, exam: Any,
                 grade: str | None, images_dir: Path,
                 images_prefix: str, download: bool = True,
                 config=None) -> tuple[dict, dict]:
    """ErrorBookTopic → 通道内部 raw dict。返回 (raw, notes)。

    notes 记录「这题有哪些数据问题」，会汇总进同步报告。
    """
    config = config or get_config()
    notes: dict[str, Any] = {}

    # --- 题干 ---
    stem_html = getattr(topic, "content_html", "") or ""
    stem_imgs = _as_url_list(getattr(topic, "topic_img_url", ""))
    images: list[str] = []
    if stem_imgs:
        # topic_img_url 注释是「好看的题目」，多半是整题的渲染图
        if download:
            ok, failed = download_images(stem_imgs, images_dir,
                                         f"{images_prefix}_stem")
            images.extend(ok)
            if failed:
                notes.setdefault("image_failed", []).extend(failed)
        else:
            images.extend(stem_imgs)

    # --- 学生作答 ---
    # ⚠ image_answer 实测是 JSON 编码的字符串（不是标注的 List[str]），
    #   必须先用 _as_url_list 拆开，否则下载必失败、作答图全丢。
    ans_imgs = _as_url_list(getattr(topic, "image_answer", None))
    student_images: list[str] = []
    if ans_imgs:
        if download:
            ok, failed = download_images(ans_imgs, images_dir,
                                         f"{images_prefix}_ans")
            student_images.extend(ok)
            if failed:
                notes.setdefault("image_failed", []).extend(failed)
        else:
            student_images.extend(ans_imgs)
    # 这些链接带 Expires/Signature 会过期，一张都没下下来时必须显式报出来
    if ans_imgs and download and not student_images:
        notes["student_images_download_failed"] = ans_imgs

    # --- 标准答案：standard_answer 的注释写的是「网址」，必须防 ---
    raw_standard = getattr(topic, "standard_answer", "") or ""
    answer_html = getattr(topic, "answer_html", "") or ""
    if _looks_like_url(raw_standard):
        # 文档假设它是文本，源码注释说是网址。以实际内容为准：
        # 记下 URL 供参考，正文改用 answer_html。
        standard = answer_html or None
        notes["standard_answer_is_url"] = raw_standard
    else:
        standard = raw_standard or answer_html or None

    # --- 难度：int，刻度未知 ---
    diff_raw = getattr(topic, "difficulty", None)
    difficulty, diff_scale = config.normalize_difficulty(diff_raw)
    if diff_scale == "unknown" and diff_raw is not None:
        notes["difficulty_scale_unknown"] = diff_raw

    # --- 题型：answer_type 语义已实测确认（见 qtype_from_answer_type）---
    answer_type = getattr(topic, "answer_type", "")
    qtype = qtype_from_answer_type(answer_type, stem_html, standard or "")
    notes.setdefault("answer_type_seen", answer_type)
    meaning = ANSWER_TYPE_MEANING.get(str(answer_type).strip().lower())
    if meaning:
        notes.setdefault("answer_type_decoded", meaning)

    raw = {
        "subject": subject_name,
        "exam_name": exam.name,
        "exam_date": _exam_date(exam)[0],
        "grade": grade,
        "stem_html": stem_html,
        "images": images,
        "qtype": qtype,
        "standard": standard,
        "analysis_html": getattr(topic, "analysis_html", "") or None,
        "student_text": None,   # 库未暴露客观题学生作答文本（见核实报告 §5.3）
        "student_images": student_images,
        "difficulty": difficulty,
        "difficulty_scale": diff_scale,
        "class_score_rate": _safe_float(getattr(topic, "class_score_rate", None)),
        "score_got": _safe_float(getattr(topic, "score", None)),
        "score_full": _safe_float(getattr(topic, "standard_score", None)),
    }
    if _looks_like_url(raw_standard):
        raw["standard_answer_url"] = raw_standard
    return raw, notes


def _safe_float(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 同步入口
# ---------------------------------------------------------------------------
def sync(store: Store, raw_cookie: str, subjects: list[str] | None = None,
         max_exams: int | None = None, exam_ids: list[str] | None = None,
         download: bool | None = None) -> dict:
    """拉取错题并入库。**这是全项目唯一联网 + 用会话的写操作。**

    subjects: 只同步这些学科（按名称匹配），None = 全部
    exam_ids: 只同步这些考试 id，None = 最近的 max_exams 场
    """
    config = get_config()
    max_exams = max_exams or int(config["sync"]["max_exams"])
    download = config["sync"]["download_images"] if download is None else download
    images_dir = config.path("images_dir")

    account = login(raw_cookie)
    student = to_student(account)

    exams = list_exams(student, limit=max_exams)
    if exam_ids:
        exams = [e for e in exams if e["id"] in set(exam_ids)]

    latest_exam_id, topic_set_ids = _latest_exam_topic_set_ids(student)

    report: dict[str, Any] = {
        "channel": "api", "source_version": SOURCE_VERSION,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "exams_scanned": 0, "subjects_scanned": 0,
        "added": 0, "updated": 0, "failed": 0, "skipped_exams": [],
        "per_subject": [], "notes": [], "errors": [],
        "download_images": download,
    }

    for exam in exams:
        report["exams_scanned"] += 1
        try:
            exam_obj = student.get_exam(exam["id"])
        except Exception as exc:
            report["errors"].append({"exam": exam["name"], "stage": "get_exam",
                                     "error": f"{type(exc).__name__}: {exc}"})
            continue
        if exam_obj is None:
            report["skipped_exams"].append(
                {"exam": exam["name"], "reason": "get_exam 返回 None"})
            continue

        try:
            subs = list_subjects(student, exam_obj)
        except Exception as exc:
            report["errors"].append({"exam": exam["name"], "stage": "get_subjects",
                                     "error": f"{type(exc).__name__}: {exc}"})
            continue

        for sub in subs:
            if subjects and sub["name"] not in subjects:
                continue
            report["subjects_scanned"] += 1
            entry = {"exam": exam["name"], "subject": sub["name"],
                     "count": 0, "param_used": None, "error": None}
            log_id = store.log_sync_start("api", sub["name"], exam["name"])
            try:
                # 只有「正在同步的考试 == 最新考试」时才用 topicSetId 兜底，
                # 因为 topicSetId 是考试级的，跨考试用会得到错乱结果。
                fallback = (topic_set_ids.get(sub["name"])
                            if exam["id"] == latest_exam_id else None)
                topics, used_param = fetch_errorbook_raw(
                    student, exam_obj, sub, topic_set_id=fallback)
                entry["count"] = len(topics)
                entry["param_used"] = used_param
                if used_param != "paperId":
                    report["notes"].append(
                        {"exam": exam["name"], "subject": sub["name"],
                         "param_note": f"paperId 失败，改用 {used_param} 才通——"
                                       f"说明 get_errorbook 的第二个参数是 topicSetId"})
                for i, t in enumerate(topics, 1):
                    prefix = f"{exam['id'][:8]}_{sub['name']}_{i:03d}"
                    raw, notes = topic_to_raw(
                        t, sub["name"], exam_obj, exam.get("grade_code"),
                        images_dir, prefix, download=download, config=config)
                    q: WrongQuestion = normalize_question(
                        raw, source="api", source_version=SOURCE_VERSION, seq=i)
                    try:
                        res = store.upsert(q)
                    except Exception as exc:
                        report["failed"] += 1
                        report["errors"].append(
                            {"exam": exam["name"], "subject": sub["name"],
                             "topic": getattr(t, "dis_title_number", i),
                             "error": f"入库失败 {type(exc).__name__}: {exc}"})
                        continue
                    if res == "added":
                        report["added"] += 1
                    else:
                        report["updated"] += 1
                    if notes:
                        report["notes"].append(
                            {"exam": exam["name"], "subject": sub["name"],
                             "no": getattr(t, "dis_title_number", i), **notes})
                store.log_sync_end(log_id, added=entry["count"], failed=0)
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                if _is_no_topic_error(exc):
                    entry["error"] = ("平台返回 40217「暂时未收集到试题信息」——"
                                      "该场考试该学科可能没有错题数据，或权限不足")
                else:
                    entry["error"] = msg
                    report["errors"].append(
                        {"exam": exam["name"], "subject": sub["name"],
                         "stage": "get_errorbook", "error": msg})
                store.log_sync_end(log_id, error=entry["error"])
            report["per_subject"].append(entry)

    report["ended_at"] = datetime.now(timezone.utc).isoformat()
    report["difficulty_scale"] = config.difficulty_scale
    report["difficulty_scale_verified"] = config.difficulty_is_verified
    report["warnings"] = []
    if not config.difficulty_is_verified:
        report["warnings"].append(
            "难度刻度未核实（config.yaml → difficulty.scale = unknown），"
            "难度闸门本次降级为软参考。跑 tools/verify_p0.py 看真实取值范围后填上。"
        )
    # id 撞车属于「make_id 没能保证唯一」的信号，绝不能吞掉。
    for fb in getattr(store, "id_fallbacks", []):
        report["notes"].append({"id_collision": fb})
    if getattr(store, "id_fallbacks", None):
        report["warnings"].append(
            f"{len(store.id_fallbacks)} 道题的 id 与库内已有记录撞车，已自动改用"
            "带指纹后缀的 id。这说明 make_id 的去重维度不够，请把上面的 "
            "id_collision 报出来排查。"
        )
    # 指纹过期检测：提取逻辑变过的话，老行的指纹跟重算结果对不上，
    # 再同步会整库重复入库。必须提前说，不能等库脏了才发现。
    try:
        stale = store.stale_fingerprint_count()
    except Exception:
        stale = 0
    if stale:
        report["warnings"].append(
            f"⚠ 库里有 {stale} 道题的指纹与当前提取逻辑算出的不一致 —— "
            "本次同步会把它们当成新题**重复入库**。"
            "建议先清空再重新同步：zx_purge(confirm=true) 然后重新 zx_sync。"
        )
    return report
