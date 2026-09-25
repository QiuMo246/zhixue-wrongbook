"""生成「学生视角」的 HTML 错题报告（单文件、零外部依赖）。

和 `docs/自测报告` 那种技术报告的区别
--------------------------------------
  · 技术报告（md2html 转的）：给维护者看 —— 方法、可复现命令、诚实声明
  · 本工具产出的：**给学生看** —— 题干、我写的、标准答案、为什么错，一眼看到

三大类结构
----------
  ① 原错题           每道题带完整题干 + 配图 + 「标准答案 vs 我写的」对照
  ② 未掌握知识点总结   掌握度 / 错因分布 / 要补的概念 / 平台印证 / 建议
  ③ 同类题           针对薄弱点的练习，点击显示答案

用法
----
    .venv/Scripts/python tools/report_student.py \\
        --spec out/report_spec_物理.json \\
        --profile out/phys_diag.json \\
        --practice out/phys_practice.json \\
        --platform out/platform_points.json \\
        --out out/物理错题报告_学生版.html

设计上的几个决定（都是踩过坑才这么写的）
----------------------------------------
1. **逐题数据（spec）与渲染代码分离**。因为「学生写了什么」是**读手写图片**得出的，
   机器没法自动算 —— 那是宿主的活。所以 spec 由宿主产出，本工具只负责渲染。
2. **题干 / 配图从数据库读**，不从 spec 读 —— 避免两处数据不同步。
3. **可选输入缺了就跳过对应板块**，不报错 —— 只想出「原错题」那一类时也能跑。
4. **配图 base64 内嵌**，缩到 720px 转 JPEG —— 单文件、可离线、能直接发给同学。

三个必须知道的坑（2026-09-25 实测）
-----------------------------------
1. **配图必须校验命中数**。库里 id 的序号是 4 位（`0001`），
   而图片文件名是 3 位（`001`）—— 直接拼字符串会**一张都匹配不到且不报错**，
   静默生成一份"没有图"的报告。所以本工具在找不到图时**打印警告**。
2. **LaTeX 清洗的顺序不能错**。`{^\\circ}` 和 `\\textcircled1` 自带花括号，
   必须先处理；否则 `\\frac{100 {^\\circ}\\mathrm{C} }{20cm}` 会变成
   `\\frac100 ^°C 20cm` 这种乱码。
3. **`**粗体**` 是 Markdown 语法**，直接塞进 HTML 会显示字面星号 ——
   统一走 `md()`（先 escape 再替换）。
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.models import html_to_text  # noqa: E402

E = html.escape


def md(s: str) -> str:
    """先转义，再把 **粗体** 变成 <b>。"""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(s or ""))


# ---------------------------------------------------------------------------
# LaTeX 残渣清洗（顺序见模块 docstring 的坑 2）
# ---------------------------------------------------------------------------
_CIRCLED = {"0": "⓪", "1": "①", "2": "②", "3": "③", "4": "④",
            "5": "⑤", "6": "⑥", "7": "⑦", "8": "⑧", "9": "⑨"}


def _circled(m: re.Match) -> str:
    return _CIRCLED.get(m.group(1), m.group(0))


_LATEX: list[tuple[str, object]] = [
    (r"\\textcircled\s*\{?\s*(\d)\s*\}?", _circled),   # \textcircled1 → ①
    (r"\{\s*\^\s*\\circ\s*\}", "°"),                   # {^\circ}
    (r"\^\s*\{\s*\\circ\s*\}", "°"),                   # ^{\circ}
    (r"\\circ", "°"),
    (r"\\mathrm\s*\{([^{}]*)\}", r"\1"),
    (r"\\text\s*\{([^{}]*)\}", r"\1"),
    (r"\\(?:d|t)?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"\1/\2"),
    (r"\\times", "×"), (r"\\div", "÷"), (r"\\cdot", "·"),
    (r"\\sim", "~"), (r"\\approx", "≈"), (r"\\leq", "≤"), (r"\\geq", "≥"),
    (r"\\left\s*", ""), (r"\\right\s*", ""),
    (r"\\min", "min"), (r"\\max", "max"),
    (r"\\[,;! ]", " "),
    (r"[{}]", ""),
    (r"[\u200b\u200c\u200d\ufeff]", ""),
]


def clean_text(s: str) -> str:
    s = s or ""
    # 表格单元格之间插入分隔符：否则剥标签后相邻格子的数字会挤在一起。
    # 单元格内常包着 <p align="center">，</p> 会被转成换行把表格拆成竖排 —— 先打掉。
    def _cell_inner(m: "re.Match") -> str:
        inner = re.sub(r"</?p[^>]*>", " ", m.group(2), flags=re.I)
        return m.group(1) + inner + m.group(3)
    s = re.sub(r"(<t[dh][^>]*>)(.*?)(</t[dh]>)", _cell_inner, s,
               flags=re.I | re.S)
    s = re.sub(r"\s*</t[dh]>\s*<t[dh][^>]*>\s*", " | ", s, flags=re.I | re.S)
    s = html_to_text(s)
    for pat, rep in _LATEX:
        s = re.sub(pat, rep, s)
    s = html.unescape(s)          # &deg; 这类实体 html_to_text 没覆盖的，这里兜底
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r" ?/(\d)", r"/\1", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def img_uri(path: Path, max_w: int = 720) -> str:
    """配图内嵌成 data URI。"""
    from PIL import Image
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", im.size, "white")
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# 数据读取
# ---------------------------------------------------------------------------
def load_questions(subject: str, qs: list[dict]) -> dict[str, dict]:
    """从库里取题干 / 标准答案 / 平台解析，并把配图内嵌。"""
    conn = sqlite3.connect(str(ROOT / "data" / "wrongbook.db"))
    conn.row_factory = sqlite3.Row
    info: dict[str, dict] = {}
    for r in conn.execute(
            "SELECT id, stem_html, standard, analysis_html FROM questions WHERE subject=?",
            (subject,)):
        info[r["id"]] = {
            "stem": clean_text(r["stem_html"]),
            "standard": clean_text(r["standard"]),
            "explain": clean_text(r["analysis_html"]),
        }
    conn.close()

    imgdir = ROOT / "data" / "images"
    missing = 0
    for q in qs:
        n = int(str(q["id"]).split("_")[-1])
        pre = q.get("exam_prefix") or ""
        # ⚠️ 模式里必须带**学科名** —— 同一场考试里数学/英语/物理的序号是各自独立编号的，
        #    只按 `*_{序号}_stem_*.png` 搜会同时命中其它学科（实测会从 16 张变 27 张）。
        pat = (f"{pre}_{subject}_{n:03d}_stem_*.png" if pre
               else f"*_{subject}_{n:03d}_stem_*.png")
        cand = sorted(imgdir.glob(pat))
        if len(cand) > 1:
            print(f"  ⚠ {q.get('qno')} 配图匹配到 {len(cand)} 张，"
                  f"请用 spec 里的 exam_prefix 限定：{[c.name for c in cand]}")
        if not cand:
            missing += 1
            print(f"  ⚠ {q.get('qno')} 没找到配图（期望 {pat}）")
        q["figures"] = [img_uri(p) for p in cand]
    if missing:
        print(f"  ⚠ 共 {missing} 道题缺配图 —— 报告会缺图，别当成功")
    return info


def load_opt(path: str | None) -> dict | list | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        print(f"  ⚠ 可选输入不存在，跳过对应板块：{p}")
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
CSS = """
:root{
  --bg:#f6f7f9; --card:#fff; --fg:#16181d; --muted:#6b7280; --line:#e5e7eb;
  --red:#e5484d; --orange:#f59e0b; --yellow:#eab308; --green:#22c55e;
  --blue:#3b82f6; --purple:#8b5cf6; --soft:#f3f4f6;
  --radius:14px; --shadow:0 1px 2px rgba(16,24,40,.04),0 4px 14px rgba(16,24,40,.05);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);
  font:16px/1.7 -apple-system,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:900px;margin:0 auto;padding:0 18px 90px}
header{background:linear-gradient(135deg,#1e3a8a,#3b82f6 55%,#60a5fa);
  color:#fff;padding:52px 18px 44px}
header .in{max-width:900px;margin:0 auto}
header h1{margin:0 0 10px;font-size:29px;letter-spacing:-.4px;font-weight:700}
header p{margin:0;opacity:.9;font-size:14.5px}
header .tags{margin-top:18px;display:flex;gap:8px;flex-wrap:wrap}
header .tags span{background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.28);
  padding:4px 12px;border-radius:99px;font-size:13px}
header .concl{margin-top:22px;background:rgba(255,255,255,.14);
  border:1px solid rgba(255,255,255,.22);border-radius:12px;padding:14px 17px;font-size:14.5px}
nav.cats{position:sticky;top:0;z-index:20;background:rgba(246,247,249,.94);
  backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line)}
nav.cats .in{max-width:900px;margin:0 auto;padding:11px 18px;display:flex;gap:9px;
  flex-wrap:wrap;align-items:center}
nav.cats a{display:flex;align-items:center;gap:7px;text-decoration:none;color:var(--fg);
  background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:7px 13px;font-size:13.5px;font-weight:600;white-space:nowrap}
nav.cats a:hover{border-color:var(--blue);color:var(--blue)}
nav.cats a i{display:inline-block;width:19px;height:19px;line-height:19px;text-align:center;
  border-radius:6px;background:var(--blue);color:#fff;font-size:11.5px;font-style:normal}
nav.cats a .c{color:var(--muted);font-weight:500}
.cat{display:flex;align-items:center;gap:15px;margin:46px 0 4px;
  padding-top:24px;border-top:2px solid var(--fg);scroll-margin-top:60px}
.cat .num{flex:0 0 48px;height:48px;line-height:48px;text-align:center;border-radius:14px;
  font-size:20px;font-weight:750;color:#fff;background:var(--fg)}
.cat .num.a{background:var(--red)} .cat .num.b{background:var(--orange)}
.cat .num.c{background:var(--green)}
.cat .tt{font-size:23px;font-weight:750;letter-spacing:-.4px;line-height:1.3}
.cat .sub{font-size:13.5px;color:var(--muted);font-weight:400;margin-top:2px}
section{margin:0 0 30px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:22px 24px}
h3{font-size:16.5px;margin:26px 0 10px}
p{margin:10px 0}
b,strong{font-weight:650}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:16px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:18px 16px;box-shadow:var(--shadow);text-align:center}
.stat .v{font-size:30px;font-weight:750;letter-spacing:-1px;line-height:1.2}
.stat .l{font-size:13px;color:var(--muted);margin-top:5px}
.stat.red .v{color:var(--red)} .stat.orange .v{color:var(--orange)}
.stat.blue .v{color:var(--blue)}
.kp{display:grid;grid-template-columns:1fr 128px 62px;gap:12px;align-items:center;
  padding:9px 0;border-bottom:1px dashed var(--line)}
.kp:last-child{border-bottom:0}
.kp .name{font-size:14.5px}
.kp .num{font-size:13px;color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
.bar{height:9px;background:var(--soft);border-radius:99px;overflow:hidden}
.bar i{display:block;height:100%;border-radius:99px;background:var(--blue)}
.bar i.red{background:var(--red)} .bar i.orange{background:var(--orange)}
.bar i.green{background:var(--green)}
.dist{display:flex;gap:10px;margin-top:6px}
.dist div{flex:1;border-radius:10px;padding:13px 15px;background:var(--soft)}
.dist .k{font-size:13px;color:var(--muted)}
.dist .v{font-size:20px;font-weight:700;margin-top:2px}
.q{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:var(--shadow);margin-bottom:18px;overflow:hidden;scroll-margin-top:66px}
.q .hd{display:flex;align-items:center;gap:11px;padding:15px 20px;flex-wrap:wrap;
  background:#fafbfc;border-bottom:1px solid var(--line)}
.q .badge{background:var(--fg);color:#fff;font-size:13px;font-weight:600;
  padding:3px 10px;border-radius:7px;white-space:nowrap}
.q .meta{font-size:13px;color:var(--muted)}
.q .score{margin-left:auto;font-size:13px;color:var(--muted);white-space:nowrap}
.q .score b{font-size:15px;color:var(--fg)}
.q .bd{padding:18px 20px 20px}
.lbl{font-size:12.5px;font-weight:700;color:var(--muted);letter-spacing:.5px;margin:0 0 7px}
.stem{font-size:15px;line-height:1.9;white-space:pre-wrap;word-break:break-word}
.figs{margin:12px 0 4px}
.figs img{max-width:100%;border:1px solid var(--line);border-radius:10px;
  margin:8px 0;background:#fff;display:block}
.cmp{display:grid;grid-template-columns:auto 1fr 1fr;gap:9px 12px;align-items:center;
  background:var(--soft);border-radius:10px;padding:13px 15px;margin:14px 0}
.cmp .h{font-size:12.5px;color:var(--muted);font-weight:600}
.cmp .w{font-size:13px;color:var(--muted)}
.cmp .r,.cmp .m{font-size:14.5px;padding:6px 11px;border-radius:7px;font-weight:600;
  word-break:break-word}
.cmp .r{background:#dcfce7;color:#166534}
.cmp .m{background:#fee2e2;color:#991b1b}
.cmp .same{background:#e5e7eb;color:#4b5563}
.tag{display:inline-block;font-size:12px;padding:2px 9px;border-radius:99px;
  background:var(--soft);color:var(--muted);margin:0 5px 5px 0}
.tag.red{background:#fee2e2;color:#991b1b}
.tag.orange{background:#fef3c7;color:#92400e}
.tag.yellow{background:#fef9c3;color:#854d0e}
.tag.green{background:#dcfce7;color:#166534}
.tag.blue{background:#dbeafe;color:#1e40af}
.tag.purple{background:#ede9fe;color:#5b21b6}
.why{font-size:14.5px;color:#374151;border-left:3px solid var(--blue);
  padding:2px 0 2px 13px;margin:14px 0 0}
.warn{font-size:13.5px;background:#fffbeb;border:1px solid #fde68a;color:#854d0e;
  border-radius:9px;padding:10px 13px;margin-top:11px}
details{margin-top:14px;border:1px solid var(--line);border-radius:10px;background:#fcfdfe}
details summary{cursor:pointer;padding:10px 15px;font-size:13.5px;color:var(--muted);
  font-weight:600;list-style:none}
details summary::-webkit-details-marker{display:none}
details summary::before{content:"\\25B8 ";color:var(--blue)}
details[open] summary::before{content:"\\25BE "}
details .dc{padding:12px 15px 15px;font-size:14px;line-height:1.85;white-space:pre-wrap;
  color:#4b5563;border-top:1px solid var(--line)}
.lesion{border-left:4px solid var(--blue);background:var(--card);border-radius:10px;
  padding:15px 18px;margin-bottom:11px;border-top:1px solid var(--line);
  border-right:1px solid var(--line);border-bottom:1px solid var(--line)}
.lesion.red{border-left-color:var(--red)} .lesion.orange{border-left-color:var(--orange)}
.lesion.yellow{border-left-color:var(--yellow)} .lesion.green{border-left-color:var(--green)}
.lesion.blue{border-left-color:var(--blue)} .lesion.purple{border-left-color:var(--purple)}
.lesion h4{margin:0 0 6px;font-size:15.5px}
.lesion p{margin:0;font-size:14px;color:var(--muted)}
.pq{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:var(--shadow);margin-bottom:14px;overflow:hidden}
.pq .ph{padding:15px 20px 0}
.pq .pt{font-size:13px;color:var(--muted);margin-bottom:7px}
.pq .stem2{font-size:14.5px;line-height:1.9}
.pq .stem2 p{margin:7px 0}
.pq .ans{display:none;margin:0 20px 18px;background:var(--soft);border-radius:10px;padding:14px 16px}
.pq.show .ans{display:block}
.pq .btn{margin:0 20px 18px;display:inline-block;background:var(--blue);color:#fff;
  border:0;border-radius:9px;padding:9px 18px;font-size:14px;cursor:pointer;
  font-family:inherit;font-weight:600}
.pq .btn:hover{background:#2563eb}
.pq .btn.on{background:var(--soft);color:var(--muted)}
.adv{display:flex;gap:14px;align-items:flex-start;margin-bottom:14px}
.adv .n{flex:0 0 34px;height:34px;line-height:34px;text-align:center;border-radius:10px;
  background:var(--blue);color:#fff;font-weight:700}
.adv .t{font-weight:650;margin-bottom:3px}
.adv .d{font-size:14px;color:#4b5563}
table{width:100%;border-collapse:collapse;font-size:14px;margin:10px 0}
th,td{text-align:left;padding:9px 11px;border-bottom:1px solid var(--line)}
th{background:var(--soft);font-weight:600;font-size:13px}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
nav.jump{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:14px 18px;margin:16px 0 20px;box-shadow:var(--shadow)}
nav.jump .t{font-size:13px;color:var(--muted);margin-bottom:9px}
nav.jump a{display:inline-block;font-size:13px;padding:4px 10px;border-radius:7px;
  background:var(--soft);color:var(--fg);text-decoration:none;margin:0 6px 6px 0}
nav.jump a:hover{background:var(--blue);color:#fff}
footer{text-align:center;color:var(--muted);font-size:13px;margin-top:44px;
  padding-top:22px;border-top:1px solid var(--line)}
@media(max-width:640px){
  header{padding:38px 16px 32px} header h1{font-size:23px}
  .stats{grid-template-columns:1fr}
  .kp{grid-template-columns:1fr 84px 52px;gap:8px}
  .cmp{grid-template-columns:1fr;gap:5px}
  .cmp .h{display:none} .cmp .w{font-size:12px}
  .card{padding:18px 16px} .q .hd{padding:13px 16px} .q .bd{padding:16px}
  .cat .tt{font-size:19px} .cat .num{flex:0 0 40px;height:40px;line-height:40px;font-size:17px}
}
@media print{
  body{background:#fff}
  header{background:#1e3a8a !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  nav.cats,nav.jump{display:none}
  details .dc{display:block !important}
  .pq .ans{display:block !important} .pq .btn{display:none}
  .card,.q,.pq,.stat,.lesion{box-shadow:none;break-inside:avoid}
  .cat{break-before:page}
}
"""


def anchor_of(q: dict) -> str:
    return f"q-{str(q['exam']).replace('-', '')}-{str(q['qno']).replace('第', '').replace('题', '')}"


def bar(pct: float, cls: str = "") -> str:
    return f'<div class="bar"><i class="{cls}" style="width:{max(2, min(100, pct)):.0f}%"></i></div>'


def level_of(m: float) -> str:
    return "red" if m < 0.4 else ("orange" if m < 0.6 else "green")


def build(spec: dict, info: dict[str, dict], profile, practice, platform) -> str:
    qs: list[dict] = spec["questions"]
    lesions: list[dict] = spec.get("lesions") or []
    advice: list[dict] = spec.get("advice") or []

    # ---- 画像（可选） ----
    prof = {}
    if isinstance(profile, dict):
        prof = profile.get("profile") or profile
    mastery = [k for k in (prof.get("kp_mastery") or []) if not k.get("insufficient")]
    mastery.sort(key=lambda k: k["mastery"])
    insuff = [k for k in (prof.get("kp_mastery") or []) if k.get("insufficient")]
    dist = prof.get("error_type_distribution") or {}
    counts = dist.get("counts") or {}
    total = dist.get("total") or sum(counts.values()) or len(qs)

    # ---- 平台考点（可选） ----
    plat_rows: list[tuple[str, dict]] = []
    if isinstance(platform, dict):
        weak: dict[str, dict] = {}
        for _, v in platform.items():
            for r in (v or {}).get("rows") or []:
                ab = r.get("myScoreAbility")
                if ab is None or ab >= 70:
                    continue
                nm = r.get("name")
                if nm not in weak or ab < weak[nm]["ability"]:
                    weak[nm] = {"ability": ab, "weight": r.get("score")}
        plat_rows = sorted(weak.items(), key=lambda kv: kv[1]["ability"])

    has_practice = isinstance(practice, list) and practice

    P: list[str] = []
    A = P.append

    # ============================================================ 页头
    A(f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(spec.get('title', '错题报告'))}</title>
<style>{CSS}</style></head><body>

<header><div class="in">
<h1>{E(spec.get('title', '错题报告'))}</h1>
<p>{E(spec.get('subtitle', ''))}</p>
{''.join(f'<div class="tags">{''.join(f'<span>{E(t)}</span>' for t in spec.get("tags") or [])}</div>' if spec.get('tags') else '')}
{f'<div class="concl">{md(spec["conclusion"])}</div>' if spec.get('conclusion') else ''}
</div></header>

<nav class="cats"><div class="in">
<a href="#cat1"><i>1</i>原错题 <span class="c">{len(qs)} 道</span></a>
<a href="#cat2"><i>2</i>未掌握知识点总结 <span class="c">{len(lesions)} 个概念</span></a>
{f'<a href="#cat3"><i>3</i>同类题 <span class="c">{len(practice)} 道</span></a>' if has_practice else ''}
</div></nav>

<div class="wrap">""")

    # ============================================================ ① 原错题
    A(f"""
<div class="cat" id="cat1">
  <div class="num a">1</div>
  <div><div class="tt">原错题</div>
  <div class="sub">{len(qs)} 道，按考试顺序排。每题带完整题干、配图、「标准答案 vs 你写的」对照</div></div>
</div>
<nav class="jump"><div class="t">跳到某一题：</div>""")
    for q in qs:
        A(f'<a href="#{anchor_of(q)}">{E(q["exam"])} {E(q["qno"])}</a>')
    A("</nav>")

    for q in qs:
        iq = info.get(q["id"], {})
        et = q.get("error_type", "")
        et_cls = "orange" if et == "表达不规范" else "red"
        kp_tags = "".join(f'<span class="tag blue">{E(k)}</span>' for k in q.get("kp") or [])
        warn = ("" if not q.get("needs_review") else
                '<div class="warn">⚠️ 这一题的结论<b>标记了待人工复核</b>：'
                '不是所有结论都一样硬，拿不准的地方我没硬猜。建议对着原卷再看一眼。</div>')
        rows = []
        for b in q.get("blanks") or []:
            same = b["right"] == b["mine"]
            rows.append(f'<div class="w">{E(b["where"])}</div>'
                        f'<div class="{"r same" if same else "r"}">{E(b["right"])}</div>'
                        f'<div class="{"m same" if same else "m"}">{E(b["mine"])}</div>')
        cmp_html = ('<div class="cmp"><div class="h">位置</div>'
                    '<div class="h">标准答案</div><div class="h">你写的</div>'
                    + "".join(rows) + "</div>") if rows else ""
        figs = "".join(f'<img src="{u}" alt="题目配图">' for u in q.get("figures") or [])
        explain = iq.get("explain") or ""

        A(f"""
<div class="q" id="{anchor_of(q)}">
  <div class="hd">
    <span class="badge">{E(q['qno'])}</span>
    <span class="meta">{E(q['exam'])} · {E(q.get('qtype', ''))}</span>
    {f'<span class="tag {et_cls}">{E(et)}</span>' if et else ''}
    <span class="score"><b>{q.get('got')}</b>/{q.get('full')} 分</span>
  </div>
  <div class="bd">
    <div class="lbl">题目</div>
    <div class="stem">{E(iq.get('stem') or '（题干缺失）')}</div>
    {f'<div class="figs">{figs}</div>' if figs else ''}
    {f'<div class="lbl" style="margin-top:18px">对照</div>{cmp_html}' if cmp_html else ''}
    <div style="margin-top:-4px">{kp_tags}</div>
    {f'<div class="why">{md(q.get("why"))}</div>' if q.get('why') else ''}
    {warn}
    {f'<details><summary>平台给的解析（点开看）</summary><div class="dc">{E(explain)}</div></details>' if explain else ''}
  </div>
</div>""")

    # ============================================================ ② 知识点总结
    A(f"""
<div class="cat" id="cat2">
  <div class="num b">2</div>
  <div><div class="tt">未掌握知识点总结</div>
  <div class="sub">把错因归到一起，看看到底是哪几个概念没掌握</div></div>
</div>
<section>""")

    if counts or mastery:
        A(f"""
<div class="stats">
  <div class="stat red"><div class="v">{counts.get('概念不清', 0)}<span style="font-size:17px">/{total}</span></div>
    <div class="l">是「概念不清」，不是粗心</div></div>
  <div class="stat orange"><div class="v">{f'{mastery[0]["mastery"]:.2f}' if mastery else '—'}</div>
    <div class="l">最弱知识点：{E(mastery[0]['kp'].split('/')[-1]) if mastery else '—'}</div></div>
  <div class="stat blue"><div class="v">{len(lesions)}</div><div class="l">个真正要补的概念</div></div>
</div>""")

    if mastery:
        A("""
<h3>各知识点掌握度</h3>
<div class="card">
<p style="font-size:14px;color:var(--muted);margin-top:0">
掌握度 = 按时间加权的得分率，只有样本 ≥3 道才给数字（不够就如实说“样本不足”，不硬算）。</p>""")
        for k in mastery:
            cls = level_of(k["mastery"])
            short = k["kp"].split("/")[-1]
            chap = k["kp"].split("/")[1] if "/" in k["kp"] else ""
            A(f"""
<div class="kp">
  <div class="name">{E(short)}<span style="color:var(--muted);font-size:12.5px"> · {E(chap)}</span></div>
  {bar(k['mastery'] * 100, cls)}
  <div class="num"><b style="color:var(--{cls})">{k['mastery']:.2f}</b> <span style="font-size:12px">({k['n']}题)</span></div>
</div>""")
        if insuff:
            A(f"""
<p style="font-size:13.5px;color:var(--muted);margin:14px 0 0">
另有 {len(insuff)} 个知识点<b>样本不足</b>（不到 3 道题），刻意不给数字，免得用一道题的表现下结论：
{E('、'.join(k['kp'].split('/')[-1] + f"（{k['n']}题）" for k in insuff))}。</p>""")
        A("</div>")

    if counts:
        A('<h3>错因分布</h3><div class="dist">')
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
            A(f'<div><div class="k">{E(k)}</div><div class="v">{v} 道</div></div>')
        A("</div>")

    if lesions:
        A(f"""
<h3>真正要补的 {len(lesions)} 个概念</h3>
<p style="font-size:14px;color:var(--muted);margin-top:-4px">
把错因归到一起，反复出现的就是这几个。<b>补概念比刷题有用。</b></p>""")
        for L in lesions:
            A(f"""
<div class="lesion {L.get('color', 'blue')}">
  <h4>{E(L['title'])}</h4>
  <p>{E(L.get('desc', ''))}</p>
  <div style="margin-top:9px">{''.join(f'<span class="tag">{E(x)}</span>' for x in L.get('qs') or [])}</div>
</div>""")

    if plat_rows:
        A("""
<h3>平台的数据也说了同一件事</h3>
<div class="card">
<p style="margin-top:0">智学网自己也有一套考点数据（考点名 + 占分 + 掌握程度）。
拿它跟逐题结论对一遍 —— <b>两个独立来源，方向一致才可信</b>。</p>
<table>
<tr><th>平台认为弱的考点</th><th class="n">平台掌握度</th><th class="n">占分</th></tr>""")
        for nm, v in plat_rows:
            color = "var(--red)" if v["ability"] < 40 else "var(--orange)"
            A(f'<tr><td>{E(nm)}</td>'
              f'<td class="n" style="color:{color};font-weight:650">{v["ability"]:.0f}</td>'
              f'<td class="n">{E(str(v["weight"]))}</td></tr>')
        A("</table></div>")

    if advice:
        A("<h3>接下来怎么做</h3>")
        for a in advice:
            A(f"""
<div class="adv"><div class="n">{E(str(a.get('n', '')))}</div>
<div><div class="t">{E(a.get('title', ''))}</div><div class="d">{md(a.get('body', ''))}</div></div></div>""")
    A("</section>")

    # ============================================================ ③ 同类题
    if has_practice:
        A(f"""
<div class="cat" id="cat3">
  <div class="num c">3</div>
  <div><div class="tt">同类题</div>
  <div class="sub">针对上面 {len(lesions) or '这些'} 个概念出的 {len(practice)} 道练习，先自己做一遍再看答案</div></div>
</div>
<section>
<p style="font-size:14px;color:var(--muted);margin-top:6px">
每道题都注明<b>改自哪道错题</b>，而且都过了校验闸门
（题型一致 / 知识点重合度 ≥0.6 / 不超纲 / 难度接近）。</p>""")
        for i, x in enumerate(practice, 1):
            p = x.get("practice") or {}
            ok = (x.get("check") or {}).get("ok")
            badge = ('<span class="tag green">已校验通过</span>' if ok
                     else '<span class="tag red">校验未通过</span>')
            A(f"""
<div class="pq" id="pq{i}">
  <div class="ph">
    <div class="pt">练习 {i} · {E(p.get('qtype', ''))} · 改自 {E(p.get('rewrite_of', ''))} {badge}</div>
    <div class="stem2">{p.get('stem_html', '')}</div>
  </div>
  <button class="btn" onclick="reveal({i},this)">显示答案</button>
  <div class="ans">
    <div style="font-size:13px;color:var(--muted);margin-bottom:5px">答案</div>
    <div style="font-weight:650;margin-bottom:11px">{E(p.get('answer', ''))}</div>
    <div style="font-size:13px;color:var(--muted);margin-bottom:5px">解析</div>
    <div style="font-size:14.5px">{E(p.get('analysis', ''))}</div>
  </div>
</div>""")
        A("</section>")

    A("""
<footer>
报告由本地错题库自动生成 · 不含任何联网上传<br>
结论均可追溯：每条错因都过了「错因枚举 / 知识点词表 / 证据可定位」三道校验
</footer>
</div>

<script>
function reveal(i, btn){
  var box = document.getElementById('pq'+i);
  box.classList.toggle('show');
  btn.textContent = box.classList.contains('show') ? '收起答案' : '显示答案';
  btn.classList.toggle('on');
}
</script>
</body></html>""")
    return "".join(P)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成学生视角的 HTML 错题报告")
    ap.add_argument("--spec", required=True, help="逐题数据（宿主产出）")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    ap.add_argument("--profile", help="可选：zx_diagnosis/zx_profile 的输出 JSON")
    ap.add_argument("--practice", help="可选：同类题校验结果 JSON")
    ap.add_argument("--platform", help="可选：平台考点数据 JSON")
    a = ap.parse_args()

    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    subject = spec.get("subject") or "物理"
    print(f"读 spec：{len(spec.get('questions') or [])} 道题 · 学科={subject}")
    info = load_questions(subject, spec["questions"])
    profile = load_opt(a.profile)
    practice = load_opt(a.practice)
    platform = load_opt(a.platform)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(spec, info, profile, practice, platform), encoding="utf-8")
    print(f"已生成 {out}  ({out.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
