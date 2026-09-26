"""数据层：本地 SQLite 存取、指纹去重、增量同步、真删。

设计要点
--------
1. **指纹去重**：同一道题从 API 和导出文件各拿一次，只存一条。
   指纹只由「内容」算（学科+考试+题干+标准答案+题型），
   不含得分/时间——同一题重做一次仍是同一题。
2. **增量**：靠 (fingerprint, fetched_at) 判断。已存在的题不重复插入，
   只更新会变的部分（得分、分析结果、历史）。
   额外存 first_seen_at（模型契约外的扩展字段），这样
   「fetched_at 是最近一次抓取时间」和「第一次见到这道题的时间」都不丢。
3. **真删**：zx_purge 会删库文件 + 图片目录 + WAL/SHM，
   不是打标记。调用方必须显式传 confirm=True。

存储格式：一题一行（扁平列），嵌套结构（analysis/practice/history）
存 JSON 文本。为什么不全塞一个 JSON？
因为「按知识点筛错题」「按学科统计」要能用 SQL 走索引，
知识点是查询主路径，不能埋在 JSON 里。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .constants import (PAPER_TYPE_ALL, PAPER_TYPE_OTHER, PAPER_TYPES,
                        PARSE_CONFIDENCE_MIN)
from .fingerprint import FingerprintStore
from .models import (Analysis, AnswerPart, Exam, HistoryEntry, PracticeRef,
                     QuestionPart, Score, WrongQuestion)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "wrongbook.db"
DEFAULT_IMAGES_DIR = ROOT / "data" / "images"

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id                TEXT PRIMARY KEY,
    fingerprint       TEXT NOT NULL UNIQUE,
    source            TEXT NOT NULL,
    source_version    TEXT NOT NULL DEFAULT '',
    fetched_at        TEXT NOT NULL,
    first_seen_at     TEXT NOT NULL,
    parse_confidence  REAL NOT NULL DEFAULT 1.0,
    subject           TEXT NOT NULL,
    grade             TEXT,
    exam_name         TEXT NOT NULL,
    exam_date         TEXT,
    stem_html         TEXT NOT NULL DEFAULT '',
    images            TEXT NOT NULL DEFAULT '[]',
    qtype             TEXT NOT NULL DEFAULT '解答题',
    difficulty        REAL,
    difficulty_scale  TEXT NOT NULL DEFAULT 'unknown',
    class_score_rate  REAL,
    student_text      TEXT,
    student_images    TEXT NOT NULL DEFAULT '[]',
    standard          TEXT,
    analysis_html     TEXT,
    score_got         REAL,
    score_full        REAL,
    analysis          TEXT,
    practice          TEXT NOT NULL DEFAULT '[]',
    history           TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_q_subject ON questions(subject);
CREATE INDEX IF NOT EXISTS idx_q_exam    ON questions(exam_name, exam_date);
CREATE INDEX IF NOT EXISTS idx_q_fetch   ON questions(fetched_at);

-- 知识点是查询主路径，单独开表（一题多知识点，一对多）
CREATE TABLE IF NOT EXISTS question_kp (
    fingerprint TEXT NOT NULL,
    kp_path     TEXT NOT NULL,
    PRIMARY KEY (fingerprint, kp_path)
);
CREATE INDEX IF NOT EXISTS idx_kp ON question_kp(kp_path);

CREATE TABLE IF NOT EXISTS sync_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    channel    TEXT NOT NULL,
    subject    TEXT,
    exam       TEXT,
    added      INTEGER DEFAULT 0,
    updated    INTEGER DEFAULT 0,
    skipped    INTEGER DEFAULT 0,
    failed     INTEGER DEFAULT 0,
    error      TEXT
);

-- 个性化诊断审计（2026-09-24 新增「诊断前必须确认科目」功能；
--                 2026-09-25 扩展为「科目 + 试卷范围」两问）
--
-- 为什么值得单独开一张表：这条规则的机器侧形态是「工具拒绝不带
-- user_confirmed=true 的调用」，但**没有任何代码能验证用户真的被问过** ——
-- 那取决于宿主模型有没有老实问。所以退一步：把「每次诊断用了哪一科、
-- 声称已确认、基于多少道题」记下来，事后可查、可追责。
-- 不留痕的规则等于没有规则。
--
-- 2026-09-25 补 paper_types / time_scope / scope_confirmed 三列：
-- 光记科目不够 —— 同一科选「本周午练」和选「全部」，结论可以完全不同，
-- 事后只看科目根本判断不了这次诊断到底覆盖了什么。
CREATE TABLE IF NOT EXISTS diagnosis_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at     TEXT NOT NULL,
    subject        TEXT NOT NULL,
    user_confirmed INTEGER NOT NULL DEFAULT 0,
    paper_types    TEXT NOT NULL DEFAULT '',
    time_scope     TEXT NOT NULL DEFAULT '',
    scope_confirmed INTEGER NOT NULL DEFAULT 0,
    question_count INTEGER DEFAULT 0,
    analyzed_count INTEGER DEFAULT 0,
    weak_top       TEXT,
    host           TEXT
);
"""


def _json_load(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def paper_type_where(paper_types: list[str] | None) -> tuple[str, list] | None:
    """把试卷类型列表翻成 SQL 条件。返回 (条件, 参数) 或 None（= 不筛）。

    判定依据是 `exam_name` 的关键字 —— 平台的命名约定就是
    「20260918八年级周测」「午练-八年级-20260922」。见 core/scope.py 的说明。

    「其他」的语义是「不属于四类中的任何一类」，所以它是
    **4 个 NOT LIKE 的 AND**，不是 OR —— 写成 OR 会永远成立（等于没筛）。
    「全部」直接返回 None。
    """
    if not paper_types or PAPER_TYPE_ALL in paper_types:
        return None

    groups, args = [], []
    for t in paper_types:
        if t == PAPER_TYPE_OTHER:
            groups.append("(" + " AND ".join(
                ["q.exam_name NOT LIKE ?"] * len(PAPER_TYPES)) + ")")
            args.extend(f"%{base}%" for base in PAPER_TYPES)
        else:
            groups.append("q.exam_name LIKE ?")
            args.append(f"%{t}%")
    if not groups:
        return None
    return "(" + " OR ".join(groups) + ")", args


def row_to_question(row: sqlite3.Row) -> WrongQuestion:
    """SQLite 行 → WrongQuestion。与 to_row() 严格互为逆运算。"""
    analysis_raw = _json_load(row["analysis"], None)
    return WrongQuestion(
        id=row["id"],
        source=row["source"],
        source_version=row["source_version"] or "",
        fetched_at=row["fetched_at"],
        parse_confidence=row["parse_confidence"],
        subject=row["subject"],
        grade=row["grade"],
        exam=Exam(name=row["exam_name"], date=row["exam_date"]),
        question=QuestionPart(
            stem_html=row["stem_html"] or "",
            images=_json_load(row["images"], []),
            type=row["qtype"] or "解答题",
            difficulty=row["difficulty"],
            difficulty_scale=row["difficulty_scale"] or "unknown",
            class_score_rate=row["class_score_rate"],
        ),
        answer=AnswerPart(
            student_text=row["student_text"],
            student_images=_json_load(row["student_images"], []),
            standard=row["standard"],
            analysis_html=row["analysis_html"],
        ),
        score=Score(got=row["score_got"], full=row["score_full"]),
        analysis=Analysis(**analysis_raw) if analysis_raw else None,
        practice=[PracticeRef(**p) for p in _json_load(row["practice"], [])],
        history=[HistoryEntry(**h) for h in _json_load(row["history"], [])],
    )


class Store:
    def __init__(self, db_path: str | Path | None = None,
                 images_dir: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.images_dir = Path(images_dir) if images_dir else DEFAULT_IMAGES_DIR
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        # 接口结构指纹（包二，2026-09-26）：表由 FingerprintStore 自建，
        # 挂在主库上 —— 指纹和题目数据同生共死，purge 时一起删。
        self.fingerprints = FingerprintStore(self.conn)
        self.conn.commit()
        # id 撞车后改名的记录。正常情况下应该永远是空的；
        # 一旦非空说明 make_id 没能保证唯一，调用方（sync）必须把它报出来。
        self.id_fallbacks: list[dict] = []
        # 本次生命周期内「因为本次没带新值而被保留下来的」派生数据条数。
        # 用途：让「重新同步没有清空既有分析结果」变成可观察的事实，
        # 而不是一个只能靠翻数据库才能确认的隐性承诺。
        self.preserved_analysis = 0
        self.preserved_practice = 0
        self.preserved_history = 0

    def _migrate(self) -> None:
        """老库补列。

        为什么要迁移：schema 里新增字段（如 difficulty_scale）时，
        已经存在的 wrongbook.db 不会自动长出新列，直接 INSERT 会报
        "table questions has no column named ..."。
        这里做最小化的 ALTER TABLE，不删数据。

        2026-09-25：迁移范围从 questions 扩到 diagnosis_log ——
        老库里那张表没有 paper_types / time_scope / scope_confirmed，
        不补列的话新代码一写审计就报错。
        """
        for table, wanted in (
            ("questions", {
                "difficulty_scale": "TEXT NOT NULL DEFAULT 'unknown'",
                "first_seen_at": "TEXT NOT NULL DEFAULT ''",
            }),
            ("diagnosis_log", {
                "paper_types": "TEXT NOT NULL DEFAULT ''",
                "time_scope": "TEXT NOT NULL DEFAULT ''",
                "scope_confirmed": "INTEGER NOT NULL DEFAULT 0",
            }),
        ):
            existing = {r["name"] for r in
                        self.conn.execute(f"PRAGMA table_info({table})")}
            for col, ddl in wanted.items():
                if col not in existing:
                    self.conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

    # -- 生命周期 -----------------------------------------------------------
    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- 写入 ---------------------------------------------------------------
    def upsert(self, q: WrongQuestion) -> str:
        """插入或更新一题。返回 'added' / 'updated'。

        'updated' 的含义是：题目内容已存在（指纹相同），
        但本次抓取带来了新信息（比如这次补上了分析结果、或得分变了）。
        完全没变化时仍返回 'updated'，由调用方按 sync_log 统计口径决定
        是否计为 skipped——这里不做「静默跳过」，
        因为沉默的跳过会掩盖「接口返回了空数据」这类故障。

        ⚠️ **派生字段的覆盖规则（2026-09-25 修的真实数据丢失缺陷）**

        表里的列分两类：

        | 类别 | 例子 | 谁写的 | 能不能被同步覆盖 |
        |---|---|---|---|
        | 来源数据 | 题干、标准答案、得分、难度 | 每次同步重新抓 | ✅ 可以 |
        | **派生数据** | `analysis` / `practice` / `history` | 调用方**后来**提交的 | ❌ **不能** |

        原因：同步抓回来的对象里，派生字段天然是空的
        （分析是宿主后来通过 `submit_analysis` 提交的）。
        原来这里是无条件全字段 UPDATE，于是**每同步一次就把已有分析结果清空一次**——
        实测 27 道题的 analysis 从 27 条掉到 0 条，而且 `zx_sync` 还返回 ok=true，
        属于最危险的「静默数据丢失」。

        所以派生字段改成「**传入值非空才覆盖**」：
        本次带了新分析结果就更新它，没带就保留库里已有的。
        """
        fp = q.fingerprint()
        now = datetime.now(timezone.utc).isoformat()
        row = q.to_row()
        row["fingerprint"] = fp

        cur = self.conn.execute(
            "SELECT analysis, practice, history FROM questions WHERE fingerprint = ?",
            (fp,),
        )
        existing = cur.fetchone()
        existed = existing is not None

        if existed:
            analysis_json = (json.dumps(row["analysis"], ensure_ascii=False)
                             if row["analysis"] else None)
            practice_json = json.dumps(row["practice"], ensure_ascii=False)
            history_json = json.dumps(row["history"], ensure_ascii=False)

            # 记一笔「本次保留了多少条既有派生数据」，让"没被清掉"变成可观察的事实
            if analysis_json is None and existing[0]:
                self.preserved_analysis += 1
            if practice_json == "[]" and existing[1] and existing[1] != "[]":
                self.preserved_practice += 1
            if history_json == "[]" and existing[2] and existing[2] != "[]":
                self.preserved_history += 1

            self.conn.execute(
                """UPDATE questions SET
                     source=?, source_version=?, fetched_at=?, parse_confidence=?,
                     subject=?, grade=?, exam_name=?, exam_date=?,
                     stem_html=?, images=?, qtype=?, difficulty=?, difficulty_scale=?,
                     class_score_rate=?,
                     student_text=?, student_images=?, standard=?, analysis_html=?,
                     score_got=?, score_full=?,
                     analysis = COALESCE(?, analysis),
                     practice = CASE WHEN ? = '[]' THEN practice ELSE ? END,
                     history  = CASE WHEN ? = '[]' THEN history ELSE ? END
                   WHERE fingerprint=?""",
                (row["source"], row["source_version"], row["fetched_at"],
                 row["parse_confidence"], row["subject"], row["grade"],
                 row["exam_name"], row["exam_date"], row["stem_html"],
                 json.dumps(row["images"], ensure_ascii=False), row["qtype"],
                 row["difficulty"], row["difficulty_scale"],
                 row["class_score_rate"], row["student_text"],
                 json.dumps(row["student_images"], ensure_ascii=False),
                 row["standard"], row["analysis_html"], row["score_got"],
                 row["score_full"],
                 analysis_json,
                 practice_json, practice_json,
                 history_json, history_json, fp),
            )
            result = "updated"
        else:
            try:
                self._insert_row(row, fp, now)
            except sqlite3.IntegrityError as exc:
                # fingerprint 上面刚查过、确认不存在，所以唯一性冲突只可能来自 id。
                # 而 id 只是给人看的标签，fingerprint 才是身份 ——
                # 那就换个没人占用的 id 再插一次，别让整场同步因为一个标签而失败。
                if "questions.id" not in str(exc):
                    raise
                preferred = str(row["id"])
                row["id"] = self._unique_id(preferred, fp)
                self._insert_row(row, fp, now)
                self.id_fallbacks.append({"preferred": preferred,
                                          "used": row["id"]})
            result = "added"

        self._sync_kp(fp, q)
        self.conn.commit()
        return result

    def _insert_row(self, row: dict, fp: str, now: str) -> None:
        self.conn.execute(
            """INSERT INTO questions (
                 id, fingerprint, source, source_version, fetched_at,
                 first_seen_at, parse_confidence, subject, grade,
                 exam_name, exam_date, stem_html, images, qtype, difficulty,
                 difficulty_scale, class_score_rate, student_text,
                 student_images, standard, analysis_html, score_got,
                 score_full, analysis, practice, history
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row["id"], fp, row["source"], row["source_version"],
             row["fetched_at"], now, row["parse_confidence"], row["subject"],
             row["grade"], row["exam_name"], row["exam_date"],
             row["stem_html"], json.dumps(row["images"], ensure_ascii=False),
             row["qtype"], row["difficulty"], row["difficulty_scale"],
             row["class_score_rate"], row["student_text"],
             json.dumps(row["student_images"], ensure_ascii=False),
             row["standard"], row["analysis_html"], row["score_got"],
             row["score_full"],
             json.dumps(row["analysis"], ensure_ascii=False) if row["analysis"] else None,
             json.dumps(row["practice"], ensure_ascii=False),
             json.dumps(row["history"], ensure_ascii=False)),
        )

    def _unique_id(self, preferred: str, fp: str) -> str:
        """给一个库内没被占用的 id。

        首选 `原 id + 指纹前缀`：既保留可读性，又**稳定**——
        同一道题每次同步都会算出同一个后缀，不会每次都变。
        """
        candidate = f"{preferred}-{fp[:6]}"
        if not self._id_taken(candidate):
            return candidate
        for i in range(2, 1000):
            alt = f"{candidate}-{i}"
            if not self._id_taken(alt):
                return alt
        raise RuntimeError(f"无法为 {preferred} 生成唯一 id（库内已占用上千个变体）")

    def _id_taken(self, qid: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM questions WHERE id = ?", (qid,)).fetchone() is not None

    def stale_fingerprint_count(self) -> int:
        """有多少行的 fingerprint 列与「现在重算的结果」不一致。

        为什么需要：`fingerprint` 是**推导值**，而推导逻辑会变。
        实测（2026-09-24）两次踩到：
          1. 指纹里含了推导出来的 `question.type` → 改题型规则，11 道老题变新题；
          2. `html_to_text` 学会还原公式图里的 data-latex → 题干文本变了，
             指纹跟着变，老行全部对不上。
        逻辑一变，老行的 fingerprint 就跟不上，再同步会被当成新题**重复入库**。
        这里只做检测，让 sync() 大声提示「先 purge 再同步」——
        不自动改指纹（可能撞 UNIQUE），更不自动删数据。
        """
        stale = 0
        for r in self.conn.execute("SELECT * FROM questions"):
            if row_to_question(r).fingerprint() != r["fingerprint"]:
                stale += 1
        return stale

    def _sync_kp(self, fp: str, q: WrongQuestion) -> None:
        self.conn.execute("DELETE FROM question_kp WHERE fingerprint = ?", (fp,))
        if q.analysis and q.analysis.knowledge_points:
            self.conn.executemany(
                "INSERT OR IGNORE INTO question_kp (fingerprint, kp_path) VALUES (?,?)",
                [(fp, kp) for kp in q.analysis.knowledge_points],
            )

    def set_analysis(self, fingerprint: str, analysis: Analysis) -> bool:
        """submit_analysis 落库入口。指纹不存在则返回 False。"""
        cur = self.conn.execute(
            "SELECT fingerprint FROM questions WHERE fingerprint = ?", (fingerprint,))
        if cur.fetchone() is None:
            return False
        self.conn.execute(
            "UPDATE questions SET analysis = ? WHERE fingerprint = ?",
            (json.dumps(analysis.model_dump(), ensure_ascii=False), fingerprint),
        )
        self.conn.execute("DELETE FROM question_kp WHERE fingerprint = ?", (fingerprint,))
        if analysis.knowledge_points:
            self.conn.executemany(
                "INSERT OR IGNORE INTO question_kp (fingerprint, kp_path) VALUES (?,?)",
                [(fingerprint, kp) for kp in analysis.knowledge_points],
            )
        self.conn.commit()
        return True

    def add_practice(self, fingerprint: str, ref: PracticeRef) -> bool:
        cur = self.conn.execute(
            "SELECT practice FROM questions WHERE fingerprint = ?", (fingerprint,))
        row = cur.fetchone()
        if row is None:
            return False
        items = _json_load(row["practice"], [])
        items = [i for i in items if i.get("gen_id") != ref.gen_id]
        items.append(ref.model_dump())
        self.conn.execute("UPDATE questions SET practice = ? WHERE fingerprint = ?",
                          (json.dumps(items, ensure_ascii=False), fingerprint))
        self.conn.commit()
        return True

    def add_history(self, fingerprint: str, entry: HistoryEntry) -> bool:
        cur = self.conn.execute(
            "SELECT history FROM questions WHERE fingerprint = ?", (fingerprint,))
        row = cur.fetchone()
        if row is None:
            return False
        items = _json_load(row["history"], [])
        items.append(entry.model_dump())
        self.conn.execute("UPDATE questions SET history = ? WHERE fingerprint = ?",
                          (json.dumps(items, ensure_ascii=False), fingerprint))
        self.conn.commit()
        return True

    # -- 读取 ---------------------------------------------------------------
    def get(self, fingerprint: str) -> WrongQuestion | None:
        cur = self.conn.execute(
            "SELECT * FROM questions WHERE fingerprint = ? OR id = ?",
            (fingerprint, fingerprint))
        row = cur.fetchone()
        return row_to_question(row) if row else None

    def query(self, subject: str | None = None, exam: str | None = None,
              kp: str | None = None, only_analyzed: bool = False,
              only_unanalyzed: bool = False, needs_review: bool | None = None,
              min_confidence: float | None = None,
              exclude_low_confidence: bool = True,
              limit: int | None = None,
              fingerprints: list[str] | None = None,
              paper_types: list[str] | None = None,
              date_from: str = "", date_to: str = "") -> list[WrongQuestion]:
        sql = "SELECT q.* FROM questions q"
        where, args = [], []
        if kp:
            sql += " JOIN question_kp k ON k.fingerprint = q.fingerprint"
            where.append("k.kp_path = ?")
            args.append(kp)
        if subject:
            where.append("q.subject = ?")
            args.append(subject)
        if exam:
            where.append("q.exam_name LIKE ?")
            args.append(f"%{exam}%")
        # 试卷范围（2026-09-25 新增「诊断前必须确认试卷范围」功能）
        pt = paper_type_where(paper_types)
        if pt:
            where.append(pt[0])
            args.extend(pt[1])
        if date_from:
            where.append("q.exam_date >= ?")
            args.append(date_from)
        if date_to:
            where.append("q.exam_date <= ?")
            args.append(date_to)
        if only_analyzed:
            where.append("q.analysis IS NOT NULL")
        if only_unanalyzed:
            where.append("q.analysis IS NULL")
        if fingerprints:
            marks = ",".join("?" for _ in fingerprints)
            where.append(f"q.fingerprint IN ({marks})")
            args.extend(fingerprints)
        if min_confidence is not None:
            where.append("q.parse_confidence >= ?")
            args.append(min_confidence)
        elif exclude_low_confidence:
            # 低解析置信度的题默认排除（架构文档第 7 节 parse_confidence）
            where.append("q.parse_confidence >= ?")
            args.append(PARSE_CONFIDENCE_MIN)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY q.exam_date DESC, q.id ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self.conn.execute(sql, args).fetchall()
        out = [row_to_question(r) for r in rows]
        if needs_review is not None:
            out = [q for q in out
                   if (q.analysis.needs_review if q.analysis else False) == needs_review]
        return out

    def counts(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) c FROM questions").fetchone()["c"]
        analyzed = self.conn.execute(
            "SELECT COUNT(*) c FROM questions WHERE analysis IS NOT NULL").fetchone()["c"]
        by_source = {r["source"]: r["c"] for r in self.conn.execute(
            "SELECT source, COUNT(*) c FROM questions GROUP BY source")}
        by_subject = {r["subject"]: r["c"] for r in self.conn.execute(
            "SELECT subject, COUNT(*) c FROM questions GROUP BY subject")}
        low_conf = self.conn.execute(
            "SELECT COUNT(*) c FROM questions WHERE parse_confidence < ?",
            (PARSE_CONFIDENCE_MIN,)).fetchone()["c"]
        return {
            "total": total, "analyzed": analyzed, "unanalyzed": total - analyzed,
            "low_parse_confidence": low_conf,
            "by_source": by_source, "by_subject": by_subject,
        }

    # -- 试卷范围统计（2026-09-25 新增「诊断前必须确认试卷范围」功能）--------
    def count_questions(self, subject: str | None = None,
                        paper_types: list[str] | None = None,
                        date_from: str = "", date_to: str = "") -> int:
        """按范围数题。给闸门和选项清单用（不做低置信度排除 —— 那是统计口径，
        这里问的是「这个范围里到底有没有题」，口径要宽）。"""
        sql = "SELECT COUNT(*) c FROM questions q"
        where, args = [], []
        if subject:
            where.append("q.subject = ?")
            args.append(subject)
        pt = paper_type_where(paper_types)
        if pt:
            where.append(pt[0])
            args.extend(pt[1])
        if date_from:
            where.append("q.exam_date >= ?")
            args.append(date_from)
        if date_to:
            where.append("q.exam_date <= ?")
            args.append(date_to)
        if where:
            sql += " WHERE " + " AND ".join(where)
        return int(self.conn.execute(sql, args).fetchone()["c"])

    def counts_by_paper_type(self, subject: str | None = None) -> dict:
        """各试卷类型有多少道题。多一个 `__total__` 表示该科目总题数。

        为什么用「逐类型 count」而不是一次 GROUP BY：
        类型是从 exam_name 关键字**推**出来的，不是数据库里的列，
        没法 GROUP BY。类型只有 5 个，5 次 count 完全够用。
        """
        out = {t: self.count_questions(subject=subject, paper_types=[t])
               for t in PAPER_TYPES}
        out[PAPER_TYPE_OTHER] = self.count_questions(
            subject=subject, paper_types=[PAPER_TYPE_OTHER])
        out["__total__"] = self.count_questions(subject=subject)
        return out

    # -- 同步日志 -----------------------------------------------------------
    def log_sync_start(self, channel: str, subject: str | None,
                       exam: str | None) -> int:
        cur = self.conn.execute(
            "INSERT INTO sync_log (started_at, channel, subject, exam) VALUES (?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), channel, subject, exam))
        self.conn.commit()
        return int(cur.lastrowid)

    def log_sync_end(self, log_id: int, added: int = 0, updated: int = 0,
                     skipped: int = 0, failed: int = 0, error: str | None = None) -> None:
        self.conn.execute(
            """UPDATE sync_log SET ended_at=?, added=?, updated=?, skipped=?,
                   failed=?, error=? WHERE id=?""",
            (datetime.now(timezone.utc).isoformat(), added, updated, skipped,
             failed, error, log_id))
        self.conn.commit()

    def sync_logs(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # -- 科目统计 / 诊断审计 ------------------------------------------------
    def subject_stats(self) -> dict:
        """按科目统计：总题数、已分析数。

        给 core/subjects.py 组装「可诊断科目清单」用。
        用一条 GROUP BY 而不是逐科查，避免科目一多就 N+1。
        """
        rows = self.conn.execute(
            """SELECT subject,
                      COUNT(*) AS c,
                      SUM(CASE WHEN analysis IS NOT NULL THEN 1 ELSE 0 END) AS a
                 FROM questions GROUP BY subject"""
        ).fetchall()
        return {r["subject"]: {"questions": int(r["c"]),
                               "analyzed": int(r["a"] or 0)} for r in rows}

    def log_diagnosis(self, subject: str, user_confirmed: bool,
                      question_count: int = 0, analyzed_count: int = 0,
                      weak_top: list[str] | None = None, host: str = "",
                      paper_types: list[str] | None = None,
                      time_scope: str = "",
                      scope_confirmed: bool = False) -> int:
        """记一条个性化诊断审计。返回自增 id（宿主可回报给用户）。

        paper_types / time_scope 记的是**这次诊断实际覆盖的范围**，
        不是用户原话 —— 事后核对时「覆盖了什么」比「说了什么」更有用。
        """
        cur = self.conn.execute(
            """INSERT INTO diagnosis_log
                 (created_at, subject, user_confirmed, paper_types, time_scope,
                  scope_confirmed, question_count, analyzed_count, weak_top, host)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (datetime.now(timezone.utc).isoformat(), subject,
             1 if user_confirmed else 0,
             "|".join(paper_types or []), time_scope,
             1 if scope_confirmed else 0, int(question_count),
             int(analyzed_count),
             json.dumps(list(weak_top or []), ensure_ascii=False), host))
        self.conn.commit()
        return int(cur.lastrowid)

    def diagnosis_logs(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM diagnosis_log ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["weak_top"] = _json_load(d.get("weak_top"), [])
            d["user_confirmed"] = bool(d.get("user_confirmed"))
            d["scope_confirmed"] = bool(d.get("scope_confirmed"))
            d["paper_types"] = [x for x in (d.get("paper_types") or "").split("|")
                                if x]
            out.append(d)
        return out

    # -- 清空（真删） -------------------------------------------------------
    def purge(self, confirm: bool = False) -> dict:
        """真删：数据库 + 图片 + WAL/SHM。必须显式 confirm=True。"""
        if not confirm:
            raise PermissionError("purge 需要 confirm=True 才会执行，防止误删")
        removed = {"db": False, "wal": False, "shm": False, "images": 0}
        self.close()
        for suffix, key in (("-wal", "wal"), ("-shm", "shm")):
            p = Path(str(self.db_path) + suffix)
            if p.exists():
                p.unlink()
                removed[key] = True
        if self.db_path.exists():
            self.db_path.unlink()
            removed["db"] = True
        if self.images_dir.exists():
            for f in self.images_dir.iterdir():
                if f.is_file():
                    f.unlink()
                    removed["images"] += 1
        return removed
