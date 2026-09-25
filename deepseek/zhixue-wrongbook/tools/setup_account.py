"""一次性录入智学网账号密码 → 登录 → 存会话 + 存账密（全程只需这一次）。

2026-09-25 按项目主人决策新增：目标「用户全程只需登录一次」。
录入后 Cookie 失效会自动用本机存档的账密重登（adapters/auto_login.py），
用户再也不用碰 F12 / 复制 Cookie。

用法
----
    .venv/Scripts/python tools/setup_account.py

    # 也可以带参数（适合脚本化；密码会出现在命令行历史里，交互式更安全）
    .venv/Scripts/python tools/setup_account.py --account 13xxxxxxxxx --password xxx

密码存系统凭据管理器（keyring 不可用时降级 Windows DPAPI 加密文件），
与 Cookie 同级保护，不落明文。
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters import auto_login          # noqa: E402
from adapters import session as session_store   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="录入智学网账号密码（一次即可）")
    ap.add_argument("--account", default="", help="手机号 / 准考证号")
    ap.add_argument("--password", default="", help="密码（不带此参数则隐藏输入）")
    args = ap.parse_args()

    account = args.account.strip() or input("智学网账号（手机号或准考证号）: ").strip()
    password = args.password or getpass.getpass("密码（输入不回显）: ")
    if not account or not password:
        print("账号和密码都不能为空。")
        return 2

    print("正在登录……")
    try:
        cookie = auto_login.login_with_password(account, password)
    except auto_login.AutoLoginError as exc:
        print(f"登录失败：{exc}")
        return 1

    stored = auto_login.save_credentials(account, password)
    saved = session_store.set_cookie(cookie)
    print("登录成功 ✓")
    print(f"账密已存：{stored}")
    print(f"会话已存：backend={saved.get('backend', saved)}")
    print("完成 —— 以后 Cookie 失效会自动重登，无需再手动登录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
