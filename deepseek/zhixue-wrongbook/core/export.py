"""输出层：错题本 Markdown/Excel、练习卷 HTML/PDF、校验报告。

一条原则：**导出的东西必须自带出处**。
错题表里带「来源通道」，练习卷里带「AI 生成，仅供参考」和逐题校验结果。
不给自己看的报告里藏信息——因为这些文件会被打印出来复习，
打印件上如果没写「这题是 AI 改的」，三天后自己都会当真题。
"""

from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import CODE_DEPENDENCY_MISSING, ZxError
from .models import WrongQuestion, html_to_text

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "templates" / "paper.html"
OUT_DIR = ROOT / "out"

SOURCE_LABEL = {"api": "接口", "api-homework": "作业接口", "export": "官方导出", "manual": "手动录入"}


# ---------------------------------------------------------------------------
# HTML 白名单清洗（2026-09-27 新增，优化.md #18）
#
# 题干 HTML 来自平台（可能带富文本）或宿主生成，直接插进导出页等于把
# 不可信 HTML 写进本地 file:// 页面 —— <script>、on* 事件、javascript:
# 链接都能执行。这里做一层**黑名单剥除**：脚本类标签连内容一起删，
# 事件属性与危险协议一律剥掉。白名单式（只留允许标签）对题干里的
# 公式 <img data-latex> / 上下标太容易误伤，黑名单 + 转义兜底更合适。
# 已知残余风险：形如 javas&#99;ript: 的实体编码协议不在此层处理；
# 个人自用 + 打印场景下这是够用的第一道闸。
# ---------------------------------------------------------------------------
_DANGEROUS_BLOCK_RE = re.compile(
    r"<\s*(script|style|iframe|object|embed|link|meta|base|form|svg|math)\b[^>]*>"
    r".*?<\s*/\s*\1\s*>", re.I | re.S)
_DANGEROUS_OPEN_RE = re.compile(
    r"<\s*(script|style|iframe|object|embed|link|meta|base|form|svg|math)\b[^>]*/?\s*>",
    re.I)
_EVENT_ATTR_RE = re.compile(
    r"\son[a-z0-9]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_DANGEROUS_URL_RE = re.compile(
    r"(?<=\s)(?:href|src|action|xlink:href|formaction|poster)\s*=\s*"
    r"(\"|')?\s*(?:javascript|vbscript|data:text/html)[^\"'>\s]*", re.I)


def sanitize_html(text: str | None) -> str:
    """剥除题干 HTML 里可执行的部分，保留普通标签/图片/公式结构。"""
    if not text:
        return ""
    out = _DANGEROUS_BLOCK_RE.sub("", text)
    out = _DANGEROUS_OPEN_RE.sub("", out)
    out = _EVENT_ATTR_RE.sub("", out)
    out = _DANGEROUS_URL_RE.sub("", out)
    return out


def _cell(text: str | None, limit: int = 60) -> str:
    """Markdown 单元格：换行压成空格，竖线转义，超长截断。"""
    if not text:
        return ""
    s = " ".join(str(text).split()).replace("|", "\\|")
    return s if len(s) <= limit else s[:limit] + "…"


# ---------------------------------------------------------------------------
# 错题本表格
# ---------------------------------------------------------------------------
def wrongbook_markdown(questions: list[WrongQuestion],
                       title: str = "错题本") -> str:
    lines = [f"# {title}", "",
             f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　"
             f"共 {len(questions)} 题", "",
             "| # | 学科 | 考试 | 题型 | 得分 | 难度 | 班级得分率 | 错因 | 知识点 | 复习状态 | 来源 |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, q in enumerate(questions, 1):
        a = q.analysis
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            i, _cell(q.subject), _cell(q.exam.name), _cell(q.question.type, 12),
            f"{q.score.got}/{q.score.full}"
            if q.score.got is not None and q.score.full is not None else "-",
            f"{q.question.difficulty:.2f}" if q.question.difficulty is not None else "-",
            f"{q.question.class_score_rate:.2f}" if q.question.class_score_rate is not None else "-",
            _cell(a.error_type if a else "未分析", 12),
            _cell("、".join(a.knowledge_points) if a else "", 40),
            _cell("、".join(f"{h.date}:{h.result}" for h in q.history) or "未复习", 24),
            SOURCE_LABEL.get(q.source, q.source),
        ))
    lines += ["", "---", "",
              "> 来源通道含义：接口 = 通过 zhixuewang 库拉取；官方导出 = 解析你自己导出的 PDF/doc；手动录入 = 手工补录。",
              "> 低解析置信度的题（parse_confidence < 0.5）默认不出现在本表中。"]
    return "\n".join(lines)


def wrongbook_xlsx(questions: list[WrongQuestion], path: str | Path) -> str:
    """导出 Excel。openpyxl 未安装时给出明确提示而不是静默失败。"""
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise ZxError(
            "未安装 openpyxl，无法导出 xlsx。执行："
            ".venv/Scripts/python -m pip install openpyxl",
            code=CODE_DEPENDENCY_MISSING,
            missing=["python 包 openpyxl"],
            suggested_action=["运行 .venv/Scripts/python -m pip install openpyxl",
                              "或改用 zx_export_wrongbook(fmt=\"md\")"]) from exc
    wb = Workbook()
    ws = wb.active
    ws.title = "错题本"
    ws.append(["序号", "学科", "考试", "日期", "题型", "得分", "满分", "难度",
               "班级得分率", "错因", "知识点", "证据", "置信度", "需复核",
               "复习状态", "来源通道", "来源版本", "抓取时间", "解析置信度"])
    for i, q in enumerate(questions, 1):
        a = q.analysis
        ws.append([
            i, q.subject, q.exam.name, q.exam.date or "", q.question.type,
            q.score.got, q.score.full, q.question.difficulty,
            q.question.class_score_rate,
            a.error_type if a else "", "、".join(a.knowledge_points) if a else "",
            " | ".join(a.evidence) if a else "", a.confidence if a else "",
            "是" if (a and a.needs_review) else "",
            "、".join(f"{h.date}:{h.result}" for h in q.history) or "",
            SOURCE_LABEL.get(q.source, q.source), q.source_version,
            str(q.fetched_at), q.parse_confidence,
        ])
    for col, width in zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                          [6, 8, 16, 12, 10, 8, 8, 8, 12, 14, 40, 40, 10, 8, 20, 12, 24, 26, 12]):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return str(path)


# ---------------------------------------------------------------------------
# 练习卷
# ---------------------------------------------------------------------------
DEFAULT_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{{TITLE}}</title><style>
body{font-family:"Microsoft YaHei",system-ui,sans-serif;max-width:820px;margin:0 auto;
padding:32px 24px;line-height:1.7;color:#1f2328;background:#fff}
h1{font-size:22px;border-bottom:2px solid #1f2328;padding-bottom:8px}
.meta{color:#6a737d;font-size:13px;margin-bottom:24px}
.q{border:1px solid #d8dee4;border-radius:8px;padding:16px 18px;margin:18px 0}
.qh{display:flex;justify-content:space-between;font-size:13px;color:#57606a;margin-bottom:10px}
.stem{font-size:15px}
.tags{margin-top:10px;font-size:12px;color:#57606a}
.ans{margin-top:12px;padding-top:12px;border-top:1px dashed #d8dee4;font-size:14px;
background:#f6f8fa;border-radius:6px;padding:12px}
.ai{display:inline-block;background:#fff8c5;border:1px solid #d4a72c;color:#7d4e00;
font-size:12px;padding:1px 6px;border-radius:4px;margin-left:6px}
.bad{color:#cf222e}.good{color:#1a7f37}
footer{margin-top:36px;padding-top:16px;border-top:1px solid #d8dee4;
font-size:12px;color:#6a737d}
@media print{.q{page-break-inside:avoid}}
</style></head><body>
<h1>{{TITLE}}</h1>
<div class="meta">{{META}}</div>
{{BODY}}
<footer>{{FOOTER}}</footer>
</body></html>
"""


def _load_template() -> str:
    if TEMPLATE_PATH.exists():
        return TEMPLATE_PATH.read_text(encoding="utf-8")
    return DEFAULT_TEMPLATE


def _as_list(v: Any) -> list:
    """把宿主可能给的几种形状统一成 list。

    为什么需要（2026-09-24 实测暴露）：zx_export_paper 收的是宿主手写的 JSON，
    而同一个字段在**本项目的其他工具里**就有两种合法写法——
    submit_analysis 明文接受「| 分隔字符串 或 JSON 数组」。
    于是宿主给 knowledge_points 传 "物理/声与光/光的折射|物理/声与光/光的反射"
    完全合理。但原来的 render_paper 直接 '、'.join(那个字符串)，
    结果是**逐字拆开**：物、理、/、声、与、光……

    这比崩溃更危险——它不报错，只是安静地渲染出一份看起来有内容、
    实际已经花掉的练习卷，打印出来才发现。
    """
    if v is None or v == "":
        return []
    if isinstance(v, (list, tuple, set)):
        return [x for x in v if x not in (None, "")]
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("["):                      # 宿主把列表 json.dumps 了
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [x for x in parsed if x not in (None, "")]
            except ValueError:
                pass
        # 与 submit_analysis 的 _split 保持一致：| 分隔
        return [p.strip() for p in s.split("|") if p.strip()]
    return [v]


# submit_solution 的 verdict → (记号, CSS 类, 中文标签)
_VERDICT_STYLE = {
    "match": ("✔", "good", "一致"),
    "numeric_match": ("✔", "good", "数值一致"),
    "mismatch": ("✘", "bad", "不一致"),
    "undecidable": ("○", "", "无法判定"),
    "partial": ("○", "", "部分正确"),
}


def _verification_marks(v: Any) -> list[str]:
    """把 verification 归一成一组 HTML 片段。

    宿主有两条自然来源，产出的形状**不一样**，这里都得认：
      - check_practice → checks: [{name, kind, passed, value, detail}]（list[dict]）
      - submit_solution → comparison.verdict: "match" / "mismatch" / "undecidable"（str）

    修之前只认第一种：传字符串会被当成可迭代对象逐字符遍历，
    然后在 'm'.get(...) 上抛 AttributeError，整个导出直接失败。
    """
    if v in (None, ""):
        return []
    raw = v if isinstance(v, (list, tuple)) else [v]
    out = []
    for chk in raw:
        if isinstance(chk, dict):
            passed = chk.get("passed")
            kind = chk.get("kind")
            cls = "good" if passed else ("bad" if kind == "hard" else "")
            mark = "✔" if passed else ("✘" if kind == "hard" else "○")
            name = chk.get("name", chk.get("label", ""))
            val = chk.get("value", "")
            out.append(f'<span class="{cls}">{mark} {html.escape(str(name))}'
                       f'={html.escape(str(val))}</span>')
        else:
            s = str(chk).strip()
            mark, cls, label = _VERDICT_STYLE.get(s, ("○", "", s))
            out.append(f'<span class="{cls}">{mark} {html.escape(label)}</span>')
    return out


def render_paper(items: list[dict], title: str = "错题同类练习卷",
                 meta: str = "", footer: str = "",
                 answer_layout: str = "key") -> str:
    """items: 每项 {gen_id, subject, kp(list), difficulty, qtype, stem_html,
                      answer, analysis, verified, verification(list[dict]),
                      source_topic(str), attempts(int)}

    kp 与 verification 都走归一化，接受「| 分隔字符串 / JSON 数组 / 单值」，
    免得宿主按别的工具的约定传值时被静默拆字或直接崩掉（见 _as_list 的注释）。

    answer_layout（Task3，移植 qwen practice/items.ts 的「答案隔离」原则）：
    学生面对的练习卷，默认不该把答案印在每题正下方 —— 一打开就看见答案，
    这份卷子作为练习就废了。qwen 的做法是题卡（cardOf）永不含 answer/analysis，
    只有 zx_answer_reveal 显式调用才给；deepseek 侧是宿主自己出题（写题时就
    知道答案），reveal 工具是空壳，所以把隔离落在**导出产物**上：
      * "key"（默认）—— 题目区不含答案；答案与解析汇总到卷末独立的
        「参考答案与解析」页（内联 page-break，打印另起一页，可裁下单独保管）。
      * "inline"     —— 旧行为：答案与解析直接印在每题下方（教师/讲评用）。
      * "hidden"     —— 全卷不含任何答案（纯学生卷），答案由持有者另行保管。
    """
    layout = (answer_layout or "key").strip().lower()
    if layout not in ("key", "inline", "hidden"):
        layout = "key"
    blocks = []
    key_rows: list[tuple[int, dict]] = []
    for i, it in enumerate(items, 1):
        vmarks = _verification_marks(it.get("verification"))
        verified = it.get("verified")
        badge = ('<span class="ai">AI 生成，仅供参考</span>' if verified
                 else '<span class="ai" style="background:#ffebe9;border-color:#cf222e;'
                      'color:#82071e">校验未通过，需人工确认</span>')
        kp_text = "、".join(str(x) for x in
                           _as_list(it.get("kp") or it.get("knowledge_points")))
        # 答案隔离：只有 inline 布局才把答案印在题目下方；key 收集到卷末，
        # hidden 完全不渲染。
        ans_block = ""
        if layout == "inline":
            ans_block = (
                '  <div class="ans"><b>参考答案：</b>'
                f'{html.escape(str(it.get("answer", "")))}<br>\n'
                '    <b>解析：</b>'
                f'{html.escape(str(it.get("analysis", "")))}</div>\n')
        elif layout == "key":
            key_rows.append((i, it))
        blocks.append(f"""<div class="q">
  <div class="qh"><span>第 {i} 题 · {html.escape(str(it.get('qtype', '')))}</span>
    <span>{html.escape(str(it.get('subject', '')))} · 难度 {html.escape(str(it.get('difficulty', '-')))}</span></div>
  <div class="stem">{sanitize_html(it.get('stem_html', ''))}{badge}</div>
  <div class="tags">知识点：{html.escape(kp_text)}
    　|　改写自：{html.escape(str(it.get('source_topic', '-')))}</div>
{ans_block}  <div class="tags">校验：{'　'.join(vmarks) if vmarks else '未校验'}
    　|　重做次数：{it.get('attempts', 1)}</div>
</div>""")
    body = "\n".join(blocks) if blocks else "<p>（空卷）</p>"

    # 卷末独立答案页（key 布局）：用内联 page-break 而非模板 CSS 类 ——
    # 用户即使换了自定义模板（templates/paper.html）也照样另起一页。
    if layout == "key" and key_rows:
        lis = []
        for i, it in key_rows:
            lis.append(
                f'<li style="margin-bottom:10px"><b>第 {i} 题</b>　参考答案：'
                f'{html.escape(str(it.get("answer", "")))}'
                f'<br><span style="color:#57606a">解析：'
                f'{html.escape(str(it.get("analysis", "")))}</span></li>')
        body += (
            '\n<div class="answer-key" style="page-break-before:always;'
            'margin-top:36px;border-top:2px solid #1f2328;padding-top:16px">\n'
            '<h2 style="font-size:18px;margin:0 0 8px">参考答案与解析</h2>\n'
            '<p style="color:#6a737d;font-size:13px;margin:0 0 12px">'
            '先做完再对答案。本页打印时另起一页，可裁下由家长/老师单独保管。</p>\n'
            '<ol style="list-style:none;padding-left:0;line-height:1.9;margin:0">\n'
            + "\n".join(lis) + '\n</ol>\n</div>')

    if footer:
        footer_text = footer
    elif layout == "inline":
        footer_text = ("本卷题目由 AI 依据本地错题库检索改写生成，"
                       "每道题均附答案与解析，并标注了确定性校验结果。"
                       "校验未通过的题请勿直接使用。")
    elif layout == "hidden":
        footer_text = ("本卷题目由 AI 依据本地错题库检索改写生成，不含答案"
                       "（纯练习卷）；答案与解析由出题方另行保管。"
                       "卷面标注了确定性校验结果，校验未通过的题请勿直接使用。")
    else:  # key
        footer_text = ("本卷题目由 AI 依据本地错题库检索改写生成，答案与解析"
                       "汇总在卷末「参考答案与解析」页（打印另起一页）。"
                       "卷面标注了确定性校验结果，校验未通过的题请勿直接使用。")
    html_out = (_load_template()
                .replace("{{TITLE}}", html.escape(title))
                .replace("{{META}}", html.escape(meta) or
                         f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
                .replace("{{BODY}}", body)
                .replace("{{FOOTER}}", html.escape(footer_text)))
    return html_out


def write_paper(items: list[dict], out_path: str | Path | None = None,
                title: str = "错题同类练习卷", meta: str = "",
                answer_layout: str = "key") -> str:
    html_out = render_paper(items, title=title, meta=meta,
                            answer_layout=answer_layout)
    if out_path is None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUT_DIR / f"paper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_out, encoding="utf-8")
    return str(out_path)


def _find_browser() -> tuple[str, str] | None:
    """找一个 Chromium 系浏览器的可执行文件，返回 (名字, 完整路径)。

    为什么不能只用 shutil.which（2026-09-24 实测暴露）：
    Windows 上 Chrome / Edge **不注册到 PATH** —— 它们只待在安装目录里，
    另外在注册表 App Paths 下登记（那是给 ShellExecute 用的，which 不查）。
    于是这台机器明明装了 Edge 和 Chrome（标准路径都在），
    try_pdf 却报「本机未检测到 …Chrome / Edge 命令行转换器」，
    把一条本来完全能走通的 PDF 导出路径给堵死了。
    """
    import shutil

    names = ["chrome", "chrome.exe", "msedge", "msedge.exe", "chromium",
             "chromium.exe", "google-chrome", "chromium-browser"]

    # 1) PATH 里能直接找到的（Linux、或用户手动加过 PATH）
    for n in names:
        hit = shutil.which(n)
        if hit:
            return (n[:-4] if n.endswith(".exe") else n, hit)

    # 2) 各平台的常见安装位置
    if os.name == "nt":
        # 环境变量不一定在。2026-09-24 实测：某些宿主/沙箱里
        # ProgramFiles 与 ProgramFiles(x86) 直接是 None（PATH 也被洗过），
        # 光靠 os.environ 会漏掉明明装在标准位置的浏览器。
        # 所以环境变量只当「先试一下」，最后一定要回落到字面量路径。
        roots = [os.environ.get("ProgramFiles"),
                 os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("LOCALAPPDATA"),
                 r"C:\Program Files",
                 r"C:\Program Files (x86)",
                 os.path.expanduser(r"~\AppData\Local")]
        rels = [(r"Google\Chrome\Application\chrome.exe", "chrome"),
                (r"Microsoft\Edge\Application\msedge.exe", "msedge"),
                (r"Chromium\Application\chrome.exe", "chromium")]
        for root in roots:
            if not root:
                continue
            for rel, label in rels:
                p = Path(root) / rel
                if p.is_file():
                    return (label, str(p))
    else:
        macs = [("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "chrome"),
                ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "msedge"),
                ("/Applications/Chromium.app/Contents/MacOS/Chromium", "chromium")]
        for p, label in macs:
            if Path(p).is_file():
                return (label, p)
        for p in ("/usr/bin/google-chrome", "/usr/bin/chromium",
                  "/usr/bin/chromium-browser", "/snap/bin/chromium"):
            if Path(p).is_file():
                return ("chrome", p)
    return None


def try_pdf(html_path: str | Path) -> dict:
    """尝试把 HTML 转 PDF。找不到可用转换器时**明确说没有**，不假装成功。

    设计文档说输出 HTML / PDF，但 PDF 需要外部渲染器。
    这里探测常见方案；都没有就返回 available=False + 安装建议。
    """
    import subprocess
    html_path = Path(html_path)
    pdf_path = html_path.with_suffix(".pdf")

    # weasyprint / wkhtmltopdf：这两个是正经在 PATH 上的命令行工具，which 够用
    for name, cmd in (("weasyprint", ["weasyprint", str(html_path), str(pdf_path)]),
                      ("wkhtmltopdf", ["wkhtmltopdf", "--enable-local-file-access",
                                       str(html_path), str(pdf_path)])):
        import shutil
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            if pdf_path.exists() and pdf_path.stat().st_size > 0:
                return {"available": True, "converter": name, "pdf": str(pdf_path)}
        except Exception:
            continue

    # Chromium 系（Chrome / Edge / Chromium）无头打印。
    # 这两次尝试的差别只在 --no-pdf-header-footer：老版本 Chrome 不认这个开关，
    # 认的话就能去掉页眉页脚（打印练习卷时那行 file:// 路径很难看）。
    found = _find_browser()
    if found:
        name, exe = found
        for extra in (["--no-pdf-header-footer"], []):
            pdf_path.unlink(missing_ok=True)
            try:
                subprocess.run(
                    [exe, "--headless", "--disable-gpu", *extra,
                     f"--print-to-pdf={pdf_path}", html_path.as_uri()],
                    check=True, capture_output=True, timeout=120)
            except Exception:
                # 不要在这里 continue。Chrome 完全可能已经把 PDF 写出来了，
                # 却因为一条无关的告警以非零码退出（实测见过）。
                # 所以异常之后照样往下看文件在不在，以文件为准。
                pass
            if pdf_path.exists() and pdf_path.stat().st_size > 0:
                return {"available": True, "converter": name, "pdf": str(pdf_path),
                        "note": "由本机浏览器无头打印生成，版式与 Ctrl+P 一致。"}

    return {
        "available": False,
        "reason": "本机未检测到 weasyprint / wkhtmltopdf / Chrome / Edge / Chromium",
        "html": str(html_path),
        "how_to": "浏览器打开 HTML 后 Ctrl+P → 另存为 PDF（无需安装任何东西）；"
                  "或 pip install weasyprint",
    }


def write_json_report(data: Any, out_path: str | Path) -> str:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return str(out_path)
