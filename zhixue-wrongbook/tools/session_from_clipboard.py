"""从剪贴板读智学网 Cookie 并保存会话（给「被风控、账密登录走不通」的账号用）。

背景
----
智学网对部分账号开启风控，登录必须人工过验证码，程序化账密登录拿不到会话
（`tools/setup_account.py` 会报 `验证码错误`）。本项目刻意不绕过风控，
所以这类账号改走「人工登录一次 → 把浏览器里的 Cookie 交给工具」这条路。

为什么单独做这个脚本，而不是直接调 zx_session_set
------------------------------------------------
Cookie 是一长串，直接贴进对话或命令行会留在对话记录 / 命令行历史里。
本脚本从**剪贴板**读，Cookie 不经过屏幕、不进历史、不落明文文件
（`session_store` 存的是系统凭据管理器 / DPAPI 加密文件）。

用法
----
    1. 浏览器登录智学网（www.zhixue.com），确认能看到自己的页面
    2. F12 → Console → 输入并回车：
           copy(document.cookie)
       （智学网的 Cookie 没有一条是 HttpOnly，document.cookie 能拿全）
    3. 运行本脚本：
           .venv/Scripts/python tools/session_from_clipboard.py

退出码：0 成功 / 1 失败 / 2 参数或剪贴板问题。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 中文 Windows 下管道输出默认 cp936，中文 + ✓ 在 AI 助手捕获场景会崩。
# 与 install.py / setup_account.py 同款双保险。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters import session as session_store      # noqa: E402
from adapters import zhixue_web                     # noqa: E402
from adapters import zhixuewang as zxw              # noqa: E402
from core.pycmd import run_tool                     # noqa: E402


def read_clipboard() -> str:
    """读系统剪贴板文本。用 tkinter（标准库，无需装包）。"""
    try:
        import tkinter
    except ImportError:
        raise SystemExit(
            "这台机器的 Python 没有 tkinter，读不了剪贴板。\n"
            f"改用命令行传入：{run_tool('tools/session_from_clipboard.py')} "
            "--cookie \"<粘贴到这里>\"")
    root = tkinter.Tk()
    root.withdraw()
    try:
        return root.clipboard_get()
    except tkinter.TclError:
        raise SystemExit("剪贴板是空的（或内容不是文本）。先执行 copy(document.cookie)。")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def mask(cookie: str) -> str:
    """只露首尾，绝不整串打印。"""
    if len(cookie) <= 24:
        return cookie[:6] + "…" + cookie[-4:] if len(cookie) > 10 else "（过短）"
    return f"{cookie[:12]}…{cookie[-8:]}（共 {len(cookie)} 字符）"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="从剪贴板保存智学网 Cookie")
    ap.add_argument("--cookie", default="",
                    help="直接传 Cookie 字符串（会进命令行历史，不推荐）")
    ap.add_argument("--no-verify", action="store_true",
                    help="跳过联网校验（离线时用）")
    args = ap.parse_args()

    cookie = (args.cookie or "").strip() or read_clipboard().strip()
    if not cookie:
        print("没读到 Cookie。")
        return 2

    print(f"读到 Cookie：{mask(cookie)}")

    # 先做纯本地的字段检查 —— 缺 loginUserName 会在这里就拦下，
    # 不用白跑一次网络请求。
    try:
        d = zxw.parse_cookie_string(cookie)
        zxw.check_cookie_dict(d)
        print(f"字段检查通过：共 {len(d)} 个 Cookie，含 loginUserName ✓")
    except Exception as exc:
        print(f"字段检查失败：{exc}")
        print("\n常见原因：复制不完整 / 复制的不是智学网页面。")
        print("请确认浏览器停在 www.zhixue.com 的页面上，再执行 copy(document.cookie)。")
        return 1

    try:
        saved = session_store.set_cookie(cookie)
        print(f"会话已保存：backend={saved.get('backend', saved)}")
    except Exception as exc:
        print(f"保存失败：{type(exc).__name__}: {exc}")
        return 1

    if args.no_verify:
        print("已跳过联网校验。")
        return 0

    print("正在联网校验……")
    probe = zhixue_web.session_check(cookie)
    status = probe.get("status")
    if status == "unreachable":
        print(f"网络不通，没法校验：{probe.get('detail')}")
        print("Cookie 已经存下来了。网络恢复后跑一次 zx_session_status 再确认。")
        return 0
    if status == "expired":
        print(f"服务端不认这个 Cookie：errorCode={probe.get('error_code')}"
              f"（{probe.get('error_info')}）")
        print("常见原因：Cookie 过期 / 复制不完整 / 复制时页面已登出。")
        print("请在浏览器里重新登录智学网，再复制一次。")
        return 1

    print("校验通过 ✓ 会话有效。")
    print("\n接下来：对 AI 助手说「帮我同步错题」，或运行")
    print(f"  {run_tool('tools/mcp_cli.py')} zx_sync '{{}}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
