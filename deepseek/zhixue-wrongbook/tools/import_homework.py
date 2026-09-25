"""把 fetch_homework.py 拉到的作业错题导入错题本库（补上「作业 → 错题本」的断桥）。

背景
----
2026-09-25 学生视角实测发现：`tools/fetch_homework.py` 能把午练/晚练的错题
拉成 `out/homework_report.json`，但数据**到此为止**——没有入库这一步，
于是 `zx_diagnosis` / `zx_profile` / `zx_export_paper` 全都看不到作业错题，
「本周的午练」诊断只会得到 no_data_in_scope。

本工具就是中间那座桥：
    homework_report.json（作业接口的原始 JSON）
      → 逐题转成通道内部 raw dict（字段与 adapters/zhixuewang.topic_to_raw
        的产出**逐字段对齐**，作业接口③ getLostTopicAndAnalysis 和错题本
        是同一个接口，返回结构一致，见 skill 场景 7）
      → normalize_question(source="api-homework")
      → store.upsert（指纹去重、派生字段保护等入库规则全部复用）

用法
----
    .venv/Scripts/python tools/import_homework.py                 # 导入 out/homework_report.json
    .venv/Scripts/python tools/import_homework.py --subject 物理   # 只要物理
    .venv/Scripts/python tools/import_homework.py --file out/hw.json --no-images

注意
----
- **会写真实的 data/wrongbook.db**（这正是它的用途），跑前可自行备份。
- 重复导入是安全的：upsert 按指纹去重，已提交的分析结果不会被清掉。
- 不联网（图片已在 fetch_homework 阶段给出 URL，下载发生在本工具，
  属于拉取行为而非查询；--no-images 可跳过）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.parsers.normalize import download_images, normalize_question
from adapters.parsers.zhixue_export import ANSWER_TYPE_MEANING, qtype_from_answer_type
from adapters.zhixuewang import SOURCE_VERSION, _as_url_list, _looks_like_url
from core.config import get_config
from core.store import Store

SOURCE = "api-homework"


def topic_to_raw_hw(t: dict, subject_name: str, exam_name: str, exam_date: str,
                    images_dir: Path, images_prefix: str,
                    download: bool = True, config=None) -> tuple[dict, dict]:
    """作业接口的一道题（原始 JSON dict）→ 通道内部 raw dict。

    字段对齐 adapters/zhixuewang.topic_to_raw（错题本链路），差异只有两点：
    - 输入是 dict（接口原样），不是库的 TopicRecord 对象
    - 作答图兜底多一路 relativeImageAnswers（作业接口实测可能只给这个）
    """
    config = config or get_config()
    notes: dict = {}

    # --- 题干 ---
    stem_html = t.get("contentHtml") or t.get("content") or ""
    stem_imgs = _as_url_list(t.get("topicImgUrl"))
    images: list[str] = []
    if stem_imgs:
        if download:
            ok, failed = download_images(stem_imgs, images_dir,
                                         f"{images_prefix}_stem")
            images.extend(ok)
            if failed:
                notes.setdefault("image_failed", []).extend(failed)
        else:
            images.extend(stem_imgs)

    # --- 学生作答 ---
    ans_imgs = _as_url_list(t.get("imageAnswer"))
    if not ans_imgs:
        ans_imgs = _as_url_list(t.get("relativeImageAnswers"))
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
    if ans_imgs and download and not student_images:
        notes["student_images_download_failed"] = ans_imgs

    # --- 标准答案：与错题本链路相同，standardAnswer 实测多为图片 URL ---
    raw_standard = t.get("standardAnswer") or ""
    answer_html = t.get("answerHtml") or ""
    if _looks_like_url(raw_standard):
        standard = answer_html or None
        notes["standard_answer_is_url"] = raw_standard
    else:
        standard = raw_standard or answer_html or None

    # --- 难度：difficultyValue 是 int，走 config 的刻度归一化 ---
    diff_raw = t.get("difficultyValue")
    difficulty, diff_scale = config.normalize_difficulty(diff_raw)
    if diff_scale == "unknown" and diff_raw is not None:
        notes["difficulty_scale_unknown"] = diff_raw

    # --- 题型 ---
    answer_type = t.get("answerType") or ""
    qtype = qtype_from_answer_type(answer_type, stem_html, standard or "")
    meaning = ANSWER_TYPE_MEANING.get(str(answer_type).strip().lower())
    if meaning:
        notes.setdefault("answer_type_decoded", meaning)

    raw = {
        "subject": subject_name,
        "exam_name": exam_name,
        "exam_date": exam_date,
        "grade": "八年级",
        "stem_html": stem_html,
        "images": images,
        "qtype": qtype,
        "standard": standard,
        "analysis_html": t.get("analysisHtml") or None,
        "student_text": None,
        "student_images": student_images,
        "difficulty": difficulty,
        "difficulty_scale": diff_scale,
        "class_score_rate": _safe_float(t.get("classScoreRate")),
        "score_got": _safe_float(t.get("score")),
        "score_full": _safe_float(t.get("standardScore")),
    }
    if _looks_like_url(raw_standard):
        raw["standard_answer_url"] = raw_standard
    return raw, notes


def _safe_float(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="out/homework_report.json",
                    help="fetch_homework.py 的输出文件")
    ap.add_argument("--subject", default="", help="只导入这个学科，如 物理")
    ap.add_argument("--no-images", action="store_true",
                    help="不下载图片，只入库文本字段")
    args = ap.parse_args()

    path = ROOT / args.file
    if not path.exists():
        print(f"找不到 {path}。先跑：.venv/Scripts/python tools/fetch_homework.py --full")
        return 2

    rows = json.loads(path.read_text(encoding="utf-8"))
    config = get_config()
    images_dir = config.path("images_dir")

    report = {"source": SOURCE, "added": 0, "updated": 0, "failed": 0,
              "notes": [], "errors": []}
    total = 0
    with Store() as store:
        for row in rows:
            exam_name = row.get("examName") or "未知作业"
            exam_date = row.get("date")
            for sb in row.get("subjects") or []:
                subject = sb.get("subject") or "未知学科"
                if args.subject and subject != args.subject:
                    continue
                topics = sb.get("topics") or []
                if not topics:
                    continue
                log_id = store.log_sync_start(SOURCE, subject, exam_name)
                added = updated = failed = 0
                for i, t in enumerate(topics, 1):
                    total += 1
                    prefix = f"hw_{(row.get('examId') or '0000')[:8]}_{subject}_{i:03d}"
                    try:
                        raw, notes = topic_to_raw_hw(
                            t, subject, exam_name, exam_date,
                            images_dir, prefix,
                            download=not args.no_images, config=config)
                        q = normalize_question(
                            raw, source=SOURCE, source_version=SOURCE_VERSION,
                            seq=i)
                        res = store.upsert(q)
                    except Exception as exc:
                        failed += 1
                        report["failed"] += 1
                        report["errors"].append(
                            {"exam": exam_name, "subject": subject,
                             "no": t.get("disTitleNumber", i),
                             "error": f"{type(exc).__name__}: {exc}"})
                        continue
                    if res == "added":
                        added += 1
                        report["added"] += 1
                    else:
                        updated += 1
                        report["updated"] += 1
                    if notes:
                        report["notes"].append(
                            {"exam": exam_name, "subject": subject,
                             "no": t.get("disTitleNumber", i), **notes})
                store.log_sync_end(log_id, added=added,
                                   updated=updated, failed=failed)
                print(f"  {exam_name} · {subject}: "
                      f"新增 {added}，更新 {updated}，失败 {failed}")

    print()
    print(f"合计处理 {total} 道：新增 {report['added']}，"
          f"更新 {report['updated']}，失败 {report['failed']}")
    if report["errors"]:
        print("错误明细（前 10 条）：")
        for e in report["errors"][:10]:
            print(f"  - {e['exam']} / {e['subject']} 第{e['no']}题: {e['error']}")
    return 0 if not report["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
