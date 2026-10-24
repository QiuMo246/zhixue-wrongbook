# -*- coding: utf-8 -*-
"""语文错题采集（走答题卡 checksheet 通道）。

【为什么单独写这个工具】
智学网的「错题本」接口 getLostTopicAndAnalysis 对语文恒定返回
`40217 暂时未收集到试题信息,无法查看`（见 adapters/zhixuewang.py 的
ERR_NO_TOPIC）。此前据此判断「学校没录语文错题」——**这个结论是错的**。

2026-10-18 实测发现：语文的数据在**另一条接口**里 ——
`GET_ORIGINAL_URL`（/zhixuebao/report/checksheet/）。

  错题本接口：errorCode=40217，result=''          ← 空
  答题卡接口：errorCode=0，result 里有：
      score                 总分（实测 79.0，与卷面一致）
      sheetImages           答题卡扫描图（每场 2 张）
      sheetDatas.userAnswerRecordDTO.answerRecordDetails
          → 每道题的 dispTitle(题号) / score(得分) /
            standardScore(满分) / isCorrect(对错) / answer(作答)

所以语文不是「没有错题」，而是「错题藏在答题卡通道里」。

【和其他学科的区别，必须知道】
1. 这里**只有题号和得分**，没有题干、没有标准答案、没有解析。
   要知道错在哪，得配合 sheetImages 里对应的扫描图去看。
2. 语文没有 40217 之外的结构化兜底：如果某场考试 checksheet 也返回
   空 result（老师没上传扫描件），那就是真没有，别硬猜。
3. `isCorrect=false` 包含「部分得分」，不全是 0 分。分析时要看
   score/standardScore 的比例，别一律当全错。

【用法】
    python tools/fetch_yuwen.py                  # 最近 10 场有语文的考试
    python tools/fetch_yuwen.py --limit 3        # 只看最近 3 场
    python tools/fetch_yuwen.py --download       # 顺便下载扫描图
    python tools/fetch_yuwen.py --json           # 输出 JSON

输出目录：out/yuwen/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters import session as session_store          # noqa: E402
from adapters import zhixuewang as zxw                 # noqa: E402
from zhixuewang.student.urls import Url                # noqa: E402

SUBJECT = "语文"


def _student():
    cookie = session_store.get_cookie()
    if not cookie:
        raise SystemExit("还没有登录。先在专用浏览器里登录，再运行 "
                         "tools/login.py")
    return zxw.to_student(zxw.login(cookie))


def _as_json(v):
    """接口里有些字段是 JSON 编码的字符串，有些已经是对象。统一拆开。"""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


def fetch_sheet(student, exam, subject) -> dict | None:
    """取一场考试某学科的答题卡数据。拿不到返回 None。"""
    r = student._session.get(
        Url.GET_ORIGINAL_URL,
        params={"examId": exam.id, "paperId": subject.id},
        headers=student.get_auth_header(),
    )
    try:
        data = r.json()
    except Exception:
        return None
    if data.get("errorCode") != 0 or not data.get("result"):
        return None

    res = data["result"]
    sheet = _as_json(res.get("sheetDatas")) or {}
    rec_dto = sheet.get("userAnswerRecordDTO") or {}
    records = rec_dto.get("answerRecordDetails") or []

    items = []
    for d in records:
        score = float(d.get("score") or 0)
        full = float(d.get("standardScore") or 0)
        items.append({
            "no": d.get("dispTitle"),
            "score": score,
            "full_score": full,
            "is_correct": bool(d.get("isCorrect")),
            # 「错了」的定义：不是全对。部分得分也算错题候补，
            # 但会用 partial 标出来，避免把 18/20 当全错。
            "partial": (not d.get("isCorrect")) and score > 0 and full > 0 and score < full,
            "answer": d.get("answer"),
            "answer_type": d.get("answerType"),
        })

    imgs = _as_json(res.get("sheetImages")) or []
    return {
        "exam_name": getattr(exam, "name", ""),
        "exam_id": exam.id,
        "score": res.get("score"),
        "full_score": res.get("standardScore"),
        "show_single_topic_score": res.get("showSingleTopicScore"),
        "sheet_images": imgs if isinstance(imgs, list) else [],
        "items": items,
    }


def download(images: list[str], outdir: Path, prefix: str) -> list[str]:
    """下载扫描图。走直连（OSS 不走本机代理，否则容易卡）。"""
    outdir.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    saved = []
    for i, url in enumerate(images):
        fn = outdir / f"{prefix}_{i}.jpg"
        try:
            with opener.open(url, timeout=30) as fh:
                fn.write_bytes(fh.read())
            saved.append(str(fn))
        except Exception as exc:
            print(f"    ! 第 {i} 张下载失败：{type(exc).__name__}: {exc}")
    return saved


def main() -> int:
    ap = argparse.ArgumentParser(description="语文错题（答题卡通道）")
    ap.add_argument("--limit", type=int, default=10, help="最多处理几场考试")
    ap.add_argument("--download", action="store_true", help="下载答题卡扫描图")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    student = _student()
    exams = list(student.get_exams() or [])
    print(f"考试总数 {len(exams)}，开始找有「{SUBJECT}」的场次……\n")

    results = []
    seen = 0
    for exam in exams:
        if seen >= args.limit:
            break
        subs = [s for s in (student.get_subjects(exam) or [])
                if getattr(s, "name", "") == SUBJECT]
        if not subs:
            continue
        seen += 1
        sheet = fetch_sheet(student, exam, subs[0])
        if sheet is None:
            print(f"[{getattr(exam, 'name', '?')}] 无答题卡数据（老师可能没上传扫描件）")
            continue

        items = sheet["items"]
        wrong = [i for i in items if not i["is_correct"]]
        got = sum(i["score"] for i in items)
        full = sum(i["full_score"] for i in items)
        sheet["wrong_count"] = len(wrong)
        print(f"[{sheet['exam_name']}] 总分 {sheet['score']} | "
              f"题 {len(items)} 道 | 错 {len(wrong)} 道 | 逐题合计 {got:.1f}/{full:.1f}")
        if sheet["sheet_images"] and args.download:
            safe = sheet["exam_name"].replace("/", "_").replace("\\", "_")[:24]
            sheet["saved_images"] = download(
                sheet["sheet_images"], ROOT / "out" / "yuwen", safe)
            print(f"    扫描图 {len(sheet['saved_images'])} 张 → out/yuwen/")
        results.append(sheet)

    outdir = ROOT / "out"
    outdir.mkdir(exist_ok=True)
    (outdir / "yuwen_wrongbook.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        total_wrong = sum(r["wrong_count"] for r in results)
        print(f"\n共 {len(results)} 场，错题条目 {total_wrong} 个")
        print(f"明细已写入 out/yuwen_wrongbook.json")
        print("\n提醒：这里只有题号和得分，没有题干/标准答案。"
              "要看具体错在哪，用 --download 拿扫描图对照。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
