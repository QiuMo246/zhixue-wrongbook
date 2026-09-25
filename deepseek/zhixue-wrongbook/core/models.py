"""数据模型：三通道归一化后的统一对象 WrongQuestion。

设计原则
--------
1. 字段严格对齐架构文档第 7 节，不擅自加减字段名。
2. 用 pydantic 做类型校验——脏数据在进入 SQLite 之前就被拦住，
   而不是等到统计阶段才发现 difficulty 是字符串。
3. `fingerprint` 是去重的唯一依据，由内容算出来，不由来源决定。
   同一道题从 API 拿一次、从导出 PDF 拿一次，应该合并成一条。
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .constants import PRACTICE_RESULTS, QUESTION_TYPES, SOURCES


# ---------------------------------------------------------------------------
# HTML / 文本清洗（校验、指纹、相似度都要用同一套清洗规则）
# ---------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# 图片/公式占位符，清掉避免影响指纹稳定性
_PLACEHOLDER_RE = re.compile(r"\[(图片|img|公式|image)\]", re.I)
# 平台把公式渲染成 <img>，但**把 LaTeX 原文放在 data-latex 属性里**
# （实测形如 data-latex="%20%5Cbecause%20" type="ocr"）。
# 这是数学/物理题里唯一可用的公式文本 —— 直接剥标签会把公式全丢掉。
_LATEX_ATTR_RE = re.compile(r'data-latex\s*=\s*"([^"]*)"', re.I)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)


def _img_to_text(m: "re.Match[str]") -> str:
    """公式图 → LaTeX 原文；普通图片 → 空字符串（保留原有行为）。"""
    lat = _LATEX_ATTR_RE.search(m.group(0))
    if not lat:
        return ""
    try:
        return urllib.parse.unquote(lat.group(1))
    except Exception:
        return lat.group(1)


def html_to_text(html: str | None) -> str:
    """把题干/答案的 HTML 压成纯文本。用于校验定位、指纹、相似度。

    2026-09-24 修正：先把带 `data-latex` 的公式图还原成 LaTeX 原文，
    再剥标签。不这么做的话，数学/物理题的公式会被整段丢掉 ——
    实测一道题的题干会退化成「如图，在中，，，，点、分别在、上」，
    标准答案退化成单个 `+`，而解析里其实藏着 96 段可还原的 LaTeX。
    """
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</(p|div|li|tr)>", "\n", text, flags=re.I)
    text = _IMG_RE.sub(_img_to_text, text)   # 公式图 → LaTeX，必须在剥标签之前
    text = _TAG_RE.sub("", text)
    # 常见 HTML 实体
    for a, b in (("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"),
                 ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(a, b)
    text = _PLACEHOLDER_RE.sub("", text)
    return text.strip()


def squash(text: str | None) -> str:
    """去掉所有空白，用于「证据能否定位」的宽松比对。"""
    if not text:
        return ""
    return _WS_RE.sub("", text)


class Exam(BaseModel):
    name: str
    date: str | None = None          # ISO 日期字符串，允许缺失


class QuestionPart(BaseModel):
    stem_html: str = ""
    images: list[str] = Field(default_factory=list)
    type: str = "解答题"
    difficulty: float | None = None          # 平台自带，刻度见 difficulty_scale
    difficulty_scale: str = "unknown"        # 'unknown' | '0-1' | 'raw'
    class_score_rate: float | None = None    # 班级得分率，0~1

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in QUESTION_TYPES:
            # 不直接拒绝：平台可能有我们没枚举到的题型，
            # 但要让它显式化，方便回头补枚举。
            return "解答题" if not v else v
        return v


class AnswerPart(BaseModel):
    student_text: str | None = None          # 客观题：文本作答
    student_images: list[str] = Field(default_factory=list)  # 主观题：手写图片
    standard: str | None = None
    analysis_html: str | None = None


class Score(BaseModel):
    got: float | None = None
    full: float | None = None

    @property
    def rate(self) -> float | None:
        if self.got is None or not self.full:
            return None
        return max(0.0, min(1.0, self.got / self.full))


class Analysis(BaseModel):
    error_type: str
    knowledge_points: list[str]
    evidence: list[str]
    confidence: float = 0.0
    needs_review: bool = False
    analyzed_by: str = ""
    prompt_version: str = ""


class PracticeRef(BaseModel):
    gen_id: str
    verified: bool = False


class HistoryEntry(BaseModel):
    date: str
    result: Literal["correct", "partial", "wrong"]

    @field_validator("result")
    @classmethod
    def _check_result(cls, v: str) -> str:
        if v not in PRACTICE_RESULTS:
            raise ValueError(f"result 必须是 {PRACTICE_RESULTS} 之一，收到 {v!r}")
        return v


class WrongQuestion(BaseModel):
    id: str
    source: Literal["api", "api-homework", "export", "manual"] = "manual"
    source_version: str = ""
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    parse_confidence: float = 1.0

    subject: str
    grade: str | None = None
    exam: Exam
    question: QuestionPart
    answer: AnswerPart = Field(default_factory=AnswerPart)
    score: Score = Field(default_factory=Score)

    analysis: Analysis | None = None
    practice: list[PracticeRef] = Field(default_factory=list)
    history: list[HistoryEntry] = Field(default_factory=list)

    @field_validator("source")
    @classmethod
    def _check_source(cls, v: str) -> str:
        if v not in SOURCES:
            raise ValueError(f"source 必须是 {SOURCES} 之一，收到 {v!r}")
        return v

    # -- 派生量 ------------------------------------------------------------
    @property
    def stem_text(self) -> str:
        return html_to_text(self.question.stem_html)

    @property
    def student_text(self) -> str:
        return html_to_text(self.answer.student_text)

    @property
    def standard_text(self) -> str:
        return html_to_text(self.answer.standard)

    def corpus_for_evidence(self) -> str:
        """证据定位用的语料池：题干 + 标准答案 + 解析 + 学生作答。

        证据要求「能在题干或学生作答中找到」，这里放宽到也允许出现在
        标准答案/解析里——因为像「学生直接代入求根」这种描述，
        往往是对照标准解法说出来的。放宽的那部分在校验结果里标为
        warning 而非 error，保持可审计。
        """
        parts = [self.stem_text, self.student_text, self.standard_text,
                 html_to_text(self.answer.analysis_html)]
        return "\n".join(p for p in parts if p)

    def fingerprint(self) -> str:
        """内容指纹：跨通道、跨次同步稳定。

        刻意**不**包含 score / fetched_at / 学生答案 ——
        同一道题重做一次得 0 分，仍然是同一道题。

        也刻意**不**包含 `question.type`。它看起来像内容，其实是**推导出来的
        标签**：API 通道由 answer_type + 题干启发式算，导出通道由文件里的
        文本算。同一个字段、两套算法，结果就可能不一致。
        而本方法的承诺是「同一道题从 API 拿一次、从导出 PDF 拿一次，
        应该合并成一条」——把推导标签塞进来，正好会破坏这个承诺。

        踩过的坑（2026-09-24）：题型判定规则一改，11 道已入库的题
        指纹全变、被当成新题重复入库，题库凭空多出 11 条。
        推导字段不该参与身份判定。
        """
        basis = "|".join([
            squash(self.subject),
            squash(self.exam.name),
            squash(self.exam.date or ""),
            squash(self.stem_text)[:800],
            squash(self.standard_text)[:400],
        ])
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]

    def to_row(self) -> dict:
        """转成 SQLite 行（扁平结构）。"""
        return {
            "id": self.id,
            "fingerprint": self.fingerprint(),
            "source": self.source,
            "source_version": self.source_version,
            "fetched_at": self.fetched_at.isoformat(),
            "parse_confidence": self.parse_confidence,
            "subject": self.subject,
            "grade": self.grade,
            "exam_name": self.exam.name,
            "exam_date": self.exam.date,
            "stem_html": self.question.stem_html,
            "images": self.question.images,
            "qtype": self.question.type,
            "difficulty": self.question.difficulty,
            "difficulty_scale": self.question.difficulty_scale,
            "class_score_rate": self.question.class_score_rate,
            "student_text": self.answer.student_text,
            "student_images": self.answer.student_images,
            "standard": self.answer.standard,
            "analysis_html": self.answer.analysis_html,
            "score_got": self.score.got,
            "score_full": self.score.full,
            "analysis": self.analysis.model_dump() if self.analysis else None,
            "practice": [p.model_dump() for p in self.practice],
            "history": [h.model_dump() for h in self.history],
        }
