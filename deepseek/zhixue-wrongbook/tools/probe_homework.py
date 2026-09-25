"""探测「作业报告」链路能不能拿到数据（只读，不写库）。

背景
----
2026-09-25：用户截图显示智学网「成绩报告 → 作业报告 → 历次试卷题目&解析」
按学科列出「午练-八年级-20260922」这类条目。但错题本（errorbook）链路
只同步到两场「周测」，没有这些午练/晚练 —— 说明它们很可能**不在**
getUserExamList 里，而走**作业（homework）**接口。

这类问题不能靠猜。本脚本先探测四件事：

  1. 会话还有效吗
  2. 考试列表（getUserExamList）里到底有哪些条目
  3. 作业列表（getStudentHomeWorkList）里有没有，学科 code 是什么
  4. 若有作业，题目和答案能不能取到（redeploy / hwreport 两条路）

用法
----
    .venv/Scripts/python tools/probe_homework.py
    .venv/Scripts/python tools/probe_homework.py --from-clipboard
    .venv/Scripts/python tools/probe_homework.py --cookie "loginUserName=..."

只读承诺
--------
- 只调 GET / 查询类接口，**不写库、不下载文件、不改任何服务端状态**
- Cookie 完整值不打印、不写明文文件
- 原始响应存 out/_selftest/probe_homework.json（**不含 Cookie**），便于复核
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

HW_LIST_URL = ("https://mhw.zhixue.com/homework_middle_service/"
               "stuapp/getStudentHomeWorkList")
HW_REDEPLOY_URL = "https://mhw.zhixue.com/hw/manage/homework/redeploy"
HW_BANK_URL = "https://mhw.zhixue.com/hwreport/question/listView"

# 学科 code 是猜的，所以全都试一遍，让数据自己说话。
# 库的文档只说了 "01"=语文、"02"=数学、"以此类推"，物理是几号没写。
SUBJECT_CODES = ["-1", "01", "02", "03", "04", "05",
                 "06", "07", "08", "09", "10"]


def _get_cookie(args) -> str | None:
    from adapters import session as session_store

    if args.cookie:
        return args.cookie
    if args.from_clipboard:
        import scan_login
        raw = scan_login._read_clipboard()
        if not raw:
            print("剪贴板里没有文本。先在浏览器 F12 → Console 执行 copy(document.cookie)")
            return None
        session_store.set_cookie(raw)
        print("已从剪贴板读取并存入凭据管理器。")
        return raw
    return session_store.get_cookie()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookie", default="", help="直接给 Cookie 字符串")
    ap.add_argument("--from-clipboard", action="store_true",
                    help="从剪贴板读取（配合浏览器 copy(document.cookie)）")
    ap.add_argument("--out", default="out/_selftest/probe_homework.json")
    args = ap.parse_args()

    cookie = _get_cookie(args)
    if not cookie:
        print("凭据管理器里没有 Cookie。")
        print("请先在你日常浏览器里登录 https://www.zhixue.com ，"
              "F12 → Console → 执行 copy(document.cookie)，")
        print("然后跑：.venv/Scripts/python tools/probe_homework.py --from-clipboard")
        return 2

    import requests
    from adapters.zhixuewang import login, to_student
    from adapters.zhixue_web import ZhixueWebClient, session_check

    raw: dict = {"steps": []}

    # ---- 第 1 步：会话是否有效 ----------------------------------------
    # 用三态探测（valid / expired / unreachable）而不是直接 login()：
    # 库的 login() 在 result=null 时会抛 TypeError（'NoneType' not subscriptable），
    # 那是个看不懂的报错 —— 分不清"Cookie 过期"和"网络不通"。
    print("=" * 68)
    print("① 会话检查")
    print("=" * 68)
    st = session_check(cookie)
    if st.get("status") != "valid":
        print(f"  状态：{st.get('status')}  {st.get('note') or st.get('detail') or ''}")
        if st.get("status") == "expired":
            print()
            print("  → Cookie 已失效，后续探测无法进行。请更新：")
            print("    1) 日常浏览器登录 https://www.zhixue.com")
            print("    2) F12 → Console → copy(document.cookie)")
            print("    3) .venv/Scripts/python tools/scan_login.py --from-clipboard")
        else:
            print()
            print("  → 网络/服务端不通（不是 Cookie 的问题），稍后重试。")
        raw["steps"].append({"step": "session", **st})
        _dump(raw, args.out)
        return 2
    print(f"  会话有效。角色={st.get('role')} 姓名={st.get('name')}")
    account = login(cookie)
    student = to_student(account)

    # ---- 第 2 步：考试列表 --------------------------------------------
    print()
    print("=" * 68)
    print("② 考试列表（getUserExamList）—— 午练/晚练在不在这里？")
    print("=" * 68)
    try:
        client = ZhixueWebClient(cookie)
        exams = student.get_exams() or []
        print(f"  共 {len(exams)} 场考试：")
        rows = []
        for e in exams:
            rows.append({"id": e.id, "name": e.name})
            print(f"    {e.id:24s} {e.name}")
        raw["steps"].append({"step": "exam_list", "count": len(exams),
                             "exams": rows})
    except Exception as exc:
        print(f"  取考试列表失败：{type(exc).__name__}: {exc}")
        raw["steps"].append({"step": "exam_list",
                             "error": f"{type(exc).__name__}: {exc}"})

    # ---- 第 3 步：作业列表（逐个学科 code 试）--------------------------
    print()
    print("=" * 68)
    print("③ 作业列表（getStudentHomeWorkList）—— 换个链路找")
    print("=" * 68)
    try:
        token = student.get_auth_header()["XToken"]
    except Exception as exc:
        print(f"  取 XToken 失败，无法探测作业接口：{type(exc).__name__}: {exc}")
        raw["steps"].append({"step": "homework_list",
                             "error": f"XToken: {type(exc).__name__}: {exc}"})
        _dump(raw, args.out)
        return 1

    hw_found: list[dict] = []
    matrix: list[dict] = []
    for code in SUBJECT_CODES:
        for cs, cs_name in ((0, "未完成"), (1, "已完成")):
            cell = {"subject_code": code, "complete_status": cs_name}
            try:
                r = student._session.get(  # noqa: SLF001  复用库的会话与请求头
                    HW_LIST_URL,
                    params={"pageIndex": 1, "completeStatus": cs,
                            "pageSize": 50, "subjectCode": code,
                            "token": token, "createTime": 0},
                    timeout=25,
                )
                body = r.json()
                res = body.get("result") or {}
                items = res.get("list") or []
                cell["http"] = r.status_code
                cell["error_code"] = body.get("errorCode")
                cell["count"] = len(items)
                if items:
                    titles = []
                    for it in items:
                        t = it.get("hwTitle", "")
                        ty = (it.get("homeWorkTypeDTO") or {})
                        titles.append(f"{t}  [{ty.get('typeName')}"
                                      f"/{ty.get('typeCode')}]")
                        hw_found.append({
                            "subject_code": code, "complete_status": cs,
                            "hwId": it.get("hwId"), "title": t,
                            "classId": it.get("classId"),
                            "type_name": ty.get("typeName"),
                            "type_code": ty.get("typeCode"),
                            "beginTime": it.get("beginTime"),
                        })
                    cell["sample"] = titles[:6]
                    print(f"  code={code:>3s} {cs_name}  → 命中 {len(items)} 条")
                    for t in titles[:6]:
                        print(f"        · {t}")
            except Exception as exc:
                cell["error"] = f"{type(exc).__name__}: {exc}"
            matrix.append(cell)

    hits = [c for c in matrix if c.get("count")]
    if not hits:
        print("  所有学科 code / 完成状态组合都返回 0 条。")
        print("  → 作业接口这条路暂时拿不到（可能是权限、或接口已变）。")
    raw["steps"].append({"step": "homework_list", "matrix": matrix,
                         "found": hw_found})

    # ---- 第 4 步：题目与答案能不能取 -----------------------------------
    print()
    print("=" * 68)
    print("④ 题目与答案（拿第一条命中的作业试）")
    print("=" * 68)
    if not hw_found:
        print("  没有可用作业，跳过。")
    else:
        probe = hw_found[0]
        print(f"  试样：{probe['title']}  "
              f"[{probe['type_name']}/{probe['type_code']}]")
        for label, url, app_id, params in (
            ("redeploy（自由出题）", HW_REDEPLOY_URL, "WNLOIVE",
             {"hwId": probe["hwId"]}),
            ("listView（题库练习）", HW_BANK_URL, "OAXI57PG",
             {"classId": probe["classId"], "hwId": probe["hwId"]}),
        ):
            body = {"base": {"appId": app_id, "appVersion": "",
                             "sysVersion": "v1001", "sysType": "web",
                             "packageName": "com.iflytek.edu.hw",
                             "udid": getattr(student, "id", ""),
                             "expand": {}},
                    "params": params}
            try:
                r = student._session.post(  # noqa: SLF001
                    url, json=body,
                    headers={"Authorization": token}, timeout=25)
                d = r.json()
                res = d.get("result")
                keys = sorted(res.keys()) if isinstance(res, dict) else None
                print(f"    {label:22s} HTTP {r.status_code} "
                      f"errorCode={d.get('errorCode')} result 键={keys}")
                raw["steps"].append({"step": "answer_probe", "which": label,
                                     "http": r.status_code,
                                     "error_code": d.get("errorCode"),
                                     "result_keys": keys,
                                     "sample": _trim(res)})
            except Exception as exc:
                print(f"    {label:22s} 失败：{type(exc).__name__}: {exc}")
                raw["steps"].append({"step": "answer_probe", "which": label,
                                     "error": f"{type(exc).__name__}: {exc}"})

    _dump(raw, args.out)
    print()
    print("=" * 68)
    print(f"原始响应已存 {args.out}（不含 Cookie）")
    print("=" * 68)
    return 0


def _trim(obj, limit: int = 1200):
    """截断原始响应，避免把整份题目塞进 JSON。"""
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + "…(截断)"


def _dump(raw: dict, path: str) -> None:
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
