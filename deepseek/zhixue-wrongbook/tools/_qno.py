"""只读探针：列出各场考试各学科错题的「题号」，用于把全页作答图对到具体题。

平台字段 dis_title_number 会被适配器读出来但**不入库**，所以只能这样拿一次。
不写库、不下载图片、不改任何状态。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.session import get_cookie  # noqa: E402
from adapters.zhixuewang import (  # noqa: E402
    list_exams, list_subjects, login, parse_cookie_string, to_student,
)


def plain(html: str) -> str:
    import re
    txt = re.sub(r"<[^>]+>", "", html or "")
    return re.sub(r"\s+", " ", txt).strip()


def main() -> int:
    cookie = (get_cookie() or "").strip()
    if not cookie:
        print("凭据管理器里没有 Cookie，先跑 tools/scan_login.py --from-clipboard")
        return 1
    student = to_student(login(cookie))
    exams = list_exams(student, limit=10)
    out = {}
    for e in exams:
        exam_obj = student.get_exam(e["id"])
        subjects = list_subjects(student, exam_obj)
        for s in subjects:
            try:
                topics = student.get_errorbook(exam_obj.id, s["paper_id"]) or []
            except Exception as exc:
                out[f"{e['name']}|{s['name']}"] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            rows = []
            for i, t in enumerate(topics, 1):
                rows.append({
                    "seq": i,
                    "no": getattr(t, "dis_title_number", None),
                    "stem": plain(getattr(t, "content_html", ""))[:60],
                    "score": f"{getattr(t, 'student_score', '?')}/{getattr(t, 'standard_score', '?')}",
                })
            out[f"{e['name']}|{s['name']}"] = rows
            print(f"== {e['name']} | {s['name']}  ({len(rows)} 题)")
            for r in rows:
                print(f"   seq={r['seq']:<3} 题号={r['no']:<4} {r['score']:<10} {r['stem']}")
    p = ROOT / "out" / "question_numbers.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
