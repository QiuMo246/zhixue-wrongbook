"""打开专用浏览器 → 你手动登录智学网 → 自动取 Cookie 存会话。

为什么需要它
------------
智学网对部分账号开了风控，登录必须人工过验证码（`setup_account.py` 会报
`验证码错误`）。本项目刻意不绕过风控，所以这类账号必须「人工登录一次」。

以前的做法是让用户 F12 → copy(document.cookie) → 再跑脚本。这个脚本把
中间那步省掉了：浏览器是本项目**自己**用 `--remote-debugging-port` 拉起的
专用实例（profile 在 `data/.browser-cdp/`，与日常 Chrome 完全隔离），
所以可以直接通过 CDP 把 Cookie 读出来，用户只需要「输账号密码 + 过验证码」。

⚠️ 安全边界：只连本项目自己拉起的那个实例（端口来自 marker 文件），
**不会**、也无法去读用户日常浏览器的 profile。

用法
----
    # 最省事：自动启动浏览器 → 你登录 → 回车 → 自动取 Cookie
    .venv/Scripts/python tools/session_from_browser.py

    # 浏览器已经开着并登录好了，直接取
    .venv/Scripts/python tools/session_from_browser.py --no-wait

    # 只启动浏览器，不取 Cookie
    .venv/Scripts/python tools/session_from_browser.py --start-only

退出码：0 成功 / 1 失败 / 2 环境问题。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 中文 Windows 下管道输出默认 cp936，中文 + ✓ 在 AI 助手捕获场景会崩。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters import browser_collect as bc        # noqa: E402
from adapters import session as session_store     # noqa: E402
from adapters import zhixue_web                    # noqa: E402
from adapters import zhixuewang as zxw             # noqa: E402
from core.errors import ZxError                     # noqa: E402
from core.pycmd import run_tool                     # noqa: E402

# 只认智学网的域 —— 守护浏览器里可能同时开了别的标签
COOKIE_URLS = [
    "https://www.zhixue.com/",
    "https://www.zhixue.com/errorbook/",
    "https://www.zhixue.com/login",
]


def _find_zhixue_tab(port: int) -> dict | None:
    """在守护实例里找智学网标签页。找不到返回 None。"""
    tabs = bc._http_json(f"http://127.0.0.1:{port}/json/list") or []
    for tb in tabs:
        if tb.get("type") == "page" and bc.matches_pattern(
                tb.get("url", ""), "zhixue.com"):
            return tb
    return None


def read_cookies(port: int) -> dict[str, str]:
    """通过 CDP 读守护实例里智学网的 Cookie。返回 {name: value}。

    用 Network.getCookies 而不是 document.cookie：前者由浏览器侧返回，
    不受页面 JS 环境（比如页面还没加载完）影响，也能拿到 HttpOnly 的
    （智学网实测没有 HttpOnly，但这样更稳）。
    """
    target = _find_zhixue_tab(port)
    if target is None:
        raise ZxError(
            "守护浏览器里没有 zhixue.com 的标签页。",
            code="browser_not_running",
            suggested_action=["在打开的浏览器窗口里访问 https://www.zhixue.com/ 并登录"])

    t = bc.CdpTransport(target["webSocketDebuggerUrl"])
    try:
        t.request("Network.enable")
        res = t.request("Network.getCookies", {"urls": COOKIE_URLS})
    finally:
        t.close()

    out: dict[str, str] = {}
    for c in res.get("cookies") or []:
        name = c.get("name")
        value = c.get("value")
        if name and value is not None:
            out[name] = value          # 同名 Cookie 以最后一个为准（path 更具体的在后）
    return out


def cookies_to_string(d: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in d.items())


def run(no_wait: bool = False, start_only: bool = False,
        no_verify: bool = False) -> int:
    """浏览器登录主流程。返回退出码（0 成功 / 1 失败 / 2 环境问题）。

    2026-10-24 从 main() 抽出：tools/login.py 需要复用同一套流程，
    命令行参数解析留在 main()，这里只收已经解析好的布尔量。
    """
    # --- 1. 确保守护浏览器在跑 ---
    st = bc.daemon_status()
    if st.get("running"):
        port = int(st["port"])
        print(f"守护浏览器已在运行（端口 {port}）。")
    else:
        print("正在启动专用浏览器……（会弹出一个新的 Chrome 窗口）")
        try:
            info = bc.start_daemon()
        except ZxError as exc:
            print(f"启动失败：{exc}")
            return 2
        if not info.get("ok"):
            print(f"启动失败：{info}")
            return 2
        port = int(info["port"])
        print(f"已启动（端口 {port}）。")
        if info.get("first_run"):
            print("这是该专用 profile 的第一次使用 —— 需要登录一次，之后就不用再登了。")

    if start_only:
        print("\n浏览器已就绪。请在窗口里登录智学网，然后重跑本脚本（加 --no-wait）。")
        return 0

    # --- 2. 等用户登录 ---
    if not no_wait:
        print("\n" + "=" * 56)
        print("请在刚打开的浏览器窗口里完成登录：")
        print("  1. 输入账号（手机号 / 准考证号）")
        print("  2. 输入密码")
        print("  3. 如果出现验证码，照着填")
        print("  4. 登录成功后，**能看到自己的页面**（不是登录框）")
        print("=" * 56)
        try:
            input("\n登录完成后，按回车继续……")
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            return 2

    # --- 3. 读 Cookie ---
    print("正在读取 Cookie……")
    try:
        d = read_cookies(port)
    except ZxError as exc:
        print(f"读取失败：{exc}")
        return 1

    if not d:
        print("没读到任何 Cookie —— 大概率还没登录成功。")
        print("请确认浏览器窗口里能看到你的个人页面，再重试。")
        return 1

    print(f"读到 {len(d)} 个 Cookie。")

    # --- 4. 字段检查 ---
    try:
        zxw.check_cookie_dict(d)
        print("字段检查通过：含 loginUserName ✓")
    except Exception as exc:
        print(f"字段检查失败：{exc}")
        print("\n说明登录还没真正完成。请在浏览器里确认已登录后再试。")
        return 1

    # --- 5. 保存 + 校验 ---
    cookie = cookies_to_string(d)
    try:
        saved = session_store.set_cookie(cookie)
        print(f"会话已保存：backend={saved.get('backend', saved)}")
    except Exception as exc:
        print(f"保存失败：{type(exc).__name__}: {exc}")
        return 1

    if no_verify:
        print("已跳过联网校验。")
        return 0

    print("正在联网校验……")
    probe = zhixue_web.session_check(cookie)
    status = probe.get("status")
    if status == "unreachable":
        print(f"网络不通，没法校验：{probe.get('detail')}")
        print("Cookie 已经存下来了，网络恢复后跑 zx_session_status 再确认。")
        return 0
    if status == "expired":
        print(f"服务端不认：errorCode={probe.get('error_code')}"
              f"（{probe.get('error_info')}）")
        print("请确认浏览器里已登录（能看到个人页面），再重试。")
        return 1

    print("校验通过 ✓ 会话有效。")
    print("\n接下来：对 AI 助手说「帮我同步错题」，或运行")
    print(f"  {run_tool('tools/mcp_cli.py')} zx_sync '{{}}'")
    return 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="专用浏览器登录 → 自动取 Cookie")
    ap.add_argument("--no-wait", action="store_true",
                    help="不等待登录，浏览器已登录好时用")
    ap.add_argument("--start-only", action="store_true",
                    help="只启动浏览器，不取 Cookie")
    ap.add_argument("--no-verify", action="store_true",
                    help="跳过联网校验")
    args = ap.parse_args()
    return run(no_wait=args.no_wait, start_only=args.start_only,
               no_verify=args.no_verify)


if __name__ == "__main__":
    raise SystemExit(main())
