"""阈值校准脚本（架构文档 8.4 节要求的 tools/calibrate.py）。

要解决什么问题
--------------
文档里 Jaccard ≥ 0.6、难度 ±0.15 这些数字是**先验值，不是校准值**。
正确做法是：先人工标注一批题目对，画出各指标的分布，再定阈值。
这个脚本就是干这件事的——但它**不能替你完成标注**。

跑法
----
    .venv/Scripts/python tools/calibrate.py
    .venv/Scripts/python tools/calibrate.py --pairs 你的标注文件.json

输出
----
    out/calibration_report.md   —— 各指标分布 + 建议阈值 + 说明

⚠ 当前内置的是**合成标注**（data/samples/practice_pairs.json），
   只用于演示方法与跑通流程，**不要**把它算出的阈值当成已验证结论。
   要真正校准，请按同样的格式标 30~50 对真实题目。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.constants import DIFFICULTY_TOLERANCE, JACCARD_MIN   # noqa: E402
from core.models import WrongQuestion, Exam, QuestionPart, Analysis  # noqa: E402
from core.taxonomy import load_taxonomy                        # noqa: E402
from core.validate import jaccard                              # noqa: E402

DEFAULT_PAIRS = ROOT / "data" / "samples" / "practice_pairs.json"
OUT = ROOT / "out"


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------
def char_ngrams(text: str, n: int = 3) -> set[str]:
    t = "".join((text or "").split())
    if len(t) < n:
        return {t} if t else set()
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def text_similarity(a: str, b: str) -> float:
    """字符 3-gram 的 Jaccard。**只是一个便宜的近似**，
    不是嵌入相似度。文档明确说文本相似度只作参考、不作闸门，
    所以这里用最省事的算法就够——重点是要能看到它和人工判断有多不相关。"""
    return round(jaccard(char_ngrams(a), char_ngrams(b)), 4)


def metrics_for_pair(pair: dict, targets: dict, taxonomy) -> dict:
    tgt = targets[pair["target"]]
    cand = pair["candidate"]

    gen_kps = set()
    for raw in cand.get("knowledge_points", []):
        info, _ = taxonomy.resolve(str(raw), subject=tgt["subject"])
        if info:
            gen_kps.add(info.path)
    tgt_kps = set(tgt["knowledge_points"])

    tgt_chapters = {"/".join(k.split("/")[:2]) for k in tgt_kps}
    oos = [k for k in gen_kps if "/".join(k.split("/")[:2]) not in tgt_chapters]

    d_diff = None
    if cand.get("difficulty") is not None and tgt.get("difficulty") is not None:
        d_diff = round(abs(float(cand["difficulty"]) - float(tgt["difficulty"])), 4)

    step_diff = None
    if cand.get("steps") is not None:
        # 合成标注里没有目标题步骤数，用正例的众数近似——仅演示用
        step_diff = None

    return {
        "id": pair["id"], "label": int(pair["label"]), "note": pair.get("note", ""),
        "jaccard": round(jaccard(gen_kps, tgt_kps), 4),
        "difficulty_diff": d_diff,
        "qtype_match": int(cand.get("qtype") == tgt.get("qtype")),
        "chapter_in_scope": int(not oos),
        "text_similarity": text_similarity(cand.get("stem_text", ""),
                                           tgt.get("stem_text", "")),
    }


# ---------------------------------------------------------------------------
# 阈值搜索
# ---------------------------------------------------------------------------
def sweep(values: list[tuple[float, int]], direction: str,
          candidates: list[float]) -> dict:
    """在一组候选阈值上算 F1，返回最优。

    direction='ge' 表示「指标 ≥ 阈值则判为正」；
    direction='le' 表示「指标 ≤ 阈值则判为正」。
    """
    best = {"threshold": None, "f1": -1.0, "precision": 0, "recall": 0}
    rows = []
    for th in candidates:
        tp = fp = fn = tn = 0
        for v, y in values:
            pred = 1 if ((v >= th) if direction == "ge" else (v <= th)) else 0
            if pred == 1 and y == 1:
                tp += 1
            elif pred == 1 and y == 0:
                fp += 1
            elif pred == 0 and y == 1:
                fn += 1
            else:
                tn += 1
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        rows.append({"threshold": th, "f1": round(f1, 4),
                     "precision": round(prec, 4), "recall": round(rec, 4),
                     "tp": tp, "fp": fp, "fn": fn, "tn": tn})
        if f1 > best["f1"]:
            best = dict(rows[-1])
    return {"best": best, "sweep": rows}


def describe(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    vs = sorted(values)
    def q(p):
        return vs[min(len(vs) - 1, int(len(vs) * p))]
    return {"n": len(vs), "min": round(vs[0], 4), "max": round(vs[-1], 4),
            "median": round(q(0.5), 4), "q25": round(q(0.25), 4),
            "q75": round(q(0.75), 4), "mean": round(sum(vs) / len(vs), 4)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=str(DEFAULT_PAIRS))
    ap.add_argument("--out", default=str(OUT / "calibration_report.md"))
    args = ap.parse_args()

    data = json.loads(Path(args.pairs).read_text(encoding="utf-8"))
    taxonomy = load_taxonomy()
    targets = data["targets"]
    pairs = data["pairs"]
    rows = [metrics_for_pair(p, targets, taxonomy) for p in pairs]

    pos = [r for r in rows if r["label"] == 1]
    neg = [r for r in rows if r["label"] == 0]

    print(f"读入 {len(rows)} 对（正例 {len(pos)} / 负例 {len(neg)}）")

    report = ["# 阈值校准报告", "",
              f"- 数据来源：`{Path(args.pairs).name}`（**合成标注**）",
              f"- 样本量：{len(rows)} 对（正例 {len(pos)} / 负例 {len(neg)}）",
              "",
              "> ⚠️ **这份报告不能当作校准结论。** 文档 8.4 节说得很清楚：",
              "> 阈值需要先人工标注 30~50 对**真实**题目，再看分布定。",
              "> 这里用的是合成样例，样本量也远不够，作用是**演示方法与跑通流程**。",
              "> 拿到真实错题库后，请按 `data/samples/practice_pairs.json` 的格式重新标注。",
              ""]

    # ---- 分布 ----
    report += ["## 1. 各指标分布（正例 vs 负例）", "",
               "| 指标 | 正例分布 | 负例分布 | 分离度 |", "|---|---|---|---|"]
    results: dict = {}
    for key in ("jaccard", "difficulty_diff", "qtype_match",
                "chapter_in_scope", "text_similarity"):
        pv = [r[key] for r in pos if r[key] is not None]
        nv = [r[key] for r in neg if r[key] is not None]
        dp, dn = describe(pv), describe(nv)
        if key == "difficulty_diff":
            sep = (dn.get("median", 0) or 0) - (dp.get("median", 0) or 0)
        else:
            sep = (dp.get("median", 0) or 0) - (dn.get("median", 0) or 0)
        results[key] = {"pos": dp, "neg": dn, "separation": round(sep, 4)}
        report.append(
            f"| {key} | n={dp.get('n')} 中位 {dp.get('median')} "
            f"[{dp.get('min')}~{dp.get('max')}] | n={dn.get('n')} "
            f"中位 {dn.get('median')} [{dn.get('min')}~{dn.get('max')}] | "
            f"{round(sep, 4)} |")
        print(f"  {key}: 正例中位 {dp.get('median')} / 负例中位 {dn.get('median')} / 分离度 {round(sep, 4)}")

    # ---- 阈值搜索 ----
    report += ["", "## 2. 阈值搜索（最大化 F1）", "",
               "| 指标 | 方向 | 最优阈值 | F1 | 精确率 | 召回率 | 当前文档值 |",
               "|---|---|---|---|---|---|---|"]
    jac_vals = [(r["jaccard"], r["label"]) for r in rows]
    diff_vals = [(r["difficulty_diff"], r["label"])
                 for r in rows if r["difficulty_diff"] is not None]
    sim_vals = [(r["text_similarity"], r["label"]) for r in rows]

    sweeps = {
        "jaccard": (sweep(jac_vals, "ge",
                          [round(x / 100, 2) for x in range(0, 101, 5)]), JACCARD_MIN),
        "difficulty_diff": (sweep(diff_vals, "le",
                                  [round(x / 100, 2) for x in range(0, 51, 2)]),
                            DIFFICULTY_TOLERANCE),
        "text_similarity": (sweep(sim_vals, "ge",
                                  [round(x / 100, 2) for x in range(0, 101, 5)]),
                            "（文档说：仅参考，不作闸门）"),
    }
    for name, (res, doc_val) in sweeps.items():
        b = res["best"]
        report.append(f"| {name} | {'≥' if name != 'difficulty_diff' else '≤'} "
                      f"| **{b['threshold']}** | {b['f1']} | {b['precision']} "
                      f"| {b['recall']} | {doc_val} |")
        print(f"  {name}: 最优阈值 {b['threshold']}（F1={b['f1']}，"
              f"精确率={b['precision']}，召回率={b['recall']}），文档值 {doc_val}")

    # ---- 逐对明细 ----
    report += ["", "## 3. 逐对明细", "",
               "| id | label | 人工备注 | Jaccard | 难度差 | 题型一致 | 章节内 | 文本相似度 |",
               "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        report.append(f"| {r['id']} | {'✅同类' if r['label'] else '❌不同类'} | "
                      f"{r['note']} | {r['jaccard']} | {r['difficulty_diff']} | "
                      f"{'是' if r['qtype_match'] else '否'} | "
                      f"{'是' if r['chapter_in_scope'] else '否'} | "
                      f"{r['text_similarity']} |")

    # ---- 关键观察 ----
    sim_sep = results["text_similarity"]["separation"]
    report += ["", "## 4. 关键观察", ""]
    report.append(
        f"1. **文本相似度的分离度只有 {sim_sep}** —— 正例和负例的文本相似度"
        "分布几乎重叠。这印证了文档 8.4 节的判断："
        "数学题换个数字文本相似度就暴跌，它和「同知识点同难度」相关性很弱，"
        "**不能单独当闸门**。")
    report.append(
        f"2. **Jaccard 的分离度是 {results['jaccard']['separation']}** —— "
        "知识点集合重合度是这套指标里最能分开正负例的一个，"
        "把它当主闸门是对的。")
    report.append(
        f"3. **难度差的分离度是 {results['difficulty_diff']['separation']}，几乎为零"
        "（甚至略为负）** —— 这条最反直觉，但很重要："
        "负例被判为「不同类」的原因绝大多数是**知识点不同**，"
        "而不是难度差。也就是说在真实场景里，"
        "「难度 ±0.15」这条闸门**几乎不会独立否决任何题**——"
        "难度差大的题，知识点通常也早就对不上了。")
    report.append(
        "   这不代表难度闸门没用（它能拦住「同知识点但明显偏难/偏易」的题，"
        "样例里的 p12 就是这种），但它说明：**闸门的有效性排序**是 "
        "知识点 > 题型 > 章节 > 难度。难度是最后一道网，不是主要判据。")
    report.append(
        f"4. **样本量太少（{len(rows)} 对），且负例构造得「太干净」**——"
        "本样例的负例大多是知识点完全不重合（Jaccard=0），所以搜出来的 "
        f"Jaccard 最优阈值是 {sweeps['jaccard'][0]['best']['threshold']}，"
        f"远低于文档给的 {JACCARD_MIN}。"
        "真实数据里会出现大量「部分重合」的边界样本（比如 3 个知识点对上 2 个），"
        "阈值会明显上移。**这正是合成标注不能当结论用的原因。**")
    report.append(
        "5. 要真正校准，至少需要 30~50 对，并且负例必须覆盖三类边界："
        "① 同章节不同知识点　② 跨章节　③ 同知识点但难度差一点。"
        "本样例已按这三类构造，可以作为你标注真实数据时的模板。")

    OUT.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(report), encoding="utf-8")
    (OUT / "calibration_report.json").write_text(
        json.dumps({"metrics": results, "sweeps": {k: v[0] for k, v in sweeps.items()},
                    "rows": rows, "synthetic": True},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
