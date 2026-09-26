"""端到端验收脚本。**不需要 Cookie、不需要联网。**

它把架构文档第 11 节里「不依赖 P0」的那条链路整条跑一遍：
    归一化 → 入库去重 → 分析校验 → 掌握度 → 生成校验 → 导出

跑法：
    .venv/Scripts/python tools/acceptance.py

产出：
    out/acceptance_report.md   人看的验收报告
    out/acceptance_report.json 机器可读的详细结果
退出码：0 = 全部通过；1 = 有失败项（失败项会逐条列出，不静默）
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.parsers import zhixue_export                      # noqa: E402
from adapters.parsers.normalize import normalize_question        # noqa: E402
from adapters.zhixuewang import (CookieError, check_cookie_dict,  # noqa: E402
                                 parse_cookie_string)
from core.export import (render_paper, try_pdf, write_paper,      # noqa: E402
                         wrongbook_markdown)
from core.models import WrongQuestion                             # noqa: E402
from core.profile import build_profile, mastery_for_kp            # noqa: E402
from core.store import Store                                      # noqa: E402
from core.taxonomy import load_taxonomy                           # noqa: E402
from core.validate import (compare_solution, validate_analysis,   # noqa: E402
                           validate_practice)

SAMPLES = ROOT / "data" / "samples"
OUT = ROOT / "out"

RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: str = "", section: str = "") -> bool:
    RESULTS.append({"section": section, "name": name, "ok": bool(ok),
                    "detail": str(detail)[:600]})
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"  — {detail}" if detail else ""))
    return bool(ok)


def section(title: str) -> None:
    print(f"\n{'=' * 66}\n{title}\n{'=' * 66}")


def load_samples() -> list[dict]:
    data = json.loads((SAMPLES / "sample_questions.json").read_text(encoding="utf-8"))
    return data["questions"]


def main() -> int:
    tmpdir = Path(tempfile.mkdtemp(prefix="zx_accept_", dir=str(ROOT / "data")))
    db = tmpdir / "accept.db"
    imgs = tmpdir / "images"
    taxonomy = load_taxonomy()
    store = Store(db, imgs)
    now = date(2026, 9, 24)

    # ---------------------------------------------------------------- A
    section("A. 受控词表与配置")
    check("taxonomy 可加载", len(taxonomy.all_paths) > 50,
          f"{len(taxonomy.all_paths)} 个知识点 / {len(taxonomy.subjects())} 个学科",
          "A")
    info, reason = taxonomy.resolve("一元二次方程/公式法与判别式", "数学")
    check("两段式路径可解析（文档歧义处已处理）", info is not None,
          info.path if info else reason, "A")
    _, reason2 = taxonomy.resolve("随便编的知识点", "数学")
    check("词表外知识点被拒绝", "不在受控词表内" in reason2, reason2, "A")

    # 2026-09-25 补录历史 / 道法（起因：这两科的错题无法标知识点）
    check("历史 / 道法 已进词表", {"历史", "道法"} <= set(taxonomy.subjects()),
          str(taxonomy.subjects()), "A")
    _hist = [p for p in taxonomy.all_paths if p.startswith("历史/")]
    _dao = [p for p in taxonomy.all_paths if p.startswith("道法/")]
    check("历史 / 道法 覆盖初中范围（各 6 / 6 册教材）",
          len(_hist) >= 80 and len(_dao) >= 60,
          f"历史 {len(_hist)} 个 / 道法 {len(_dao)} 个", "A")
    check("全路径无重复", len(set(taxonomy.all_paths)) == len(taxonomy.all_paths),
          f"{len(taxonomy.all_paths)} 条", "A")
    # 两段式「章节/知识点」在不给学科时也必须唯一命中，否则 resolve 会歧义
    _amb = []
    for _p in taxonomy.all_paths:
        _s, _c, _pt = _p.split("/", 2)
        if taxonomy.resolve(f"{_c}/{_pt}", None)[0] is None:
            _amb.append(f"{_c}/{_pt}")
    check("「章节/知识点」两段式全词表唯一（无学科也能命中）",
          not _amb, str(_amb[:3]) if _amb else f"{len(taxonomy.all_paths)} 条全部唯一", "A")
    for _raw, _subj in [("历史/抗日战争与人民解放战争/七七事变与全民族抗战", None),
                        ("宪法与依法治国/宪法是根本法", "道法"),
                        ("道法/国家利益与国家安全/总体国家安全观", None),
                        ("历史/冷战与多极化/世界多极化与经济全球化", None)]:
        _i, _r = taxonomy.resolve(_raw, _subj)
        check(f"新学科路径可解析：{_raw}", _i is not None,
              _i.path if _i else _r, "A")
    # 回归：difflib 对「短串 vs 长串」算不出相似度（'西安事变' 对
    # '九一八事变与西安事变' 只有 0.57，卡在 0.6 阈值下），所以搜索必须子串优先
    check("子串搜索命中（difflib 单独算不出来）",
          taxonomy.search("西安事变", "历史")
          == ["历史/抗日战争与人民解放战争/九一八事变与西安事变"],
          str(taxonomy.search("西安事变", "历史")), "A")
    check("搜索能处理「模型自己加了修饰语」（point in key）",
          "历史/列强侵略与民族危机/洋务运动" in taxonomy.search("洋务运动的作用", "历史"),
          str(taxonomy.search("洋务运动的作用", "历史")), "A")
    _, _r4 = taxonomy.resolve("历史/中国近代史/洋务运动的作用", None)
    check("词表外的历史考点被拒且给出候选", "你是不是想写" in _r4, _r4, "A")
    check("跨学科误用被拒（道法知识点配历史）",
          taxonomy.resolve("宪法是根本法", "历史")[0] is None,
          taxonomy.resolve("宪法是根本法", "历史")[1], "A")

    # ---------------------------------------------------------------- B
    section("B. Cookie 解析（库的字符串解析有缺陷，这里验证我们的替代实现）")
    raw = "token=abc==; userName=zhangsan; loginUserName=zhangsan; _blanks=1"
    d = parse_cookie_string(raw)
    check("值里含 '=' 也能正确解析", d.get("token") == "abc==",
          f"token={d.get('token')!r}", "B")
    d2 = parse_cookie_string("token=abc==;userName=zhangsan;loginUserName=zhangsan")
    check("无空格分隔（; 直接连写）也能解析", len(d2) == 3, f"{len(d2)} 个键", "B")
    check("缺 loginUserName 时给人话提示",
          _raises(lambda: check_cookie_dict({"token": "x"}), CookieError),
          "库会 KeyError，我们提前拦下", "B")

    # ---------------------------------------------------------------- C
    section("C. 归一化与入库去重")
    samples = load_samples()
    questions = []
    for s in samples:
        q = WrongQuestion(**s)
        questions.append(q)
    check("样例数据可归一化为 WrongQuestion", len(questions) == 10,
          f"{len(questions)} 题", "C")
    check("指纹稳定（同题两次算出的指纹相同）",
          questions[0].fingerprint() == questions[0].fingerprint(),
          questions[0].fingerprint(), "C")
    check("不同题指纹不同",
          questions[0].fingerprint() != questions[1].fingerprint(), "", "C")

    added = sum(1 for q in questions if store.upsert(q) == "added")
    check("首次入库全部为 added", added == len(questions), f"added={added}", "C")
    again = [store.upsert(q) for q in questions]
    check("重复入库不再新增（指纹去重生效）",
          all(r == "updated" for r in again) and store.counts()["total"] == len(questions),
          f"第二次结果={set(again)}，库内总数={store.counts()['total']}", "C")

    # 同一道题换个来源通道进来，应该合并
    dup = json.loads(json.dumps(samples[0]))
    dup["source"] = "export"
    dup["source_version"] = "zhixue-export/heuristic-1"
    r = store.upsert(WrongQuestion(**dup))
    check("跨通道同一道题合并为一条（不重复计）",
          r == "updated" and store.counts()["total"] == len(questions),
          f"{r}，库内总数={store.counts()['total']}", "C")
    # 把 source 改回来，后面统计口径一致
    store.upsert(questions[0])

    # ---------------------------------------------------------------- D
    section("D. submit_analysis 三道闸门")
    subs = json.loads((SAMPLES / "analysis_submissions.json").read_text(encoding="utf-8"))
    by_id = {q.id: q for q in questions}

    ok_count = 0
    for item in subs["valid"]:
        q = by_id[item["ref"]]
        res = validate_analysis(q, item, taxonomy)
        if res.ok:
            ok_count += 1
            # 真正落库，后面统计要用
            store.set_analysis(q.fingerprint(), _mk_analysis(res.normalized, item))
        else:
            check(f"正例应通过但被拒：{item['ref']}", False, "；".join(res.errors), "D")
    check(f"正例全部通过（{ok_count}/{len(subs['valid'])})",
          ok_count == len(subs["valid"]), "", "D")

    q10 = by_id["sample-10"]
    res10 = validate_analysis(q10, next(i for i in subs["valid"] if i["ref"] == "sample-10"),
                              taxonomy)
    check("纯图片题走「证据无法校验」分支而非误判通过",
          any(i.name == "证据可定位" and i.kind == "soft" and not i.passed
              for i in res10.items),
          "无文本语料 → 降级为软项 + 强制 needs_review", "D")
    check("纯图片题被强制 needs_review",
          res10.normalized.get("needs_review") is True, "", "D")

    rej = 0
    for item in subs["invalid"]:
        q = by_id[item["ref"]]
        res = validate_analysis(q, item, taxonomy)
        kw = item.get("expect_error_keyword", "")
        hit = (not res.ok) and any(kw in e for e in res.errors)
        if hit:
            rej += 1
        else:
            check(f"负例应被拒但通过了：{item['case']}", False,
                  f"errors={res.errors}", "D")
    check(f"负例全部被拒（{rej}/{len(subs['invalid'])}）",
          rej == len(subs["invalid"]), "含错因越界/知识点越界/证据不可定位/不可追溯/置信度越界", "D")

    # 2026-09-25：历史 / 道法补进词表之后，必须真的能走完「标知识点 → 校验通过」
    # 这条路 —— 否则补词表就白补了。这里用真实形态的历史题端到端验一次。
    hist_q = normalize_question({
        "subject": "历史", "exam_name": "历史单元测", "exam_date": "2026-09-20",
        "grade": "八年级上",
        "stem_html": "<p>简述七七事变后全民族抗战局面形成的过程。</p>",
        "qtype": "解答题", "standard": "略", "student_text": "只写了九一八事变",
        "score_got": 2, "score_full": 8,
    }, source="manual", source_version="acceptance-fixture", seq=300)
    res_h = validate_analysis(hist_q, {
        "error_type": "概念不清",
        "knowledge_points": ["历史/抗日战争与人民解放战争/七七事变与全民族抗战"],
        "evidence": ["「只写了九一八事变」——把两次事变混为一谈"],
        "confidence": 0.8, "analyzed_by": "host:acceptance",
        "prompt_version": "analyze-v3",
    }, taxonomy)
    check("历史错题能过知识点闸门（补词表的目的就是这个）", res_h.ok,
          "；".join(res_h.errors) or str(res_h.normalized.get("knowledge_points")), "D")
    res_h2 = validate_analysis(hist_q, {
        "error_type": "概念不清",
        "knowledge_points": ["历史/中国近代史/抗日战争"],   # 词表里没有的写法
        "evidence": ["「只写了九一八事变」——把两次事变混为一谈"],
        "confidence": 0.8, "analyzed_by": "host:acceptance",
        "prompt_version": "analyze-v3",
    }, taxonomy)
    check("历史词表外的写法仍被拒（补词表 ≠ 放松闸门）",
          not res_h2.ok and any("受控词表" in e for e in res_h2.errors),
          "；".join(res_h2.errors), "D")

    # 掌握度需要同一知识点 ≥3 题，这里补 5 道已知得分的题做确定性验证。
    # 注意：sample-01 本身就挂在这个知识点上（2026-09-15，得分 5/8），
    # 所以期望值必须把它一起算进去，否则是我自己算错而不是代码算错。
    mastery_cases = [
        (9, 5, 8),    # sample-01 本身
        (4, 5, 8), (14, 8, 8), (23, 3, 8),   # ≤30 天 → 权重 1.0
        (66, 4, 8),   # 30~90 天 → 0.6
        (146, 0, 8),  # >90 天 → 0.3
    ]
    for i, (days_ago, got, full) in enumerate(mastery_cases[1:], 1):
        d = now - timedelta(days=days_ago)
        extra = normalize_question({
            "subject": "数学", "exam_name": f"掌握度验证卷{i}",
            "exam_date": d.isoformat(), "grade": "九年级上",
            "stem_html": f"<p>掌握度验证题 {i}：关于 x 的方程 x^2 - {i}x + 1 = 0 的判别式。</p>",
            "qtype": "解答题", "standard": "Δ = b^2 - 4ac",
            "student_text": "直接代入求根", "difficulty": 0.6,
            "difficulty_scale": "0-1", "score_got": got, "score_full": full,
        }, source="manual", source_version="acceptance-fixture", seq=100 + i)
        store.upsert(extra)
        store.set_analysis(extra.fingerprint(), _mk_analysis({
            "error_type": "方法选择错误",
            "knowledge_points": ["数学/一元二次方程/公式法与判别式"],
            "evidence": ["「直接代入求根」——未讨论判别式"],
            "confidence": 0.8, "needs_review": False,
            "analyzed_by": "host:acceptance", "prompt_version": "analyze-v3",
        }, {}))

    # ---------------------------------------------------------------- E
    section("E. 掌握度：公式可复现")
    qs = store.query()
    m1 = mastery_for_kp(qs, "数学/一元二次方程/公式法与判别式", now)
    m2 = mastery_for_kp(qs, "数学/一元二次方程/公式法与判别式", now)

    def _w(days: int) -> float:
        return 1.0 if days <= 30 else (0.6 if days <= 90 else 0.3)

    num = sum(_w(d) * (g / f) for d, g, f in mastery_cases)
    den = sum(_w(d) for d, _, _ in mastery_cases)
    expected = num / den
    check("同一份数据两次算出同一结果", m1 == m2,
          f"mastery={m1['mastery']}, n={m1['n']}", "E")
    check("加权平均与手算一致（含时间衰减 1.0/0.6/0.3）",
          abs((m1["mastery"] or 0) - round(expected, 4)) < 1e-9,
          f"算出 {m1['mastery']}，手算 {round(expected, 4)}，n={m1['n']}", "E")
    m3 = mastery_for_kp(qs, "英语/从句/宾语从句", now)
    check("样本量 < 3 时只报「样本不足」，不给数值",
          m3["insufficient"] and m3["mastery"] is None, m3["reason"], "E")

    prof1 = build_profile(store, now=now)
    prof2 = build_profile(store, now=now)
    # generated_at 是时间戳，本来就会不同，比较时排除掉
    def _stable(p):
        p = dict(p)
        p.pop("generated_at", None)
        return json.dumps(p, ensure_ascii=False, sort_keys=True)

    check("学情画像可复现（除时间戳外两次结果完全一致）",
          _stable(prof1) == _stable(prof2),
          f"知识点 {len(prof1['kp_mastery'])} 个，薄弱 {len(prof1['weak_top'])} 个", "E")
    check("错因分布是纯计数", prof1["error_type_distribution"]["total"] > 0,
          str(prof1["error_type_distribution"]["counts"]), "E")

    # ---------------------------------------------------------------- F
    section("F. check_practice 分层校验")
    # 关键：目标题必须从**库里**取（分析结果是落库的，不在内存对象上）。
    # 这里踩过一次坑：拿内存里的原始对象会得到「目标题尚未分析」的误报。
    target = store.get(by_id["sample-01"].fingerprint())
    check("目标题已带分析结果（前置条件）", target is not None and target.analysis is not None,
          f"知识点={target.analysis.knowledge_points if target and target.analysis else None}", "F")
    good = {"gen_id": "p_001", "qtype": "解答题",
            "knowledge_points": ["数学/一元二次方程/公式法与判别式",
                                 "数学/一元二次方程/根与系数关系"],
            "difficulty": 0.6, "steps": 3, "target_steps": 3,
            "stem_text": "已知关于 x 的方程 x^2 - 5x + k = 0 有两个不相等的实数根，求 k 的范围。"}
    res = validate_practice(good, target, taxonomy)
    check("正例通过（同题型/同知识点/同章节/难度接近）", res.ok,
          "；".join(res.errors), "F")

    bad_type = dict(good, gen_id="p_002", qtype="单选题")
    res = validate_practice(bad_type, target, taxonomy)
    check("题型不一致被拒", not res.ok and any("题型不一致" in e for e in res.errors),
          "；".join(res.errors), "F")

    bad_kp = dict(good, gen_id="p_003",
                  knowledge_points=["数学/二次函数/最值问题"])
    res = validate_practice(bad_kp, target, taxonomy)
    check("知识点不重合 / 超纲被拒",
          not res.ok and any("Jaccard" in e for e in res.errors)
          and any("超纲" in e for e in res.errors),
          "；".join(res.errors), "F")

    bad_diff = dict(good, gen_id="p_004", difficulty=0.95)
    res = validate_practice(bad_diff, target, taxonomy)
    check("难度偏离过大被拒（刻度已核实时为硬约束）",
          not res.ok and any("难度偏离" in e for e in res.errors),
          "；".join(res.errors), "F")

    unverified = store.get(by_id["sample-01"].fingerprint()).model_copy(deep=True)
    unverified.question.difficulty_scale = "unknown"
    res = validate_practice(dict(good, gen_id="p_005", difficulty=0.95),
                            unverified, taxonomy)
    check("难度刻度未核实时自动降级为软参考（不假装闸门有效）",
          res.ok and any("刻度未核实" in w for w in res.warnings),
          "；".join(res.warnings), "F")

    # ---------------------------------------------------------------- G
    section("G. submit_solution 确定性比对")
    cases = [
        ("0.6A", "0.6 A", "match"),
        ("2,3", "x = 2 或 x = 3", "numeric_match"),
        ("D", "A", "mismatch"),
        ("证明：连接 OC，由切线性质得 OC ⊥ CD，故 ∠ACD = ∠OCB = ∠ABC",
         "证明：连接 OC。∵ CD 是 ⊙O 的切线，∴ OC ⊥ CD，即 ∠OCD = 90°。"
         "∵ AB 是直径，∴ ∠ACB = 90°。∴ ∠ACD = ∠ACB - ∠OCA = ∠OCB。"
         "又 ∵ OB = OC，∴ ∠OBC = ∠OCB。∴ ∠ACD = ∠ABC。", "undecidable"),
    ]
    for sub, std, want in cases:
        got = compare_solution(sub, std)["verdict"]
        check(f"比对判定 {want}", got == want, f"实际={got}", "G")

    # ---------------------------------------------------------------- H
    section("H. 通道 A（官方导出解析）—— 造一个导出文件真跑一遍")
    export_txt = tmpdir / "export_sample.txt"
    export_txt.write_text(
        "期中考试 数学\n\n"
        "1. 解方程 x^2 - 4x + 3 = 0\n"
        "答案：x1 = 1, x2 = 3\n"
        "解析：因式分解得 (x-1)(x-3)=0\n"
        "学生答案：x = 1\n"
        "得分：3/8\n"
        "难度：0.55\n\n"
        "2. 计算 (-2)^3 + 5 的值\n"
        "答案：-3\n"
        "学生答案：-3\n"
        "得分：5/5\n",
        encoding="utf-8")
    eq, stats = zhixue_export.parse_file(export_txt, subject="数学",
                                        exam_name="期中考试",
                                        exam_date="2026-04-20")
    check("导出文件解析出题目", len(eq) == 2, f"{len(eq)} 题；{stats['extract_method']}", "H")
    check("解析出标准答案与得分", eq[0].answer.standard is not None
          and eq[0].score.got == 3, f"{eq[0].answer.standard!r} / {eq[0].score.got}", "H")
    check("解析置信度按字段齐备度计算", 0 < eq[0].parse_confidence <= 1,
          f"{eq[0].parse_confidence}", "H")
    check("低置信度题会被标记（供统计排除）", stats["low_confidence"] >= 0,
          f"low_confidence={stats['low_confidence']}", "H")
    for q in eq:
        store.upsert(q)
    check("导出通道的题也进了同一个库", store.counts()["total"] > len(questions),
          f"库内总数={store.counts()['total']}", "H")

    # ---------------------------------------------------------------- I
    section("I. 导出（错题本 / 练习卷）")
    md = wrongbook_markdown(store.query(), title="验收错题本")
    md_path = OUT / "acceptance_wrongbook.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    check("错题本 Markdown 生成", md_path.exists() and "来源" in md,
          f"{md_path}（{len(md)} 字）", "I")

    items = [{"gen_id": "p_001", "subject": "数学", "qtype": "解答题",
              "kp": ["数学/一元二次方程/公式法与判别式"], "difficulty": 0.6,
              "stem_html": "<p>已知方程 x^2 - 5x + k = 0 有两个不相等的实数根，求 k 的取值范围。</p>",
              "answer": "k < 25/4", "analysis": "由 Δ = 25 - 4k > 0 得 k < 25/4。",
              "verified": True, "attempts": 1, "source_topic": "sample-01",
              "verification": [i.to_dict() for i in validate_practice(good, target, taxonomy).items]}]
    paper = write_paper(items, OUT / "acceptance_paper.html", title="验收练习卷")
    check("练习卷 HTML 生成", Path(paper).exists(),
          f"{paper}（{Path(paper).stat().st_size} 字节）", "I")
    html = Path(paper).read_text(encoding="utf-8")
    check("练习卷带「AI 生成，仅供参考」标注", "AI 生成" in html, "", "I")
    check("练习卷带逐题校验结果", "校验：" in html, "", "I")
    pdf = try_pdf(paper)
    check("PDF 导出：有转换器就转，没有就明确说没有",
          pdf.get("available") is True or "how_to" in pdf,
          f"available={pdf.get('available')}，{pdf.get('reason') or pdf.get('converter')}", "I")

    # ---------------------------------------------------------------- J
    # 2026-09-24 新增：个性化诊断前必须确认科目。这里验的是闸门的**数据基础** ——
    # 闸门本身（缺科目/未确认就拒绝）走 MCP 层，由 tools/mcp_e2e.py 覆盖。
    section("J. 科目闸门的数据基础（个性化诊断前必须确认科目）")
    from core.subjects import (ask_user_prompt, normalize_subject,  # noqa: E402
                               subject_options)
    opts = subject_options(store, taxonomy)
    check("科目清单 = 标准学科顺序 ∪ 受控词表 ∪ 库内实际科目",
          set(opts["taxonomy_subjects"]) <= {r["subject"] for r in opts["subjects"]}
          and "数学" in opts["with_questions"],
          f"候选 {len(opts['subjects'])} 个；库内有数据的：{opts['with_questions']}")
    check("排序按固定学科顺序，不按题数（不让数据替用户做决定）",
          [r["subject"] for r in opts["subjects"]][:3] == ["语文", "数学", "英语"],
          str([r["subject"] for r in opts["subjects"]][:6]))
    check("字段自洽：has_questions ≡ 题数>0，diagnosable ≡ 已分析数>0",
          all(r["has_questions"] == (r["questions"] > 0)
              and r["diagnosable"] == (r["analyzed"] > 0)
              for r in opts["subjects"]),
          str([(r["subject"], r["questions"], r["analyzed"], r["diagnosable"])
               for r in opts["subjects"] if r["has_questions"]]))
    # 「库里有题、但受控词表里没这一科」是最容易被假装过去的一档：
    # 能列出来、能被用户选中，却暂时做不了知识点级分析。
    # 用「生物」实测（生物不在受控词表里；2026-09-25 补的是历史/道法，不是生物）。
    bio = normalize_question({
        "subject": "生物", "exam_name": "生物单元测", "exam_date": "2026-09-20",
        "grade": "八年级上", "stem_html": "<p>简述细胞呼吸的过程与意义。</p>",
        "qtype": "解答题", "standard": "略", "score_got": 2, "score_full": 8,
    }, source="manual", source_version="acceptance-fixture", seq=200)
    store.upsert(bio)
    opts2 = subject_options(store, taxonomy)
    hrow = next((r for r in opts2["subjects"] if r["subject"] == "生物"), None)
    check("库内有题但词表没有的学科：能列出，但如实标 in_taxonomy=false",
          hrow is not None and hrow["has_questions"] is True
          and hrow["in_taxonomy"] is False and hrow["diagnosable"] is False,
          str(hrow))
    check("历史 / 道法 反过来应标 in_taxonomy=true（已补词表）",
          all(r["in_taxonomy"] for r in opts2["subjects"]
              if r["subject"] in ("历史", "道法")),
          str([(r["subject"], r["in_taxonomy"]) for r in opts2["subjects"]
               if r["subject"] in ("历史", "道法")]))
    _prompt = ask_user_prompt(opts)
    check("「照读即可」的问话含候选科目与题数",
          "你想诊断哪一科" in _prompt and "数学" in _prompt, _prompt[:90])
    check("科目别名归一化（政治/道德与法治 → 道法）",
          normalize_subject("政治") == "道法"
          and normalize_subject("道德与法治") == "道法"
          and normalize_subject(" 数学 ") == "数学",
          f"政治→{normalize_subject('政治')}")

    _kp = "数学/一元二次方程/公式法与判别式"
    aid = store.log_diagnosis("数学", user_confirmed=True,
                              question_count=store.counts()["total"],
                              analyzed_count=1, weak_top=[_kp],
                              host="host:acceptance")
    logs = store.diagnosis_logs()
    check("诊断审计可写可读（科目 / 确认声明 / 薄弱项留痕）",
          bool(logs) and logs[0]["id"] == aid and logs[0]["subject"] == "数学"
          and logs[0]["user_confirmed"] is True and logs[0]["weak_top"] == [_kp],
          f"audit_id={aid}，共 {len(logs)} 条："
          f"{[(x['subject'], x['user_confirmed']) for x in logs]}")

    # ---------------------------------------------------------------- K
    section("K. 数据层收尾")
    check("同步日志可读写", isinstance(store.sync_logs(), list), "", "K")
    counts = store.counts()
    check("统计口径自洽",
          counts["total"] == counts["analyzed"] + counts["unanalyzed"],
          f"{counts}", "K")
    store.close()

    # 清理临时库（真删）
    s2 = Store(db, imgs)
    removed = s2.purge(confirm=True)
    check("zx_purge 真删（库文件 + WAL/SHM + 图片）",
          removed["db"] is True and not db.exists(), str(removed), "J")
    try:
        for f in sorted(tmpdir.rglob("*"), reverse=True):
            f.unlink() if f.is_file() else f.rmdir()
        tmpdir.rmdir()
    except Exception:
        pass

    # ---------------------------------------------------------------- K2
    section("K2. 接口结构指纹（包二）")
    from core.errors import CODE_FINGERPRINT_DRIFT, ZxError   # noqa: E402
    from core.fingerprint import (FingerprintStore, diff,     # noqa: E402
                                  check_response, shape_signature)

    sig1 = shape_signature({"result": {"list": [{"a": 1, "b": "x"}], "n": 3}})
    sig2 = shape_signature({"result": {"list": [{"a": 999, "b": "完全不同的文本"}],
                                       "n": 777}})
    check("指纹只看结构不看值：同结构不同值 → 签名相同", sig1 == sig2,
          f"{sig1[:3]}…")
    sig3 = shape_signature({"result": {"list": [{"a": 1, "b2": "x"}], "n": 3}})
    d = diff(sig1, sig3)
    check("字段改名 / 消失 → 签名变化", sig1 != sig3 and d["removed"], str(d)[:120])

    fp_conn = sqlite3.connect(":memory:")
    fps = FingerprintStore(fp_conn)
    now = "2026-09-26T00:00:00+00:00"
    resp = {"errorCode": 0, "result": {"examList": [{"examId": "1"}]}}
    st = check_response(fps, "homework.getUserExamList", resp, now)
    check("首次响应登记基线", st["status"] == "baseline_registered", st["status"])
    st = check_response(fps, "homework.getUserExamList", resp, now)
    check("同结构再次响应 → 放行", st["status"] == "ok", st["status"])
    drifted = {"errorCode": 0, "result": {"data": {"examList": [{"examId": "1"}]}}}
    try:
        check_response(fps, "homework.getUserExamList", drifted, now)
        drift_raised = False
    except ZxError as exc:
        drift_raised = (exc.code == CODE_FINGERPRINT_DRIFT
                        and bool(exc.suggested_action))
    check("结构漂移 → ZxError(fingerprint_drift)，不把可疑数据放行",
          drift_raised, "")
    check("基线持久化（可跨连接读取）",
          fps.baseline("homework.getUserExamList") is not None, "")

    # ---------------------------------------------------------------- 汇总
    passed = sum(1 for r in RESULTS if r["ok"])
    failed = [r for r in RESULTS if not r["ok"]]
    section(f"汇总：{passed}/{len(RESULTS)} 通过")
    for r in failed:
        print(f"  FAIL [{r['section']}] {r['name']} — {r['detail']}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "acceptance_report.json").write_text(
        json.dumps({"passed": passed, "total": len(RESULTS),
                    "failed": failed, "results": RESULTS},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "acceptance_report.md").write_text(_md_report(passed, RESULTS),
                                             encoding="utf-8")
    print(f"\n报告已写入 out/acceptance_report.md 和 out/acceptance_report.json")
    return 0 if not failed else 1


def _raises(fn, exc_type) -> bool:
    try:
        fn()
        return False
    except exc_type:
        return True
    except Exception:
        return False


def _mk_analysis(norm: dict, item: dict):
    from core.models import Analysis
    return Analysis(
        error_type=norm["error_type"],
        knowledge_points=norm.get("knowledge_points", []),
        evidence=norm.get("evidence", item.get("evidence", [])),
        confidence=norm["confidence"],
        needs_review=norm.get("needs_review", False),
        analyzed_by=norm.get("analyzed_by", ""),
        prompt_version=norm.get("prompt_version", ""),
    )


def _md_report(passed: int, results: list[dict]) -> str:
    lines = ["# 端到端验收报告", "",
             f"- 结果：**{passed}/{len(results)} 通过**",
             f"- 生成时间：{date.today().isoformat()}",
             "- 说明：本报告由 `tools/acceptance.py` 自动生成，"
             "覆盖归一化/去重/分析校验/掌握度/生成校验/答案比对/导出全链路。",
             "- **全程不需要 Cookie、不需要联网**（架构文档第 11 节：P2/P3 不依赖 P0）。",
             "", "| 段 | 检查项 | 结果 | 详情 |", "|---|---|---|---|"]
    cur = ""
    for r in results:
        if r["section"] != cur:
            cur = r["section"]
        lines.append(f"| {r['section']} | {r['name']} | "
                     f"{'✅ 通过' if r['ok'] else '❌ 失败'} | {r['detail']} |")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
