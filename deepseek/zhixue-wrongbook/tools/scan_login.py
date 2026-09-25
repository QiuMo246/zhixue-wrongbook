"""扫码登录助手：弹出浏览器让你登录一次，Cookie 自动抓取并存入系统凭据管理器。

⚠️ 实测警告（2026-09-24）：**这条路会被智学网风控拦**
------------------------------------------------------
在真实账号上实测时，本脚本弹出的自动化 Chrome 登录到一半，
智学网返回了「极验封禁 / Error code: 60500」。

原因（推断，但有充分依据）：Playwright 启动的浏览器带有明显的自动化特征
（`navigator.webdriver`、CDP 连接痕迹等），智学网的风控组件（极验）能识别。
连续两次弹出登录窗口会更快触发。

**所以：优先用下面那条「手工复制 Cookie」的路，本脚本只当备选。**

推荐路径（不触发风控）：
  1. 在你**日常使用的浏览器**里正常登录智学网（真实人类操作，风控不拦）
  2. F12 → Console → 执行 `copy(document.cookie)`
  3. 回来跑：
         .venv/Scripts/python tools/scan_login.py --from-clipboard
     本脚本从剪贴板取 Cookie，存进凭据管理器，并立刻联网验证。
     这样 Cookie 不经过聊天记录、不落明文文件。

如果一定要用浏览器路径，请注意：
  · 别短时间内反复重试（会加重风控，可能需要等几十分钟才恢复）
  · 风控提示出现后，先在你自己浏览器里正常登录一次，通常能恢复

---

为什么需要它
------------
`tools/verify_p0.py` 要求你自己按 F12，从浏览器网络面板里抠出 `Cookie:` 那一整行。
对不熟悉开发者工具的人来说，这一步最容易出问题（少个字段、少个分号、
复制到响应头而不是请求头），而且失败了只看到一个 KeyError。

本脚本把这一步自动化：

  1. 弹出一个**独立的 Chrome 窗口**（独立 profile 目录，不碰你日常浏览器的登录态）
  2. 你在窗口里正常登录 —— 扫码 / 账号密码 / 微信，随便哪种都行
  3. 脚本自己盯着 Cookie，**并且真的问一次服务器确认可用**才抓取
  4. 存进 Windows 凭据管理器，顺手验证能不能拉到考试列表

隐私
----
- Cookie 完整值**不打印、不写明文文件**（走 `adapters/session.py` 的 keyring / DPAPI）
- 本脚本只调用「当前用户 + 考试列表」两个只读接口
- **不调用任何同学信息接口**
- 登录窗口用的是项目自己的 profile 目录，与你日常浏览器完全隔离

用法
----
    # 推荐：先从浏览器把 Cookie 复制到剪贴板，再执行这条
    .venv/Scripts/python tools/scan_login.py --from-clipboard

    # 备选：弹窗登录（可能触发风控，见上方警告）
    .venv/Scripts/python tools/scan_login.py
    .venv/Scripts/python tools/scan_login.py --timeout 600
    .venv/Scripts/python tools/scan_login.py --cookie "..." # 直接给 Cookie
    .venv/Scripts/python tools/scan_login.py --show-browser # 保留窗口，便于排错

跑完 Cookie 就在系统凭据管理器里了，接着直接跑：
    .venv/Scripts/python tools/verify_p0.py
"""

from __future__ import annotations

import argparse
import base64
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOGIN_URL = "https://www.zhixue.com/login.html"
HOME_HOST = "zhixue.com"
PROFILE_DIR = ROOT / "data" / ".browser_profile"

# 登录成功的判据：这个 Cookie 出现 = 服务端已认你。库也硬依赖它（account.py:59）
KEY_COOKIE = "loginUserName"

# 这几个是判断「Cookie 是不是一整套」的辅助字段（缺失只是警告）
NICE_TO_HAVE = ("token", "userName", "JSESSIONID")


def sep(title: str = "") -> None:
    print("\n" + "=" * 66)
    if title:
        print(title)
        print("=" * 66)


# ---------------------------------------------------------------------------
# 剪贴板（不依赖 tkinter / PowerShell，纯 ctypes 调 Windows API）
# ---------------------------------------------------------------------------
def _read_clipboard() -> str:
    """读 Windows 剪贴板里的文本。

    为什么不用 tkinter：精简版 Python 常常没带 tkinter。
    为什么不用 PowerShell：从某些沙箱环境里调用会被安全策略拦掉。
    ctypes 直连 user32 最稳，且零额外依赖。

    ⚠️ 必须显式声明 argtypes / restype：
    ctypes 默认把返回值当 32 位 int，而句柄和指针在 64 位下是 64 位，
    不声明就会把地址截断成野指针 —— 实测直接段错误（踩过）。
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL

    if not user32.OpenClipboard(None):
        raise RuntimeError("打不开剪贴板（可能被其他程序占用，稍后重试）")
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            raise RuntimeError("锁定剪贴板内存失败")
        try:
            return ctypes.wstring_at(ptr) or ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _looks_like_cookie(text: str) -> bool:
    """判断剪贴板内容像不像一段 Cookie。

    为什么不用「必须包含 loginUserName」当判据：
    `document.cookie` 读不到 HttpOnly 的字段，可能正好缺它。
    那种情况要交给后续步骤去补（`_fetch_username_via_api`），
    不能在这里就把用户挡在门外。

    判据放成：含 '=' 的键值对 ≥3 个，且整体够长。
    这样像 `202501007`（学号）这种无关文本不会被误收。
    """
    if not text or "=" not in text or len(text) < 40:
        return False
    pairs = [p for p in text.split(";") if "=" in p]
    return len(pairs) >= 3


def wait_clipboard_cookie(wait_seconds: int, quiet: bool = False) -> str:
    """等剪贴板里出现一段像 Cookie 的文本，返回它。

    这样你只要：先在浏览器里 `copy(document.cookie)`，
    再跑本脚本（或反过来，脚本会一直等），顺序随意。
    """
    deadline = time.time() + wait_seconds
    reported = 0.0
    while True:
        try:
            text = _read_clipboard().strip()
        except Exception as exc:
            text = ""
            if not quiet:
                print(f"  · 读剪贴板出错：{exc}")
        if _looks_like_cookie(text):
            return text
        if time.time() >= deadline:
            raise RuntimeError(
                f"等了 {wait_seconds} 秒，剪贴板里仍未出现 Cookie。\n"
                "请确认已在浏览器里执行 copy(document.cookie)，"
                "然后重跑本脚本。")
        if not quiet and time.time() - reported >= 10:
            reported = time.time()
            n = len(text)
            print(f"  · 还在等剪贴板…（当前内容 {n} 字符，"
                  f"需要包含 `{KEY_COOKIE}`）")
        time.sleep(2)


# ---------------------------------------------------------------------------
# Cookie 抓取
# ---------------------------------------------------------------------------
def _pick_cookies(cookies: list[dict]) -> dict[str, str]:
    """从 Playwright 的 cookie 列表里挑出智学网相关的，拼成 dict。

    同一个键可能出现在多个域（`.zhixue.com` 和 `www.zhixue.com`）。
    按域名长度**升序**写入，让更具体的域（www.zhixue.com）后写入、覆盖泛域的值
    —— 与浏览器实际发请求时的优先级一致。

    注意：**空值一律丢掉**。智学网在未登录状态下也会塞一个空的
    `loginUserName=` 进 cookie，把它当成「已登录」会误判（踩过这个坑）。
    """
    picked: dict[str, str] = {}
    relevant = [c for c in cookies if HOME_HOST in (c.get("domain") or "")]
    for c in sorted(relevant, key=lambda c: len(c.get("domain") or "")):
        name, value = c.get("name"), c.get("value")
        if name and value and value.strip():
            picked[name] = value
    return picked


def verify_cookie_live(cookie_string: str) -> tuple[bool, str]:
    """真问一次服务器：这个 Cookie 到底能不能用？

    为什么不能只看 cookie 里有没有 `loginUserName`：
    登录过程中 cookie 是**分步写入**的。先出现 loginUserName，
    之后才有 token / userName。在中间那一刻抓走，就会得到一个
    「看着像登录了、实际用不了」的残缺 Cookie（`errorCode: -200`）。

    所以判据必须是「服务端认不认」，不是「本地有没有某个字段」。
    调用的是只读接口 `/container/getCurrentUser`。
    """
    import requests

    from adapters.zhixuewang import parse_cookie_string

    try:
        session = requests.Session()
        session.cookies.update(parse_cookie_string(cookie_string))
        r = session.get("https://www.zhixue.com/container/getCurrentUser",
                        timeout=15)
        data = r.json()
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    # 智学网的**成功码是 200，不是 0**；失败码是负数（实测 -200「操作失败」）。
    # 只认 0 会把成功判成失败 —— 这个坑已经踩过一次，别再改回去。
    code = data.get("errorCode")
    if code in (0, 200) and data.get("result"):
        return True, "ok"
    return False, f"errorCode={code} {data.get('errorInfo')}"

def _to_cookie_string(picked: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in picked.items())


def _fetch_username_via_api(cookie_string: str) -> tuple[str | None, dict]:
    """兜底：有些登录方式（第三方扫码）可能不落 `loginUserName`。

    这时用 Cookie 直接问一句「我是谁」（`/container/getCurrentUser`，
    只读接口），把用户名捞出来补上 —— 库和通道 C 都要求这个字段存在。

    返回 (用户名, 原始响应的键)，捞不到就 (None, {...})。
    """
    import requests

    from adapters.zhixuewang import parse_cookie_string

    try:
        session = requests.Session()
        session.cookies.update(parse_cookie_string(cookie_string))
        r = session.get("https://www.zhixue.com/container/getCurrentUser",
                        timeout=20)
        data = r.json()
    except Exception as exc:
        return None, {"error": f"{type(exc).__name__}: {exc}"}
    result = data.get("result") or {}
    if not isinstance(result, dict):
        return None, {"keys": list(data.keys())}
    # 平台不同版本的字段名不一样，按可能性依次找
    for key in ("loginName", "userName", "user_name", "account", "uname"):
        v = result.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip(), {"keys": sorted(result.keys()), "matched": key}
    return None, {"keys": sorted(result.keys())}


# ---------------------------------------------------------------------------
# 浏览器登录
# ---------------------------------------------------------------------------
def login_via_browser(timeout: int, keep_open: bool) -> tuple[str | None, str]:
    """弹出 Chrome，等用户登录，返回 (cookie 字符串, 状态说明)。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, ("未安装 playwright。请执行：\n"
                      "  .venv/Scripts/python -m pip install playwright\n"
                      "或直接用 --cookie 传入 Cookie 字符串。")

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # 用系统已装的 Chrome，不额外下载浏览器内核（省磁盘）
        launch_kwargs = dict(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            channel="chrome",
            locale="zh-CN",
            viewport={"width": 1280, "height": 900},
            args=["--no-first-run", "--no-default-browser-check"],
        )
        try:
            ctx = p.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as exc:
            return None, (f"启动 Chrome 失败：{type(exc).__name__}: {exc}\n"
                          "提示：本机需装有 Chrome（或用 --cookie 直接传 Cookie）。")

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            print(f"打开登录页失败（{exc}），请手动在窗口里访问 {LOGIN_URL}")

        sep("请在弹出的 Chrome 窗口里登录智学网")
        print("  · 扫码 / 账号密码 / 微信，随便哪种都行")
        print(f"  · 脚本在等「服务端认可」——最多等 {timeout} 秒")
        print("  · 登录成功后窗口会自己关掉（加了 --show-browser 则保留）")
        print("  · 登录窗口用的是独立 profile，不影响你日常浏览器的登录状态")
        print("  · 中途不要手动关窗口，慢慢来就行")

        deadline = time.time() + timeout
        cookie_string = ""
        last_note = 0.0
        last_probe = 0.0
        while time.time() < deadline:
            try:
                cookies = ctx.cookies()
                landed = page.url
            except Exception as exc:
                return None, f"读取浏览器 Cookie 失败（窗口可能被关掉了）：{exc}"

            found = _pick_cookies(cookies)
            candidate = _to_cookie_string(found) if found else ""

            # 只有在「看起来像登录了」且距上次探测 ≥3 秒时才真去问服务器，
            # 免得对平台发太多请求
            looks_logged_in = (KEY_COOKIE in found) or (
                "login.html" not in landed and "token" in found)
            if looks_logged_in and candidate and time.time() - last_probe >= 3:
                last_probe = time.time()
                ok, msg = verify_cookie_live(candidate)
                if ok:
                    time.sleep(1.5)          # 让最后几个 cookie 落定
                    found = _pick_cookies(ctx.cookies())
                    cookie_string = _to_cookie_string(found)
                    print("\n  ✅ 服务端已确认登录有效")
                    break
                if time.time() - last_note >= 15:
                    last_note = time.time()
                    print(f"  · 检测到登录痕迹但还没放行（{msg}），继续等…")
            time.sleep(1.5)
        else:
            if not keep_open:
                ctx.close()
            return None, (f"等待超时（{timeout} 秒）仍未拿到可用的 Cookie。\n"
                          "可能原因：还没登录完 / 扫的是旧二维码 / 登录被中断。\n"
                          "直接重跑本脚本即可，或用 --timeout 给更多时间。")

        if not keep_open:
            try:
                ctx.close()
            except Exception:
                pass

    if not cookie_string:
        return None, "登录窗口里没抓到任何智学网 Cookie。"
    return cookie_string, "ok"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookie", default="", help="已有 Cookie 字符串，跳过浏览器")
    ap.add_argument("--from-clipboard", action="store_true",
                    help="从剪贴板取 Cookie（推荐：不触发风控，凭证不进聊天记录）")
    ap.add_argument("--wait", type=int, default=300,
                    help="--from-clipboard 时最多等剪贴板多少秒（默认 300）")
    ap.add_argument("--timeout", type=int, default=300, help="等待登录的秒数")
    ap.add_argument("--show-browser", action="store_true", help="登录后保留窗口")
    ap.add_argument("--no-verify", action="store_true", help="跳过联网验证")
    args = ap.parse_args()

    from adapters.session import backend_name, set_cookie

    # --- 1. 拿 Cookie ---
    if args.cookie.strip():
        cookie_string = args.cookie.strip()
        print(f"使用命令行传入的 Cookie（长度 {len(cookie_string)}）")
    elif args.from_clipboard:
        print(f"Cookie 将存入：{backend_name()}")
        sep("从剪贴板取 Cookie")
        print("  如果你还没复制，现在去浏览器里操作（脚本会一直等）：")
        print("    1) 打开 https://www.zhixue.com 并确认已登录")
        print("    2) F12 → Console → 输入 copy(document.cookie) 回车")
        print(f"  最多等 {args.wait} 秒。")
        try:
            cookie_string = wait_clipboard_cookie(args.wait)
        except RuntimeError as exc:
            sep("失败")
            print(exc)
            return 1
        print(f"\n✅ 已从剪贴板读到 Cookie（长度 {len(cookie_string)}）")
    else:
        print(f"Cookie 将存入：{backend_name()}")
        cookie_string, status = login_via_browser(args.timeout, args.show_browser)
        if not cookie_string:
            sep("失败")
            print(status)
            return 1
        print(f"\n✅ 已抓到 Cookie（长度 {len(cookie_string)}）")

    from adapters.zhixuewang import (CookieError, check_cookie_dict,
                                     parse_cookie_string)

    cookie_dict = parse_cookie_string(cookie_string)

    # --- 2. 缺 loginUserName 就尝试补 ---
    if KEY_COOKIE not in cookie_dict:
        sep("Cookie 里没有 loginUserName，尝试用只读接口补齐")
        print("（某些登录方式不落这个字段，但库和通道 C 都要求它存在）")
        username, meta = _fetch_username_via_api(cookie_string)
        if username:
            cookie_dict[KEY_COOKIE] = username
            cookie_string = _to_cookie_string(cookie_dict)
            print(f"  ✅ 已从 getCurrentUser 补上 loginUserName"
                  f"（字段：{meta.get('matched')}）")
        else:
            print(f"  ✗ 没补上。接口返回的字段：{meta}")
            print("  建议：在登录窗口里改用「账号登录」（手机号 + 密码）重试。")
            return 1

    warnings = check_cookie_dict(cookie_dict)
    print(f"解析出 {len(cookie_dict)} 个键：{sorted(cookie_dict)}")
    for w in warnings:
        print(f"  ⚠ {w}")

    # --- 3. 先确认服务端认这个 Cookie，再存 ---
    # 为什么要多这一步：登录过程中 Cookie 是分步写入的，
    # 抓早了会得到一个「字段齐全但服务端不认」的残缺凭证。
    # 存进去只会让后面每一步都报看不懂的错，不如在这里挡住。
    if not args.no_verify:
        sep("向服务器确认这个 Cookie 能不能用")
        ok, msg = verify_cookie_live(cookie_string)
        if ok:
            print("  ✅ 服务端已确认有效")
        else:
            print(f"  ✗ 服务端不认：{msg}")
            print("  常见原因：Cookie 不完整 / 已过期 / 复制到了别的东西。")
            print("  建议重新在浏览器里执行 copy(document.cookie)，再跑一次。")
            print("  （为避免留下无效凭据，本次不写入凭据管理器）")
            return 1

    # --- 4. 存进系统凭据管理器 ---
    sep("保存 Cookie")
    info = set_cookie(cookie_string)
    print(f"  backend = {info['backend']}")
    print(f"  length  = {info['length']}")
    if info.get("note"):
        print(f"  note    = {info['note']}")

    if args.no_verify:
        return 0

    # --- 4. 立刻验证能不能用 ---
    sep("验证：通道 B（zhixuewang 库）")
    try:
        from adapters.zhixuewang import LIB_VERSION, list_exams, login, to_student
        print(f"  库版本：{LIB_VERSION}")
        student = to_student(login(cookie_string))
        print("  ✅ 登录成功，确认是学生账号")
        exams = list_exams(student, limit=5)
        for e in exams[:5]:
            print(f"     {e['name']}  id={e['id']}  date={e['date']}")
        print(f"  共取到 {len(exams)} 场考试")
        if not exams:
            print("  ⚠ 考试列表为空 —— Cookie 有效，但这个账号暂时没有考试记录")
    except Exception as exc:
        print(f"  ✗ 通道 B 失败：{type(exc).__name__}: {exc}")
        print("  接着试通道 C（自建接口），它不依赖库的解析逻辑。")

    sep("验证：通道 C（自建裸接口）")
    try:
        from adapters.zhixue_web import probe
        result = probe(cookie_string)
        print(f"  role = {result.get('role')}")
        for s in result["steps"]:
            mark = "✅" if s["ok"] else "✗"
            print(f"  {mark} {s['step']}：{s.get('sample') or s.get('error')}")
        if result.get("latest_exam"):
            print(f"  最近考试：{result['latest_exam']}")
        if result.get("hint"):
            print(f"  提示：{result['hint']}")
    except Exception as exc:
        print(f"  ✗ 通道 C 失败：{type(exc).__name__}: {exc}")

    sep("完成")
    print("Cookie 已存入系统凭据管理器，后续不用再登录。")
    print("下一步：")
    print("  .venv/Scripts/python tools/verify_p0.py      # 核实真实字段（难度刻度等）")
    print("  .venv/Scripts/python server.py               # 启动 MCP Server")
    print("\n提醒：如果你在浏览器里点了「退出登录」，这个 Cookie 会立刻失效，"
          "重跑本脚本即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
