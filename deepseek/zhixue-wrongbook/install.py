"""一键安装：学生只需要把「AI 安装指令」发给自己的 AI 助手，或自己跑本脚本。

    python install.py              # 装 venv + 依赖，打印 MCP 配置和后续步骤
    python install.py --config     # 顺带把 MCP 配置自动写进检测到的 AI 助手（带备份、幂等）
    python install.py --account 13x --password xxx
                                   # 顺带完成登录（= 用户唯一一次"登录"）

做完之后用户对 AI 助手说「帮我同步错题」就能用了。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
IS_WIN = sys.platform == "win32"
PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")

REQUIRED_IMPORTS = ["mcp", "pydantic", "yaml", "keyring", "requests", "PIL"]


def step(msg: str) -> None:
    print(f"\n==> {msg}")


def ensure_venv() -> None:
    if PY.exists():
        print(f".venv 已存在，跳过创建（{PY}）")
        return
    step("创建虚拟环境 .venv")
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)


def install_deps() -> None:
    step("安装依赖（requirements.txt + pillow + openpyxl）")
    subprocess.run([str(PY), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
                   check=True)
    subprocess.run([str(PY), "-m", "pip", "install", "--quiet",
                    "-r", str(ROOT / "requirements.txt"),
                    "pillow>=11", "openpyxl>=3.1"], check=True)


def verify_imports() -> None:
    step("验证关键依赖可导入")
    code = "import " + ",".join(REQUIRED_IMPORTS)
    r = subprocess.run([str(PY), "-c", code], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr)
        raise SystemExit("依赖验证失败 —— 把上面的报错发给你的 AI。")
    print("全部可导入 ✓")


def mcp_entry() -> dict:
    return {
        "command": str(PY),
        "args": [str(ROOT / "server.py")],
    }


def print_mcp_config() -> None:
    step("把下面这段加进你 AI 助手的 MCP 配置（或用 --config 自动写入）")
    print(json.dumps({"mcpServers": {"zhixue-wrongbook": mcp_entry()}},
                     indent=2, ensure_ascii=False))


def known_config_paths() -> list[Path]:
    home = Path.home()
    return [
        home / ".workbuddy-ai" / "mcp.json",
        home / ".zcode" / "mcp.json",
        home / ".claude" / "mcp.json",
    ]


def auto_config() -> None:
    step("自动写入 MCP 配置（找到几个写几个；已存在同名的跳过；改动前备份）")
    for path in known_config_paths():
        try:
            if not path.parent.exists():
                print(f"  跳过 {path}（没有这个 AI 助手）")
                continue
            cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            servers = cfg.setdefault("mcpServers", {})
            if "zhixue-wrongbook" in servers:
                print(f"  跳过 {path}（已配置过）")
                continue
            if path.exists():
                backup = path.with_suffix(
                    f".bak-{time.strftime('%Y%m%d%H%M%S')}.json")
                shutil.copy2(path, backup)
                print(f"  已备份原配置 → {backup.name}")
            servers["zhixue-wrongbook"] = mcp_entry()
            path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                            encoding="utf-8")
            print(f"  已写入 {path}")
        except Exception as exc:
            print(f"  写 {path} 失败：{exc}（不影响其它步骤，可手动加配置）")


def setup_account(account: str, password: str) -> None:
    step("录入账号密码（真实登录一次，之后 Cookie 失效自动重登）")
    r = subprocess.run([str(PY), str(ROOT / "tools" / "setup_account.py"),
                        "--account", account, "--password", password])
    if r.returncode != 0:
        raise SystemExit("登录失败 —— 检查账号密码后再跑一次 "
                         f"{PY} {ROOT / 'tools' / 'setup_account.py'}")


def next_steps() -> None:
    print("""
==================================================================
安装完成。接下来：
  1) 重启你的 AI 助手（或到连接器管理里点「信任」），让新 MCP 生效
  2) 如果刚才没录入账号密码，跑：
       .venv/Scripts/python tools/setup_account.py
     （这是你唯一一次需要"登录"—— 之后失效会自动重登）
  3) 对 AI 助手说「帮我同步错题」即可开始使用
==================================================================
""")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", action="store_true",
                    help="自动把 MCP 配置写入检测到的 AI 助手")
    ap.add_argument("--account", default="", help="智学网账号（手机号/准考证号）")
    ap.add_argument("--password", default="", help="密码（不带则跳过登录步骤）")
    args = ap.parse_args()

    ensure_venv()
    install_deps()
    verify_imports()
    print_mcp_config()
    if args.config:
        auto_config()
    if args.account and args.password:
        setup_account(args.account, args.password)
    next_steps()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
