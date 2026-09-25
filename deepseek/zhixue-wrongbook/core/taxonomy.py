"""taxonomy.yaml 的加载与查询。

知识点校验是防幻觉的关键闸门：模型只能「选」，不能「造」。
本模块提供：
  - 规范路径集合（数学/一元二次方程/公式法与判别式）
  - 宽松解析：允许「章节/知识点」两段写法，但要求学科内唯一命中
  - 模糊建议：拒绝时给出最接近的候选，让宿主能自我纠正而不是瞎猜
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "data" / "taxonomy.yaml"


@dataclass(frozen=True)
class KpInfo:
    subject: str
    chapter: str
    point: str

    @property
    def path(self) -> str:
        return f"{self.subject}/{self.chapter}/{self.point}"

    @property
    def chapter_path(self) -> str:
        return f"{self.subject}/{self.chapter}"


class Taxonomy:
    def __init__(self, data: dict):
        self.version: int = data.get("version", 1)
        self.updated_at: str = str(data.get("updated_at", ""))
        self._infos: list[KpInfo] = []
        for subj in data.get("subjects", []):
            sname = subj["name"]
            for chap in subj.get("chapters", []):
                cname = chap["name"]
                for pt in chap.get("points", []):
                    self._infos.append(KpInfo(sname, cname, str(pt)))
        self._by_path = {i.path: i for i in self._infos}
        # 章节/知识点 -> [KpInfo]（用于两段写法消歧）
        self._by_two = {}
        for i in self._infos:
            self._by_two.setdefault(f"{i.chapter}/{i.point}", []).append(i)
        # 纯知识点名 -> [KpInfo]
        self._by_point = {}
        for i in self._infos:
            self._by_point.setdefault(i.point, []).append(i)

    # -- 查询 ---------------------------------------------------------------
    @property
    def all_paths(self) -> list[str]:
        return [i.path for i in self._infos]

    def subjects(self) -> list[str]:
        out = []
        for i in self._infos:
            if i.subject not in out:
                out.append(i.subject)
        return out

    def chapters(self, subject: str | None = None) -> list[str]:
        out = []
        for i in self._infos:
            if subject and i.subject != subject:
                continue
            if i.chapter_path not in out:
                out.append(i.chapter_path)
        return out

    def points_in_chapter(self, chapter_path: str) -> list[str]:
        return [i.path for i in self._infos if i.chapter_path == chapter_path]

    def resolve(self, raw: str, subject: str | None = None) -> tuple[KpInfo | None, str]:
        """把用户/模型给的写法解析成规范 KpInfo。

        返回 (info, reason)。info 为 None 时 reason 说明原因。
        """
        key = (raw or "").strip().strip("/")
        if not key:
            return None, "知识点为空"

        # 1) 完全规范路径
        if key in self._by_path:
            info = self._by_path[key]
            if subject and info.subject != subject:
                return None, f"知识点「{key}」不属于学科「{subject}」"
            return info, ""

        # 2) 章节/知识点（两段）—— 学科内唯一则接受
        cands = self._by_two.get(key, [])
        if subject:
            cands = [c for c in cands if c.subject == subject]
        if len(cands) == 1:
            return cands[0], ""
        if len(cands) > 1:
            opts = "、".join(c.path for c in cands[:5])
            return None, f"知识点「{key}」有歧义，请用完整路径，例如：{opts}"

        # 3) 只有知识点名 —— 同上
        cands = self._by_point.get(key, [])
        if subject:
            cands = [c for c in cands if c.subject == subject]
        if len(cands) == 1:
            return cands[0], ""
        if len(cands) > 1:
            opts = "、".join(c.path for c in cands[:5])
            return None, f"知识点「{key}」有歧义，请用完整路径，例如：{opts}"

        # 4) 模糊建议：先子串，再 difflib
        near = self.search(key, subject, n=3)
        hint = f"，你是不是想写：{'、'.join(near)}" if near else ""
        return None, f"知识点「{key}」不在受控词表内{hint}"

    def search(self, query: str, subject: str | None = None,
               n: int = 20) -> list[str]:
        """按关键词找知识点路径。子串优先，difflib 兜底。

        为什么子串要排在 difflib 前面（2026-09-25 实测）：
        模型给的往往是考点的一部分，而 difflib 对「短串 vs 长串」的相似度
        算得很低。实测 `resolve("西安事变", "历史")` 在只有 difflib 时
        **一个候选都给不出来** —— '西安事变' 对
        '九一八事变与西安事变' 的相似度只有 0.57，卡在 0.6 阈值下面。
        子串匹配能稳稳命中，而且结果更符合直觉。

        三层匹配，按「精确程度」降序：
          1. 关键词是路径的一部分（key in path）—— 最准
          2. 某个知识点名出现在关键词里（point in key）—— 处理
             「洋务运动的作用」这种模型自己加了修饰语的情况
          3. difflib 模糊兜底
        """
        key = (query or "").strip()
        pool = [i for i in self._infos if not subject or i.subject == subject]
        if not key:
            return [i.path for i in pool][:n]

        hits = [i.path for i in pool if key in i.path]
        if not hits:
            hits = [i.path for i in pool if i.point and i.point in key]
        if hits:
            # 路径短的更可能是「精确的那个」，排前面
            return sorted(set(hits), key=len)[:n]

        near = difflib.get_close_matches(
            key, [i.point for i in pool], n=n, cutoff=0.5)
        out = [i.path for i in pool if i.point in near]
        if not out:
            out = difflib.get_close_matches(
                key, [i.path for i in pool], n=n, cutoff=0.3)
        return out[:n]

    def suggest(self, raw: str, subject: str | None = None, n: int = 5) -> list[str]:
        """保留旧接口（difflib 模糊），新代码请用 search()。"""
        pool = [i.path for i in self._infos if not subject or i.subject == subject]
        return difflib.get_close_matches(raw, pool, n=n, cutoff=0.3)


@lru_cache(maxsize=4)
def load_taxonomy(path: str | None = None) -> Taxonomy:
    p = Path(path) if path else DEFAULT_TAXONOMY_PATH
    with open(p, "r", encoding="utf-8") as fh:
        return Taxonomy(yaml.safe_load(fh))
