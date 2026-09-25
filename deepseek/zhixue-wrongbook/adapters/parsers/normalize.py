"""归一化层：三条通道的原始数据 → 统一 WrongQuestion 对象。

三条通道的原始形态完全不同：
  A 官方导出：PDF/doc 抽出来的文本块，字段靠规则识别，可能有缺失
  B 现成库  ：结构化对象，字段名由库决定
  C 自建接口：原始 JSON，字段名由平台决定

归一化的任务就是把这些差异**全部吃掉**，让下游（存储/分析/导出）
只面对一种形状。差异不允许泄漏到 core/ 里去。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from core.models import (AnswerPart, Exam, QuestionPart, Score, WrongQuestion,
                         html_to_text)

ROOT = Path(__file__).resolve().parent.parent.parent

SUBJECT_CODE = {
    "数学": "math", "物理": "phys", "化学": "chem", "英语": "eng",
    "语文": "chin", "生物": "bio", "地理": "geo", "历史": "hist",
    "政治": "poli", "道德与法治": "poli", "科学": "sci",
}


def _exam_tag(exam_name: str, exam_date: str | None) -> str:
    """把「哪一场考试」压成 4 位十六进制，用来把考试维度带进 id。

    为什么必须带：seq 是「每场考试 × 每个学科」内部从 1 重新开始的，
    所以「年份 + 学科 + 序号」根本不足以定位一道题。
    """
    basis = f"{(exam_name or '').strip()}|{(exam_date or '').strip()}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:4]


def make_id(subject: str, exam_name: str, exam_date: str | None,
            seq: int) -> str:
    """生成稳定可读的 id，形如 zx_2026_math_3f2a_0031。

    id 是 questions 表的**主键，必须全局唯一**；去重仍然靠 fingerprint。

    踩过的坑（2026-09-24 真实同步时暴露）：早期版本是
    `zx_<年>_<学科>_<序号>`，漏了考试维度。seq 每场考试都从 1 重来，
    于是 2026 年两场数学考试的第 1 题都算成 `zx_2026_math_0001`，
    第一场入库成功、第二场整批报
    `UNIQUE constraint failed: questions.id`。
    现在补上考试摘要（exam_name + exam_date 的短哈希）。
    """
    year = "0000"
    if exam_date:
        m = re.search(r"(20\d{2})", str(exam_date))
        if m:
            year = m.group(1)
    code = SUBJECT_CODE.get(subject, "misc")
    return f"zx_{year}_{code}_{_exam_tag(exam_name, exam_date)}_{seq:04d}"


def estimate_parse_confidence(*, has_stem: bool, has_standard: bool,
                              has_student: bool, has_analysis: bool,
                              has_score: bool, has_difficulty: bool) -> float:
    """解析置信度：按关键字段的齐备程度加权。

    权重反映「缺了它还能不能做错因分析」：
      题干 0.35 —— 没题干一切免谈
      学生作答 0.25 —— 没有它就不知道学生错在哪
      标准答案 0.20
      解析 0.10
      得分 0.05 / 难度 0.05 —— 缺了只是少个交叉验证信号
    """
    score = 0.0
    score += 0.35 if has_stem else 0.0
    score += 0.25 if has_student else 0.0
    score += 0.20 if has_standard else 0.0
    score += 0.10 if has_analysis else 0.0
    score += 0.05 if has_score else 0.0
    score += 0.05 if has_difficulty else 0.0
    return round(score, 3)


def normalize_question(raw: dict, source: str, source_version: str = "",
                       seq: int = 1,
                       fetched_at: datetime | None = None) -> WrongQuestion:
    """把通道原始 dict 归一化成 WrongQuestion。

    raw 的字段名按「通道内部约定」，见各 adapter 的说明。
    缺失字段一律容忍，但会体现在 parse_confidence 上——
    宁可让置信度低、被统计排除，也不要抛异常把整次同步打断。
    """
    subject = (raw.get("subject") or "未知学科").strip()
    exam_name = (raw.get("exam_name") or "未知考试").strip()
    exam_date = raw.get("exam_date")

    stem_html = raw.get("stem_html") or ""
    images = list(raw.get("images") or [])
    standard = raw.get("standard")
    analysis_html = raw.get("analysis_html")
    student_text = raw.get("student_text")
    student_images = list(raw.get("student_images") or [])
    difficulty = _to_float(raw.get("difficulty"))
    difficulty_scale = raw.get("difficulty_scale") or (
        "0-1" if difficulty is not None and 0.0 <= difficulty <= 1.0 and isinstance(raw.get("difficulty"), float)
        else ("unknown" if difficulty is not None else "unknown"))
    class_score_rate = _to_float(raw.get("class_score_rate"))
    score_got = _to_float(raw.get("score_got"))
    score_full = _to_float(raw.get("score_full"))

    conf = raw.get("parse_confidence")
    if conf is None:
        conf = estimate_parse_confidence(
            has_stem=bool(html_to_text(stem_html) or images),
            has_standard=bool(standard),
            has_student=bool(student_text or student_images),
            has_analysis=bool(analysis_html),
            has_score=score_got is not None and score_full is not None,
            has_difficulty=difficulty is not None,
        )

    return WrongQuestion(
        id=raw.get("id") or make_id(subject, exam_name, exam_date, seq),
        source=source,
        source_version=source_version,
        fetched_at=fetched_at or datetime.now(timezone.utc),
        parse_confidence=float(conf),
        subject=subject,
        grade=raw.get("grade"),
        exam=Exam(name=exam_name, date=exam_date),
        question=QuestionPart(
            stem_html=stem_html,
            images=images,
            type=raw.get("qtype") or "解答题",
            difficulty=difficulty,
            difficulty_scale=difficulty_scale,
            class_score_rate=class_score_rate,
        ),
        answer=AnswerPart(
            student_text=student_text,
            student_images=student_images,
            standard=standard,
            analysis_html=analysis_html,
        ),
        score=Score(got=score_got, full=score_full),
    )


def _to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        # 有些平台返回 "3/8" 或 "0.75" 这类字符串
        if isinstance(v, str) and "/" in v:
            a, _, b = v.partition("/")
            try:
                return float(a) / float(b)
            except (ValueError, ZeroDivisionError):
                return None
        return None


# ---------------------------------------------------------------------------
# 图片落盘（只在同步时调用；MCP 的其他工具都不联网）
# ---------------------------------------------------------------------------
def _file_url_to_path(url: str) -> Path:
    """file:// URL → 本地路径。Windows 上 file:///D:/a.png 要变成 D:/a.png，
    直接 url[7:] 会得到 /D:/a.png（开头多一个斜杠），是个很容易踩的坑。"""
    from urllib.parse import unquote, urlparse
    p = urlparse(url)
    raw = unquote(p.path)
    if p.netloc:                       # file://host/share/... 这种 UNC 形式
        raw = f"//{p.netloc}{raw}"
    if re.match(r"^/[A-Za-z]:", raw):  # /D:/xxx → D:/xxx
        raw = raw[1:]
    return Path(raw)


def download_images(urls: list[str], dest_dir: Path, prefix: str,
                    timeout: int = 20) -> tuple[list[str], list[str]]:
    """下载题目/作答图片到本地。

    返回 (本地相对路径列表, 失败列表)。失败不抛异常——
    一道题的图挂了不该让整次同步失败，但必须在返回值里暴露出来。
    """
    import requests
    dest_dir.mkdir(parents=True, exist_ok=True)
    ok, failed = [], []
    for i, url in enumerate(urls, 1):
        if not url:
            continue
        if url.startswith("file://"):
            # 本地文件也要**复制进 images 目录**，不能只记个路径：
            # 一是 Windows 的 file:///D:/x.png 直接切片会得到 /D:/x.png（错的），
            # 二是数据要自包含，原文件被移走后题库就瞎了。
            try:
                src = _file_url_to_path(url)
                data = src.read_bytes()
                name = f"{prefix}_{i:02d}{src.suffix or '.png'}"
                (dest_dir / name).write_bytes(data)
                ok.append(name)
            except Exception:
                failed.append(url)
            continue
        if not url.startswith("http"):
            ok.append(url)  # 已经是本地相对路径
            continue
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            ext = ".png"
            ctype = r.headers.get("Content-Type", "")
            if "jpeg" in ctype or "jpg" in ctype:
                ext = ".jpg"
            elif "webp" in ctype:
                ext = ".webp"
            else:
                m = re.search(r"\.(png|jpe?g|webp|gif)(\?|$)", url, re.I)
                if m:
                    ext = "." + m.group(1).lower().replace("jpeg", "jpg")
            name = f"{prefix}_{i:02d}{ext}"
            (dest_dir / name).write_bytes(r.content)
            ok.append(name)
        except Exception:
            failed.append(url)
    return ok, failed
