"""P0 验证脚本：确认 zhixuewang 能不能拿到错题数据，并打印**真实**字段。

为什么需要它
------------
`docs/字段核实报告.md` 里已经通过读源码核实了字段**名字**，
但有几件事离线做不到，必须用真实账号跑一次：

  1. difficulty 的实际取值范围是多少？（决定难度闸门是硬约束还是会失效）
  2. standard_answer 到底是文本还是 URL？
  3. get_errorbook 的第二个参数用 paperId 还是 topicSetId 能通？
  4. image_answer 是不是真的返回图片 URL 列表？
  5. 平台的「考点」接口（getExamPointsAndScoringAbility）返回什么？
     —— 这条最关键：如果平台自带知识点，我们的自建标注就是重复劳动。

用法
----
1. 浏览器登录智学网 → 用下面的书签复制 Cookie
2. 把 Cookie 填进环境变量 ZX_COOKIE，或运行时按提示粘贴
3. 运行：
       .venv/Scripts/python tools/verify_p0.py

   加 --dump 会把真实响应写到 out/p0_dump.json（**注意里面有你的作答数据，
   自己决定要不要发出来**；Cookie 本身绝不会被写进文件）。

安全
----
- Cookie 等同于登录凭证：不写文件、不打印完整值、只显示首尾几个字符
- 本脚本只调用「错题相关 + 考试列表」接口
- **不会调用任何同学信息接口**（架构文档第 9 节：最小必要原则）
- 跑完建议在浏览器退出登录，让这个 Cookie 失效
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config import get_config  # noqa: E402

COOKIE_BOOKMARK = (
    "javascript:(function(){function g(){return document.cookie}"
    "function c(t){const a=document.createElement('textarea');a.value=t;"
    "document.body.appendChild(a);a.select();document.execCommand('copy');"
    "document.body.removeChild(a);}c(g());alert('Cookies 已复制！');})();"
)

DUMP: dict = {}


def sep(title: str = "") -> None:
    line = "=" * 68
    print(f"\n{line}")
    if title:
        print(title)
        print(line)


def show(obj, name: str, maxlen: int = 100) -> None:
    if not hasattr(obj, name):
        print(f"  [无此字段] {name}")
        return
    value = getattr(obj, name)
    tname = type(value).__name__
    if isinstance(value, str) and len(value) > maxlen:
        value = value[:maxlen] + f"...(共{len(value)}字)"
    elif isinstance(value, list):
        value = f"list[{len(value)}] {value[:2]}"
    print(f"  {name} ({tname}): {value}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true",
                    help="把真实响应写到 out/p0_dump.json（不含 Cookie）")
    args = ap.parse_args()

    # 延迟导入：没装库时也要能给出人话提示
    try:
        from adapters.zhixuewang import (CookieError, check_cookie_dict,
                                        list_exams, list_subjects, login,
                                        parse_cookie_string, to_student)
        from adapters.zhixuewang import LIB_VERSION
    except ImportError as exc:
        print(f"导入失败：{exc}")
        print("请先执行：.venv/Scripts/python -m pip install -r requirements.txt")
        return 1

    sep("步骤 0 / 获取 Cookie")
    print("如果还没复制 Cookie，把下面这行粘到浏览器地址栏（书签也行）并回车：")
    print(f"  {COOKIE_BOOKMARK}\n")
    cookie = os.environ.get("ZX_COOKIE", "").strip()
    if not cookie:
        # 先看系统凭据管理器里有没有（tools/scan_login.py 存进去的）
        try:
            from adapters.session import get_cookie
            saved = (get_cookie() or "").strip()
            if saved:
                cookie = saved
                print(f"已从系统凭据管理器读到 Cookie（长度 {len(cookie)}，"
                      f"完整值不打印）")
        except Exception as exc:
            print(f"（读取已保存的 Cookie 失败：{type(exc).__name__}: {exc}）")
    if not cookie:
        print("未检测到环境变量 ZX_COOKIE，凭据管理器里也没有。"
              "请粘贴 Cookie 后回车：")
        try:
            cookie = input().strip()
        except EOFError:
            print("无法读取输入。请改用环境变量 ZX_COOKIE，"
                  "或先跑 tools/scan_login.py --from-clipboard。")
            return 1
    if not cookie:
        print("Cookie 为空，退出。")
        return 1

    # --- 用我们自己的稳健解析，而不是库的脆弱实现 ---
    try:
        cookie_dict = parse_cookie_string(cookie)
        warnings = check_cookie_dict(cookie_dict)
    except CookieError as exc:
        print(f"Cookie 解析失败：{exc}")
        return 1
    print(f"解析出 {len(cookie_dict)} 个 Cookie 键：{sorted(cookie_dict)}")
    print(f"只显示首尾：{cookie[:6]}…{cookie[-4:]}（完整值不会打印）")
    for w in warnings:
        print(f"  ⚠ {w}")

    sep("步骤 1 / 登录")
    print(f"库版本：{LIB_VERSION}")
    try:
        account = login(cookie)
        student = to_student(account)
        print("登录成功，学生账号")
    except Exception as exc:
        print(f"登录失败：{type(exc).__name__}: {exc}")
        print("常见原因：Cookie 已过期 / 复制不完整 / 缺少 loginUserName")
        return 1

    sep("步骤 2 / 考试列表")
    exams: list[dict] = []
    try:
        exams = list_exams(student, limit=20)
        for e in exams[:10]:
            print(f"  {e['name']}  id={e['id']}  date={e['date']}"
                  f"{'（近似）' if e['date_is_approx'] else ''}")
        print(f"  共 {len(exams)} 场")
        DUMP["exams"] = exams
    except Exception as exc:
        print(f"获取考试列表失败：{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1
    if not exams:
        print("没有考试记录，无法继续。")
        return 1

    sep("步骤 3 / 学科列表（注意 Subject.id 来自 paperId）")
    exam = exams[0]
    exam_obj = student.get_exam(exam["id"])
    subjects = list_subjects(student, exam_obj)
    for s in subjects:
        print(f"  {s['name']}  paper_id={s['paper_id']}  满分={s['standard_score']}")
    DUMP["subjects"] = subjects
    if not subjects:
        print("没有学科数据，无法继续。")
        return 1

    sep("步骤 4 / 错题本（关键）")
    # 同时准备 topicSetId，用于 paperId 失败时的重试
    topic_set_ids = {}
    try:
        latest = student.get_latest_exam()
        topic_set_ids = {s.name: s.id for s in (getattr(latest, "subjects", []) or [])}
        print(f"（已取到 topicSetId 备用：{topic_set_ids}）")
    except Exception as exc:
        print(f"（取 topicSetId 失败，将只用 paperId：{exc}）")

    subj = None
    topics, used_param = None, None
    attempts: list[tuple[str, str, str]] = []
    any_ok = False
    # 逐个学科试，直到找到**真的有错题**的那一个。
    #
    # 为什么不能只看 subjects[0]（2026-09-24 实测真实账号）：
    # 语文恒定返回 40217「暂时未收集到试题信息」，大概率语文不生成错题本。
    # 而 subjects 的第一项正好是语文 —— 原实现挑中它就判定「两种参数都没成功」
    # 然后直接 return 1，明明数学 / 英语 / 物理都有数据。
    # 结论：不能把「某个学科没数据」当成「整个接口不通」。
    for cand in subjects:
        for param_name, param_val in (("paperId", cand["paper_id"]),
                                      ("topicSetId", topic_set_ids.get(cand["name"]))):
            if not param_val:
                continue
            try:
                got = list(student.get_errorbook(exam["id"], param_val) or [])
            except Exception as exc:
                attempts.append((cand["name"], param_name,
                                 f"{type(exc).__name__}: {str(exc)[:110]}"))
                continue
            any_ok = True
            attempts.append((cand["name"], param_name, f"成功，{len(got)} 题"))
            if got:
                subj, topics, used_param = cand, got, param_name
                break
        if subj:
            break

    print("各学科尝试结果：")
    for name, pname, result in attempts:
        mark = "✅" if result.startswith("成功") else "✗"
        print(f"  {mark} {name:<6} {pname:<11} {result}")

    if subj is None:
        if any_ok:
            print("\n接口是通的，但所有学科都返回 0 道错题 —— 这场考试确实没有错题。")
            return 0
        print("\n所有学科都调用失败。上面列出了每个学科的原始报错，请对照排查。")
        return 1
    print(f"\n→ 后续验证用「{subj['name']}」的 {len(topics)} 道错题（参数：{used_param}）")

    DUMP["errorbook_param_used"] = used_param
    DUMP["errorbook_subject_used"] = subj["name"]
    DUMP["errorbook_attempts"] = attempts

    sep("步骤 5 / 第一道错题的全部字段（本次验证最重要的产出）")
    first = topics[0]
    fields = [f for f in dir(first) if not f.startswith("_")]
    print(f"字段总数：{len(fields)}\n")
    dumped_first = {}
    for f in fields:
        v = getattr(first, f, None)
        if callable(v):
            continue
        show(first, f)
        dumped_first[f] = v if isinstance(v, (str, int, float, bool, list, type(None))) else str(v)
    DUMP["first_topic_fields"] = dumped_first

    sep("步骤 6 / 回答离线核实不了的那 5 个问题")

    # Q1: difficulty 的取值范围
    diffs = [getattr(t, "difficulty", None) for t in topics]
    diffs = [d for d in diffs if d is not None]
    if diffs:
        print(f"Q1 difficulty 取值：min={min(diffs)} max={max(diffs)} "
              f"类型={type(diffs[0]).__name__} 样本={len(diffs)}")
        print(f"   分布：{dict(Counter(diffs).most_common(10))}")
        # 建议必须先**读一眼当前配置**再给。
        #
        # 2026-09-25 实测的缺陷：这里原来无条件打印「请把 config.yaml 的
        # scale 改成 raw」—— 而 config.yaml 早就是 raw / assumed_max=3 了。
        # 使用者看到这条会以为配置还没做，白折腾一轮。
        # 一条「建议做 X」如果不先看 X 做了没有，就只是个噪音源。
        cfg = get_config()
        cur_scale = cfg.difficulty_scale
        cur_max = cfg.assumed_max
        if all(isinstance(d, int) and d > 1 for d in diffs):
            want_max = max(diffs)
            if cur_scale == "raw" and cur_max:
                if want_max <= cur_max:
                    print(f"   → 结论：不是 0~1 刻度，是 0~{cur_max} 的整数刻度。")
                    print(f"     当前 config.yaml 已是 scale=raw / assumed_max={cur_max}，"
                          f"✅ 与实测一致 —— 难度闸门处于**硬约束**状态，无需修改。")
                else:
                    print(f"   → ⚠️ 实测出现 {want_max}，**超过** config 里的 "
                          f"assumed_max={cur_max}。平台可能改了刻度，请重新校准这一项。")
            else:
                print(f"   → 结论：不是 0~1 刻度！当前 config 是 "
                      f"scale={cur_scale!r} / assumed_max={cur_max}。")
                print("     请把 difficulty.scale 改成 raw，assumed_max 填实际最大值，"
                      "难度闸门才会恢复为硬约束。")
        elif max(diffs) <= 1:
            if cur_scale == "0-1":
                print("   → 结论：像 0~1 刻度。当前 config.yaml 已是 scale=0-1，"
                      "✅ 与实测一致 —— 难度闸门已生效，无需修改。")
            else:
                print("   → 结论：像 0~1 刻度。请把 config.yaml 的 "
                      "difficulty.scale 改成 0-1，难度闸门即生效。")
    else:
        print("Q1 difficulty 全是 None —— 平台没给难度，难度闸门将不可用。")
    DUMP["difficulty_values"] = diffs

    # Q2: standard_answer 是文本还是 URL
    sa = getattr(first, "standard_answer", None) or ""
    is_url = sa.strip().lower().startswith("http")
    print(f"Q2 standard_answer 是 URL 吗？ {'是' if is_url else '否'}"
          f"　前 80 字：{sa[:80]!r}")
    print(f"   answer_html 前 80 字：{(getattr(first,'answer_html','') or '')[:80]!r}")
    DUMP["standard_answer_is_url"] = is_url

    # Q3: 哪个参数生效（上面已答）
    print(f"Q3 get_errorbook 生效的参数：{used_param}")

    # Q4: image_answer 是不是图片 URL 列表
    ia = getattr(first, "image_answer", None)
    print(f"Q4 image_answer 类型={type(ia).__name__}，值={str(ia)[:200]}")
    non_empty = [t for t in topics if getattr(t, "image_answer", None)]
    print(f"   {len(non_empty)}/{len(topics)} 道题带学生作答图片"
          f"（如果没有，主观题错因分析就缺关键输入）")
    DUMP["image_answer_sample"] = str(ia)[:500]

    # Q5: 平台有没有考点数据
    sep("步骤 7 / 平台考点接口探测（决定我们自建标注是否重复劳动）")
    try:
        from adapters.zhixue_web import ZhixueWebClient
        client = ZhixueWebClient(cookie)
        for label, fn in (
            ("getExamPointsAndScoringAbility(考点与得分能力)",
             lambda: client.exam_points_and_scoring_ability(exam["id"], subj["paper_id"])),
            ("getSubjectDiagnosis(学科诊断)",
             lambda: client.subject_diagnosis(exam["id"])),
        ):
            try:
                data = fn()
                keys = list(data.keys())[:10] if isinstance(data, dict) else type(data).__name__
                print(f"  ✅ {label} 有响应，顶层键：{keys}")
                print(f"     前 300 字：{json.dumps(data, ensure_ascii=False)[:300]}")
                DUMP.setdefault("platform_diagnosis", {})[label] = (
                    json.dumps(data, ensure_ascii=False)[:4000])
            except Exception as exc:
                print(f"  ✗ {label} 失败：{type(exc).__name__}: {str(exc)[:200]}")
    except Exception as exc:
        print(f"  探测未执行：{exc}")
    print("\n  → 如果 getExamPointsAndScoringAbility 返回了结构化的「考点/知识点」列表，"
          "\n     那么平台的考点数据可以直接替代我们自建的知识点标注；"
          "\n     我们的价值应聚焦在「错因分析」上（平台不做这件事）。")

    sep("步骤 8 / 前 3 道错题摘要")
    for t in topics[:3]:
        print(f"  题{getattr(t,'dis_title_number','?')}  "
              f"得分 {getattr(t,'score','?')}/{getattr(t,'standard_score','?')}  "
              f"难度 {getattr(t,'difficulty','?')}  "
              f"班级得分率 {getattr(t,'class_score_rate','?')}  "
              f"题型 {getattr(t,'answer_type','?')}")

    if args.dump:
        out = ROOT / "out" / "p0_dump.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(DUMP, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"\n已写入 {out}（不含 Cookie；里面有你的作答数据，发之前自己看一眼）")

    sep("完成")
    print("请把步骤 5、6、7 的输出发我，我据此把归一化层的假设换成事实。")
    print("特别是步骤 6 的 Q1（难度刻度）和步骤 7（平台有无考点数据）——")
    print("这两条会直接改变 config.yaml 和整个工具的定位。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
