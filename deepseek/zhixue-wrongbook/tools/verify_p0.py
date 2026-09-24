"""
P0 验证脚本：确认 zhixuewang 库能否拿到错题数据，并打印真实字段。

用途
----
架构文档里对字段的描述来自官方文档，不一定和实际返回完全一致。
本脚本的目的就是拿到「真实返回」，再据此写归一化层。

用法
----
1. pip install zhixuewang
2. 浏览器登录智学网 → 用书签复制 Cookie（见下方 COOKIE_BOOKMARK）
3. 把 Cookie 填进环境变量 ZX_COOKIE，或运行时按提示粘贴
4. python tools/verify_p0.py

安全提示
--------
- Cookie 等同于登录凭证，不要提交到 Git、不要发到群里
- 本脚本不会写任何文件，只打印到终端
- 用完建议在浏览器里退出登录，让这个 Cookie 失效
"""

from __future__ import annotations

import os
import sys
import traceback

COOKIE_BOOKMARK = (
    "javascript:(function(){function g(){return document.cookie}"
    "function c(t){const a=document.createElement('textarea');a.value=t;"
    "document.body.appendChild(a);a.select();document.execCommand('copy');"
    "document.body.removeChild(a);}c(g());alert('Cookies 已复制！');})();"
)


def sep(title: str = "") -> None:
    line = "=" * 60
    print(f"\n{line}")
    if title:
        print(title)
        print(line)


def show(obj, name: str, maxlen: int = 120) -> None:
    """安全打印一个字段，不存在就明确说没有。"""
    if not hasattr(obj, name):
        print(f"  [无此字段] {name}")
        return
    value = getattr(obj, name)
    if isinstance(value, str) and len(value) > maxlen:
        value = value[:maxlen] + f"...(共{len(value)}字)"
    elif isinstance(value, list):
        value = f"list[{len(value)}] {value[:3]}"
    print(f"  {name}: {value}")


def main() -> int:
    try:
        from zhixuewang import login_cookie
    except ImportError:
        print("未安装依赖。请先执行：pip install zhixuewang")
        print(f"(参考书签代码：{COOKIE_BOOKMARK})")
        return 1

    sep("步骤 0 / 获取 Cookie")
    cookie = os.environ.get("ZX_COOKIE", "").strip()
    if not cookie:
        print("未检测到环境变量 ZX_COOKIE。")
        print("请粘贴 Cookie 后回车（输入不会回显到历史记录）：")
        try:
            cookie = input().strip()
        except EOFError:
            print("无法读取输入。请改用环境变量 ZX_COOKIE。")
            return 1
    if not cookie:
        print("Cookie 为空，退出。")
        return 1
    print(f"已获取 Cookie，长度 {len(cookie)}")

    sep("步骤 1 / 登录")
    try:
        account = login_cookie(cookie)
        print(f"登录成功，账号角色: {getattr(account, 'role', '未知')}")
    except Exception as exc:
        print(f"登录失败: {type(exc).__name__}: {exc}")
        print("常见原因：Cookie 已过期 / 复制不完整 / 需要重新登录")
        return 1

    try:
        student = account.to_student()
    except Exception as exc:
        print(f"不是学生账号或转换失败: {exc}")
        return 1

    sep("步骤 2 / 考试列表")
    exam = None
    try:
        exam = student.get_latest_exam()
        print(f"最新考试: {exam.name}  id={exam.id}")
        print(f"  年级: {getattr(exam, 'grade_code', '?')}  期末: {getattr(exam, 'is_final', '?')}")
    except Exception as exc:
        print(f"获取最新考试失败: {type(exc).__name__}: {exc}")
        traceback.print_exc()

    sep("步骤 3 / 学科列表")
    subjects = []
    try:
        subjects = list(student.get_subjects(exam) if exam else student.get_subjects())
        for s in subjects:
            print(f"  {s.name}  id={s.id}  满分={getattr(s, 'standard_score', '?')}")
    except Exception as exc:
        print(f"获取学科失败: {type(exc).__name__}: {exc}")

    if not (exam and subjects):
        print("\n缺少考试或学科信息，无法继续拉错题。")
        return 1

    sep("步骤 4 / 错题本（关键）")
    try:
        topics = student.get_errorbook(exam.id, subjects[0].id)
        print(f"共拿到 {len(topics)} 道错题\n")
    except Exception as exc:
        print(f"获取错题本失败: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1

    if not topics:
        print("错题本为空。可能原因：该考试无错题 / 该学科不支持 / 权限不足")
        return 0

    # 打印全部字段名，这是本次验证最重要的产出
    sep("步骤 5 / 第一道错题的全部字段")
    first = topics[0]
    fields = [f for f in dir(first) if not f.startswith("_")]
    print(f"字段总数: {len(fields)}\n")
    for f in fields:
        if callable(getattr(first, f, None)):
            continue
        show(first, f)

    sep("步骤 6 / 关键字段可用性检查")
    checks = {
        "题干": ["content_html", "topic_img_url"],
        "标准答案": ["standard_answer", "answer_html"],
        "解析": ["analysis_html", "topic_analysis_img_url"],
        "学生答案": ["image_answer"],
        "难度": ["difficulty"],
        "班级得分率": ["class_score_rate"],
        "得分": ["score", "standard_score"],
    }
    for label, names in checks.items():
        hit = [n for n in names if hasattr(first, n)]
        mark = "OK " if hit else "缺失"
        print(f"  [{mark}] {label:8s} -> {hit if hit else '（平台可能不提供）'}")

    sep("步骤 7 / 前 3 道错题摘要")
    for t in topics[:3]:
        num = getattr(t, "dis_title_number", "?")
        got = getattr(t, "score", "?")
        full = getattr(t, "standard_score", "?")
        diff = getattr(t, "difficulty", "?")
        rate = getattr(t, "class_score_rate", "?")
        print(f"  题{num}  得分 {got}/{full}  难度 {diff}  班级得分率 {rate}")

    sep("完成")
    print("请把上面步骤 5 和步骤 6 的输出复制给 AI 助手。")
    print("特别关注：知识点字段是否存在？如果平台已提供，我们的分析模块可以省一部分工作。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
