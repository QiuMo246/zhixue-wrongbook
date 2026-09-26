"""拉取「作业报告」里的练习卷（午练 / 晚练 / 早读）及其题目与解析。

背景
----
2026-09-25：用户在智学网「成绩报告 → 作业报告 → 历次试卷题目&解析」里
看到每天 1~2 张的「午练 / 晚练」。错题本（errorbook）链路里**没有**这些 ——
它们不在 getUserExamList 的默认结果里。

定位过程（省下次的事）：
  学生菜单 getMenu → 成绩报告 = /activitystudy/web-report/index.html
  → 该页 JS 分块 4.js 里写着：
       tabList: [{name:"学情报告", value:"exam"},
                 {name:"作业报告", value:"homework"}]
       getReportExamList: (t) => fetchGet("/zhixuebao/report/exam/getUserExamList", t)

**同一个 getUserExamList 接口，多传一个 `reportType=homework` 就是"作业报告"。**
这是整件事的关键，库（zhixuewang）没有封装，因为它没传 reportType。

三层链路
--------
  ① GET /zhixuebao/report/exam/getUserExamList?reportType=homework
        → 作业列表（examId / examName / examCreateDateTime）
  ② GET /zhixuebao/report/exam/getExamData?examId=…&reportType=homework
        → 该份作业的学科列表（含 topicSetId）
  ③ GET /zhixuebao/report/paper/getLostTopicAndAnalysis?examId=…&paperId=<topicSetId>
        → 题目 + 答案 + 解析 + 学生作答图 + 知识点
        （和错题本链路是同一个接口，项目已在用）

用法
----
    # 只列清单
    .venv/Scripts/python tools/fetch_homework.py

    # 连每份的题目与解析一起拉（慢，约 1 分钟）
    .venv/Scripts/python tools/fetch_homework.py --full

    # 只要物理
    .venv/Scripts/python tools/fetch_homework.py --full --subject 物理

    # 指定输出
    .venv/Scripts/python tools/fetch_homework.py --full --out out/hw.json

只读承诺
--------
- 只调 GET 查询接口，**不写库、不下载文件、不改服务端状态**
- Cookie 走凭据管理器，不打印、不落明文
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.fingerprint import FingerprintStore, check_response  # noqa: E402


def _fp_store() -> FingerprintStore:
    """作业链路的结构指纹库（包二）。

    三个接口都是自己逆出来的，平台改版时最可能先在这里断 ——
    指纹基线挂在主库（和题目数据同生共死，purge 时一起删）。
    ZX_FINGERPRINT_OFF=1 时 check_response 自动只登记不比对。
    """
    db_path = os.environ.get("ZX_DB_PATH", str(ROOT / "data" / "wrongbook.db"))
    conn = sqlite3.connect(db_path)
    return FingerprintStore(conn)


BASE = "https://www.zhixue.com"
LIST_URL = "/zhixuebao/report/exam/getUserExamList"
SUBJECT_URL = "/zhixuebao/report/exam/getExamData"
TOPIC_URL = "/zhixuebao/report/paper/getLostTopicAndAnalysis"
REFERER = "https://www.zhixue.com/activitystudy/web-report/index.html"


def _client():
    """返回 (session, headers, academic_year_params)。"""
    import requests

    from adapters import session as session_store
    from adapters.zhixuewang import parse_cookie_string
    from adapters.zhixue_web import ZhixueWebClient

    raw = session_store.get_cookie()
    if not raw:
        print("凭据管理器里没有 Cookie。请先：")
        print("  1) 日常浏览器登录 https://www.zhixue.com")
        print("  2) F12 → Console → copy(document.cookie)")
        print("  3) .venv/Scripts/python tools/scan_login.py --from-clipboard")
        raise SystemExit(2)

    cli = ZhixueWebClient(raw)
    headers = cli._auth_headers()          # noqa: SLF001
    headers["User-Agent"] = "Mozilla/5.0 Chrome/128.0"
    headers["Referer"] = REFERER

    s = requests.Session()
    s.cookies.update(parse_cookie_string(raw))

    years = cli.academic_years() or []
    y = years[0] if years else {}
    return s, headers, {"startSchoolYear": y.get("beginTime", ""),
                        "endSchoolYear": y.get("endTime", "")}


def fetch_list(s, headers, year: dict, max_pages: int = 40,
               fp: FingerprintStore | None = None) -> list[dict]:
    """① 作业列表（自动翻页）。"""
    out, page = [], 1
    while page <= max_pages:
        r = s.get(BASE + LIST_URL,
                  params={"reportType": "homework", "pageIndex": page,
                          "pageSize": 50, **year},
                  headers=headers, timeout=25)
        d = r.json()
        if fp is not None:
            check_response(fp, "homework.getUserExamList", d,
                           datetime.now(timezone.utc).isoformat())
        if d.get("errorCode") != 0:
            print(f"  取列表失败：errorCode={d.get('errorCode')} "
                  f"{d.get('errorInfo')}")
            break
        res = d.get("result") or {}
        batch = res.get("examList") or []
        out.extend(batch)
        if not res.get("hasNextPage") or not batch:
            break
        page += 1
    return out


def fetch_subjects(s, headers, year, exam_id: str,
                   fp: FingerprintStore | None = None) -> list[dict]:
    """② 某份作业的学科列表。"""
    d = s.get(BASE + SUBJECT_URL,
              params={"examId": exam_id, "reportType": "homework", **year},
              headers=headers, timeout=25).json()
    if fp is not None:
        check_response(fp, "homework.getExamData", d,
                       datetime.now(timezone.utc).isoformat())
    return ((d.get("result") or {}).get("subjects")) or []


def fetch_topics(s, headers, exam_id: str, paper_id: str,
                 fp: FingerprintStore | None = None) -> list[dict]:
    """③ 某学科在本次作业里的题目（含答案与解析）。"""
    d = s.get(BASE + TOPIC_URL,
              params={"examId": exam_id, "paperId": paper_id},
              headers=headers, timeout=25).json()
    if fp is not None:
        check_response(fp, "homework.getLostTopicAndAnalysis", d,
                       datetime.now(timezone.utc).isoformat())
    res = d.get("result") or {}
    return ((res.get("wrongTopicAnalysis") or {}).get("topicList")) or []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true",
                    help="连题目与解析一起拉（慢）")
    ap.add_argument("--subject", default="",
                    help="只拉这个学科，如 物理")
    ap.add_argument("--out", default="out/homework_report.json")
    args = ap.parse_args()

    s, headers, year = _client()
    fp = _fp_store()          # 结构指纹（包二）：漂移即拦截，不采错数据
    print(f"学年参数: {year}")
    print()

    items = fetch_list(s, headers, year, fp=fp)
    print(f"① 作业列表：{len(items)} 份")
    if not items:
        print("  没拿到任何作业。可能 Cookie 失效或该校未启用作业报告。")
        return 1

    if not args.full:
        for it in items:
            day = time.strftime("%Y-%m-%d",
                                time.localtime(it["examCreateDateTime"] / 1000))
            print(f"   {day}  {it.get('examName')}")
        _save([{"examId": i["examId"], "examName": i["examName"],
                "date": time.strftime("%Y-%m-%d", time.localtime(
                    i["examCreateDateTime"] / 1000))} for i in items], args.out)
        return 0

    print()
    print("② 逐份取学科与题目（含答案、解析）…")
    rows, total = [], 0
    for n, it in enumerate(items, 1):
        eid = it["examId"]
        day = time.strftime("%Y-%m-%d",
                            time.localtime(it["examCreateDateTime"] / 1000))
        try:
            subs = fetch_subjects(s, headers, year, eid, fp=fp)
        except Exception as exc:
            print(f"  {n:2d}. {it.get('examName')} 取学科失败：{exc}")
            continue
        per = []
        for sb in subs:
            if args.subject and sb.get("subjectName") != args.subject:
                continue
            try:
                tl = fetch_topics(s, headers, eid, sb.get("topicSetId"), fp=fp)
            except Exception as exc:
                tl = []
                print(f"       {sb.get('subjectName')} 取题失败：{exc}")
            per.append({"subject": sb.get("subjectName"),
                        "code": sb.get("subjectCode"),
                        "topicSetId": sb.get("topicSetId"),
                        "topic_count": len(tl), "topics": tl})
            total += len(tl)
            time.sleep(0.15)          # 别把服务端打急
        rows.append({"examId": eid, "examName": it["examName"], "date": day,
                     "subjects": per})
        desc = ", ".join(f"{p['subject']}{p['topic_count']}题" for p in per) or "（已跳过）"
        print(f"  {n:2d}. {day}  {it['examName']:26s} {desc}")

    _save(rows, args.out)
    print()
    print(f"合计题目：{total} 道")
    return 0


def _save(rows, path: str) -> None:
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已写入 {p}  ({p.stat().st_size:,} B)")


if __name__ == "__main__":
    raise SystemExit(main())
