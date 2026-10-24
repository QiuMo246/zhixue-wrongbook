"""登录智学网 —— **默认走浏览器**，不要求用户碰命令行账密。

为什么默认是浏览器
------------------
这台机器对应的账号被智学网风控命中：账密登录必然返回「验证码错误」
（不是密码错，别去改密码）。终端里弹不出验证码，`setup_account.py`
这条路在本机走不通。所以默认入口改成「拉起专用浏览器 → 人工登录一次 →
自动取 Cookie 存进系统凭据管理器」。

用法
----
    # 默认：拉起专用浏览器，人工登录，自动取会话（最常用）
    .venv/Scripts/python tools/login.py

    # 浏览器已经登录好了，直接取会话
    .venv/Scripts/python tools/login.py --no-wait

    # 只看当前会话是否还有效，不动浏览器
    .venv/Scripts/python tools/login.py --status

    # 只启动浏览器，先不取 Cookie
    .venv/Scripts/python tools/login.py --start-only

    # 显式要求账密登录（仅限**未被风控**的账号 / 其他机器）
    .venv/Scripts/python tools/login.py --password

安全边界
--------
- 专用浏览器用独立 profile（`data/.browser-cdp/`），**绝不碰用户真实 Chrome**。
- Cookie 存系统凭据管理器（keyring / DPAPI / AES-GCM 加密文件），不落明文。
- 本脚本不绕过、不破解任何验证码。

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

from adapters import session as session_store      # noqa: E402
from adapters import zhixue_web                     # noqa: E402
from core.pycmd import run_tool                     # noqa: E402


def show_status() -> int:
    """打印会话状态。0=有效 / 1=失效或没有 / 2=网络不通。"""
    cookie = session_store.get_cookie()
    if not cookie:
        print("没有已保存的会话。")
        print(f"登录：{run_tool('tools/login.py')}")
        return 1
    probe = zhixue_web.session_check(cookie)
    st = probe.get("status")
    print(f"存储后端：{session_store.backend_name()}")
    if st == "valid":
        print("会话有效 ✓")
        return 0
    if st == "unreachable":
        print(f"网络不通，没法判断：{probe.get('detail')}")
        print("先查网络/代理，别急着重登。")
        return 2
    print(f"会话已失效：errorCode={probe.get('error_code')}"
          f"（{probe.get('error_info')}）")
    print(f"重新登录：{run_tool('tools/login.py')}")
    return 1


def password_login() -> int:
    """账密登录（保留路径，仅未被风控的账号可用）。"""
    from adapters import auto_login

    print("=" * 56)
    print("账密登录 —— 仅适用于**未被风控**的账号。")
    print("被风控的账号必然返回「验证码错误」，请改用默认的浏览器登录。")
    print("=" * 56)

    import getpass
    account = input("智学网账号（手机号或准考证号）: ").strip()
    password = getpass.getpass("密码（输入不回显）: ")
    if not account or not password:
        print("账号和密码都不能为空。")
        return 2

    print("正在登录……")
    try:
        cookie = auto_login.login_with_password(account, password)
    except auto_login.AutoLoginError as exc:
        print(f"登录失败：{exc}")
        print(f"\n大概率是风控命中。改用浏览器登录：{run_tool('tools/login.py')}")
        return 1

    stored = auto_login.save_credentials(account, password)
    saved = session_store.set_cookie(cookie)
    print("登录成功 ✓")
    print(f"账密已存：{stored}")
    print(f"会话已存：backend={saved.get('backend', saved)}")
    return 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="登录智学网（默认走专用浏览器，不用命令行账密）")
    ap.add_argument("--status", action="store_true",
                    help="只查会话状态，不启动浏览器")
    ap.add_argument("--password", action="store_true",
                    help="改用账密登录（仅未被风控的账号）")
    ap.add_argument("--no-wait", action="store_true",
                    help="浏览器已登录好，直接取会话")
    ap.add_argument("--start-only", action="store_true",
                    help="只启动浏览器，不取 Cookie")
    ap.add_argument("--no-verify", action="store_true",
                    help="跳过联网校验")
    args = ap.parse_args()

    if args.status:
        return show_status()
    if args.password:
        return password_login()

    # 默认路径：浏览器。tools/ 不是 package，把目录加进 sys.path 再导入。
    sys.path.insert(0, str(ROOT / "tools"))
    import session_from_browser as sfb
    return sfb.run(no_wait=args.no_wait, start_only=args.start_only,
                   no_verify=args.no_verify)


if __name__ == "__main__":
    raise SystemExit(main())
