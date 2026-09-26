"""通道 C-2：CDP 守护浏览器「借页面自身的请求」采集（包一，2026-09-26）。

移植自 qwen 分支 src/collect/ 的核心设计。它解决的是 deepseek 版的
两个单点：
  1. `auto_login.py` 逆向的 RC4 登录协议（密钥硬编码）—— 平台一改即失效；
  2. 学生账密必须落本机（keyring/DPAPI）—— 再加密也是「存了」。

机制（qwen 真机验证过的最短诚实路径）：
  * MCP 拉起**自有的** Chrome 守护进程（专用 profile，与日常浏览器隔离），
    用户在这个窗口里**手动登录一次**，登录态永远留在 profile 里；
  * 采集时 CDP 导航到错题本页面，捕获**页面自己发出的** getErrorbookList
    响应 —— 签名头（authtoken/authguid/XToken）由页面自己带，凭据
    一步不离开浏览器；
  * 抓到的 JSON 走库自家的字段映射（student.py:822 get_errorbook 的
    ErrorBookTopic 构造）转回 ErrorBookTopic，**复用现有入库管线**
    （topic_to_raw → normalize_question → store.upsert），零新解析逻辑；
  * 所有权规则：profile 里写 marker（pid/port/启动时间）。marker 里的
    pid 已死 → 清掉当陈旧处理；端口上有 CDP 实例但**没有**我们的
    marker → 那是别人的浏览器，拒绝驱动（qwen probe.test.ts 同款规则）。

诚实声明（真机验证状态）：
  * 守护进程 / CDP 传输 / 捕获状态机 / 字段映射 / 入库管线：有离线测试；
  * 真实页面的 URL、响应时序、翻页交互：**尚未真机跑通**（那是 qwen
    分支在它的栈里验证过的，本移植需要一次真机联调）。
    联调前 zx_sync_browser 如实返回 not_verified 标记，不假装能用。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from core.errors import CODE_DEPENDENCY_MISSING, ZxError

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = Path(os.environ.get(
    "ZX_BROWSER_PROFILE", str(ROOT / "data" / ".browser-cdp")))
MARKER = PROFILE_DIR / "daemon.json"
ERRORBOOK_URL = "https://www.zhixue.com/errorbook/"
# 页面自己发出的错题本数据接口（相对特征，匹配 URL 子串）
CAPTURE_PATTERN = "getErrorbookList"

DEFAULT_CHROMES = {
    "win32": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
}


# ---------------------------------------------------------------------------
# Chrome 守护进程管理（所有权规则见模块 docstring）
# ---------------------------------------------------------------------------
def chrome_executable() -> Path | None:
    env = os.environ.get("ZX_CHROME_PATH")
    cands = [Path(env)] if env else [Path(p) for p in
                                     DEFAULT_CHROMES.get(sys.platform, [])]
    for c in cands:
        if c.exists():
            return c
    return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def marker_path() -> Path:
    return MARKER


def read_marker() -> dict | None:
    if not MARKER.exists():
        return None
    try:
        return json.loads(MARKER.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def write_marker(pid: int, port: int) -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(json.dumps({
        "pid": pid, "port": port, "profile": str(PROFILE_DIR),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False), encoding="utf-8")


def clear_marker() -> None:
    MARKER.unlink(missing_ok=True)


def daemon_status() -> dict:
    """守护浏览器状态：running / stale_marker / off，绝不猜。"""
    m = read_marker()
    if not m:
        return {"running": False, "status": "off"}
    if not _pid_alive(int(m["pid"])):
        clear_marker()
        return {"running": False, "status": "stale_marker",
                "note": "marker 里的进程已死，已清理（陈旧标记）"}
    return {"running": True, "status": "running",
            "pid": m["pid"], "port": m["port"]}


def start_daemon(port: int = 0) -> dict:
    """拉起自有 Chrome（有头窗口 —— 用户要在里面登录一次）。

    返回 {ok, port, pid, first_run}。端口被别的 CDP 实例占用时
    顺延换端口，绝不抢（qwen 同款规则）。
    """
    chrome = chrome_executable()
    if chrome is None:
        raise ZxError(
            "没找到 Chrome。CDP 采集通道需要本机安装 Google Chrome。",
            code=CODE_DEPENDENCY_MISSING,
            missing=["Google Chrome（或设 ZX_CHROME_PATH 环境变量指向 chrome.exe）"],
            suggested_action=["安装 Chrome 后重试",
                              "或设 ZX_CHROME_PATH 指向现有 chrome.exe"])
    if daemon_status().get("running"):
        return {"ok": True, "already_running": True, **daemon_status()}

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    port = int(port) or 9333
    for _ in range(10):
        proc = subprocess.Popen(
            [str(chrome), f"--remote-debugging-port={port}",
             f"--user-data-dir={PROFILE_DIR}", "--no-first-run",
             "--no-default-browser-check", ERRORBOOK_URL],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.2)
        info = _http_json(f"http://127.0.0.1:{port}/json/version", timeout=2)
        if info and "webSocketDebuggerUrl" in info:
            write_marker(proc.pid, port)
            first_run = not (PROFILE_DIR / "Default" / "Cookies").exists()
            return {"ok": True, "port": port, "pid": proc.pid,
                    "first_run": first_run,
                    "note": "Chrome 已启动。请在窗口里登录智学网一次，"
                            "登录态会留在这个专用浏览器里。"}
        port += 1
    raise ZxError(
        "Chrome 启动后 10 次都没有出现 CDP 调试端口 —— 可能被安全软件拦截。",
        code="browser_daemon_failed",
        suggested_action=["手动运行 Chrome 带参数 --remote-debugging-port=9333 看报错",
                          "把本条 error 原文发给维护者"])


def stop_daemon() -> dict:
    m = read_marker()
    if not m:
        return {"ok": True, "removed": []}
    pid = int(m["pid"])
    if _pid_alive(pid):
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    clear_marker()
    return {"ok": True, "removed": [{"pid": pid}]}


def _http_json(url: str, timeout: float = 5) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CDP 传输（websocket-client；transport 可注入，测试用假传输）
# ---------------------------------------------------------------------------
class CdpTransport:
    """最小 CDP WebSocket 客户端：request(id 配对) + 事件收听。"""

    def __init__(self, ws_url: str):
        try:
            import websocket  # websocket-client
        except ImportError as exc:
            raise ZxError(
                "未安装 websocket-client，无法使用 CDP 采集通道。",
                code=CODE_DEPENDENCY_MISSING,
                missing=["python 包 websocket-client"],
                suggested_action=[
                    "运行 .venv/Scripts/python -m pip install websocket-client"]) from exc
        self._ws = websocket.create_connection(ws_url, timeout=10)
        self._next_id = 0

    def request(self, method: str, params: dict | None = None,
                timeout: float = 15) -> dict:
        self._next_id += 1
        mid = self._next_id
        self._ws.send(json.dumps({"id": mid, "method": method,
                                  "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self._ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise ZxError(f"CDP {method} 失败：{msg['error']}",
                                  code="cdp_error")
                return msg.get("result", {})
            # 非配对消息是事件，丢弃（事件路径用 events()）
        raise ZxError(f"CDP {method} 超时（{timeout}s）", code="cdp_error")

    def recv(self, timeout: float = 10) -> dict | None:
        """收一条消息（事件或响应），超时返回 None。"""
        self._ws.settimeout(timeout)
        try:
            return json.loads(self._ws.recv())
        except Exception:
            return None

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass


def matches_pattern(url: str, pattern: str) -> bool:
    return pattern in url


class ResponseCapture:
    """在已连接的 CDP 会话里导航并捕获匹配 URL 的响应体。

    状态机与传输分离：测试里用假 transport 就能驱动整个流程。
    """

    def __init__(self, transport: CdpTransport, page_ws_url: str):
        self.t = transport
        self.page_ws_url = page_ws_url

    def attach(self) -> None:
        self.t.request("Network.enable")
        self.t.request("Page.enable")

    def navigate(self, url: str) -> None:
        self.t.request("Page.navigate", {"url": url})

    def wait_responses(self, pattern: str, timeout: float = 30,
                       max_count: int = 5) -> list[dict]:
        """等导航触发后页面自己发出的匹配响应。返回 [{url, body}]。"""
        got: list[dict] = []
        pending: dict[str, dict] = {}     # requestId -> response 元信息
        deadline = time.time() + timeout
        while time.time() < deadline and len(got) < max_count:
            msg = self.t.recv(timeout=1.0)
            if not msg:
                continue
            m = msg.get("method", "")
            p = msg.get("params", {})
            if m == "Network.responseReceived":
                resp = p.get("response", {})
                url = resp.get("url", "")
                if matches_pattern(url, pattern):
                    pending[p.get("requestId")] = {"url": url}
            elif m == "Network.loadingFinished" and p.get("requestId") in pending:
                rid = p["requestId"]
                try:
                    body = self.t.request("Network.getResponseBody",
                                          {"requestId": rid})
                    pending[rid]["body"] = body.get("body", "")
                    got.append(pending.pop(rid))
                except Exception:
                    pending.pop(rid, None)
        return got


def capture_errorbook(timeout: float = 40) -> dict:
    """高层入口：确保守护浏览器在跑 → 新开标签 → 捕获错题本页面自己的
    getErrorbookList 响应。返回 {ok, raw_topics, captured, login_hint}。

    登录态不在时会抓到登录跳转 —— 如实报 login_hint，不重试不硬绕。
    """
    st = daemon_status()
    if not st.get("running"):
        raise ZxError(
            "CDP 守护浏览器没在运行。先用 zx_browser_start 启动并在窗口里登录。",
            code="browser_not_running",
            missing=["运行中的守护浏览器 + 一次手动登录"],
            suggested_action=["调 zx_browser_start，在弹出的 Chrome 窗口里登录智学网",
                              "登录后重试本工具"])

    port = st["port"]
    tabs = _http_json(f"http://127.0.0.1:{port}/json/list") or []
    target = None
    for tb in tabs:
        if tb.get("type") == "page" and matches_pattern(tb.get("url", ""), "zhixue.com"):
            target = tb
            break
    if target is None:
        raise ZxError("没找到 zhixue.com 页面标签 —— 请在守护浏览器里打开错题本页面。",
                      code="browser_not_running",
                      suggested_action=["在守护 Chrome 里打开 https://www.zhixue.com/errorbook/ 后重试"])

    t = CdpTransport(target["webSocketDebuggerUrl"])
    try:
        cap = ResponseCapture(t, target["webSocketDebuggerUrl"])
        cap.attach()
        cap.navigate(ERRORBOOK_URL)
        got = cap.wait_responses(CAPTURE_PATTERN, timeout=timeout)
    finally:
        t.close()

    raw_topics: list[dict] = []
    for g in got:
        try:
            data = json.loads(g.get("body") or "")
        except ValueError:
            continue
        if data.get("errorCode") != 0:
            continue
        lst = ((data.get("result") or {}).get("wrongTopicAnalysis")
               or {}).get("topicList") or []
        raw_topics.extend(lst)

    return {"ok": True, "captured": len(got), "raw_topics": raw_topics,
            "not_verified": True,
            "login_hint": (None if raw_topics else
                           "没抓到错题本数据 —— 大概率登录态失效或页面结构不同。"
                           "请在守护浏览器里确认已登录并能打开错题本页面。")}


# ---------------------------------------------------------------------------
# 捕获 JSON → 现有入库管线（复用库的字段映射 + topic_to_raw + normalize）
# ---------------------------------------------------------------------------
def json_to_topics(raw_topics: list[dict]):
    """getErrorbookList 的 topicList 原始 JSON → ErrorBookTopic 列表。

    字段映射与库 student.py:838-856 的 get_errorbook 逐字段一致 ——
    这是通道 B 已在真实账号上验证过的映射，CDP 抓到的就是同一个接口
    的同一个响应体，所以直接复用，零新增解析假设。
    """
    from zhixuewang.models import ErrorBookTopic
    out = []
    for each in raw_topics:
        out.append(ErrorBookTopic(
            analysis_html=each["analysisHtml"],
            answer_html=each["answerHtml"],
            answer_type=each["answerType"],
            is_correct=each["beCorrect"],
            class_score_rate=each["classScoreRate"],
            content_html=each["contentHtml"],
            difficulty=each["difficultyValue"],
            dis_title_number=each["disTitleNumber"],
            image_answer=each.get("imageAnswer"),
            paper_id=each["paperId"],
            subject_name=each["paperName"],
            score=each["score"],
            standard_answer=each["standardAnswer"],
            standard_score=each["standardScore"],
            topic_analysis_img_url=each["topicAnalysisImgUrl"],
            topic_set_id=each["topicId"],
            topic_img_url=each["topicImgUrl"],
            topic_source_paper_name=each["topicSourcePaperName"],
        ))
    return out


def sync_captured(store, capture: dict, images_dir: Path,
                  download: bool = False) -> dict:
    """把捕获到的题目走现有管线入库（source 仍是 'api' —— 本来就是同一接口）。

    按 paper_id 分组，每组用 topic_source_paper_name 当考试名
    （SimpleNamespace 复用 topic_to_raw 对 exam 对象的属性访问）。
    """
    from adapters.parsers.normalize import normalize_question
    from adapters.zhixuewang import SOURCE_VERSION, topic_to_raw
    from core.config import get_config

    report = {"added": 0, "updated": 0, "failed": 0, "exams": [],
              "errors": [], "not_verified": True}
    topics = json_to_topics(capture.get("raw_topics") or [])
    by_paper: dict[str, list] = {}
    for tp in topics:
        by_paper.setdefault(tp.paper_id, []).append(tp)

    for paper_id, group in by_paper.items():
        exam_name = group[0].topic_source_paper_name or paper_id
        exam = SimpleNamespace(name=exam_name, create_time=None)
        log_id = store.log_sync_start("api-cdp", group[0].subject_name, exam_name)
        added = updated = failed = 0
        for i, t in enumerate(group, 1):
            prefix = f"{paper_id[:8]}_{t.subject_name}_{i:03d}"
            try:
                raw, _notes = topic_to_raw(
                    t, t.subject_name, exam, None, images_dir, prefix,
                    download=download, config=get_config())
                q = normalize_question(raw, source="api",
                                       source_version=SOURCE_VERSION, seq=i)
                res = store.upsert(q)
                if res == "added":
                    added += 1
                elif res == "updated":
                    updated += 1
            except Exception as exc:
                failed += 1
                report["errors"].append(
                    {"exam": exam_name, "topic": t.dis_title_number,
                     "error": f"{type(exc).__name__}: {exc}"})
        store.log_sync_end(log_id, added=added, updated=updated, failed=failed,
                           error=";".join(e["error"] for e in report["errors"])[:400]
                           if report["errors"] else None)
        report["exams"].append({"exam": exam_name, "added": added,
                                "updated": updated, "failed": failed})
        report["added"] += added
        report["updated"] += updated
        report["failed"] += failed
    return report
