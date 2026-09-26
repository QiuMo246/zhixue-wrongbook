"""一键安装：学生只需要把「AI 安装指令」发给自己的 AI 助手，或自己跑本脚本。

    python install.py              # 装 venv + 依赖，打印 MCP 配置和后续步骤
    python install.py --config     # 顺带把 MCP 配置自动写进检测到的 AI 助手（带备份、幂等）
    python install.py --account 13x --password xxx
                                   # 顺带完成登录（= 用户唯一一次"登录"）

2026-09-25 针对学生环境（没 Python / 没 git）补的两条路：

  1. **没有系统 Python**：AI 助手（WorkBuddy/ZCode）自带 Python
     （~/.workbuddy-ai/binaries/python/current/python.exe），用它跑本脚本即可。
     venv 创建失败时自动降级为「无 venv 模式」，依赖直接装进当前解释器。
     `--find-python` 可以列出本机所有可用的 Python，供 AI 选择。
  2. **没有 git**：`--from-zip` 直接下载 GitHub 的 zip 包解开（纯 urllib，
     不依赖 git），解完接着走正常安装。

做完之后用户对 AI 助手说「帮我同步错题」就能用了。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

REQUIRED_IMPORTS = ["mcp", "pydantic", "yaml", "keyring", "requests", "PIL"]

REPO = "QiuMo246/zhixue-wrongbook"          # GitHub 后备源
GITEE_REPO = "qiu_moRs/zhixue-wrongbook"    # 默认源：国内免代理直连
GITEE_TAG = "install"                       # 装安装包 zip 的 Gitee Release 标签
REPO_BRANCH = "main"

# 全局：venv 不可用时降级为「无 venv 模式」，PY 指向当前解释器
ROOT = Path(__file__).resolve().parent
VENV: Path | None = ROOT / ".venv"
PY: Path = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt"
                             else "bin/python")


def step(msg: str) -> None:
    print(f"\n==> {msg}")


# ---------------------------------------------------------------------------
# Python 探测：学生机器没有系统 Python 时，用 AI 助手自带的
# ---------------------------------------------------------------------------
def known_pythons() -> list[Path]:
    """常见 AI 助手自带的 Python，按优先级排。"""
    home = Path.home()
    cands = [
        home / ".workbuddy-ai" / "binaries" / "python" / "current" / "python.exe",
        home / ".workbuddy-ai" / "binaries" / "python" / "current" / "bin" / "python3",
        home / ".zcode" / "binaries" / "python" / "current" / "python.exe",
    ]
    # versions/<ver>/ 兜底
    for base in (home / ".workbuddy-ai" / "binaries" / "python" / "versions",
                 home / ".zcode" / "binaries" / "python" / "versions"):
        if base.exists():
            for d in sorted(base.iterdir(), reverse=True):
                cands.append(d / "python.exe")
                cands.append(d / "bin" / "python3")
    return [c for c in cands if c.exists()]


def find_python() -> str:
    """打印本机可用的 Python（给 AI 看的排障入口）。"""
    print("sys.executable =", sys.executable)
    print("AI 助手自带的 Python：")
    found = known_pythons()
    for c in found or ["（没找到）"]:
        print("  ", c)
    return sys.executable


# ---------------------------------------------------------------------------
# zip 兜底：没有 git 也能拿到代码
# ---------------------------------------------------------------------------
def locate_project(root: Path) -> Path:
    """在 root 里定位真正的项目目录（含 server.py + requirements.txt）。

    仓库可能是「工作区」布局：项目嵌在 deepseek/zhixue-wrongbook/ 里。
    两种布局都要能装，学生不应该关心目录结构。
    """
    if (root / "requirements.txt").exists() and (root / "server.py").exists():
        return root
    if root.name == "zhixue-wrongbook":
        return root
    for cand in sorted(root.rglob("install.py")):
        d = cand.parent
        if (d / "requirements.txt").exists() and (d / "server.py").exists():
            return d
    raise SystemExit(
        f"在 {root} 下没找到项目（server.py + requirements.txt）。"
        "把这段输出发给你的 AI 排查。")


def fetch_from_zip(target: Path, url: str = "") -> Path:
    """下载仓库 zip 并解开到 target（剥掉顶层目录）。纯标准库，不需要 git。"""
    # 学生环境没有代理，按国内可达性排序；逐个试，zip 魔数不对（如反爬
    # 返回 HTML 页面）也当失败继续换源。
    sources = [url] if url else [
        f"https://gitee.com/{GITEE_REPO}/releases/download/"
        f"{GITEE_TAG}/zhixue-wrongbook-{REPO_BRANCH}.zip",
        f"https://gitee.com/{GITEE_REPO}/repository/archive/{REPO_BRANCH}.zip",
        f"https://codeload.github.com/{REPO}/zip/refs/heads/{REPO_BRANCH}",
    ]
    tmp = target.parent / "_repo.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    last_err: Exception | None = None
    for src in sources:
        step(f"下载仓库 zip：{src}")
        try:
            with urllib.request.urlopen(src, timeout=120) as r, open(tmp, "wb") as f:
                f.write(r.read())
            if tmp.read(2) == b"PK":
                break
            last_err = OSError("返回内容不是 zip（多半被反爬挡了）")
            step(f"下载失败（{last_err}），换下一个源…")
        except OSError as e:
            last_err = e
            step(f"下载失败（{e}），换下一个源…")
    else:
        raise SystemExit(
            f"所有下载源都失败了（最后一个错误：{last_err}）。"
            "手动下载仓库 zip 后用 --from-zip <zip路径> 安装。")
    step(f"解压到 {target}")
    with zipfile.ZipFile(tmp) as z:
        tops = {n.split("/", 1)[0] for n in z.namelist() if n.strip("/")}
        z.extractall(target.parent)
    tmp.unlink()
    # zip 顶层是一个单目录，但名字随打包方式而变（Gitee/GitHub 命名规则不同），
    # 按解压出来的实际目录名剥掉这层挪到 target
    extracted = target.parent / next(iter(tops)) if len(tops) == 1 else None
    if extracted and extracted.exists():
        if target.exists():
            raise SystemExit(
                f"{target} 已存在 —— 换个 --target 或先删掉再试。")
        extracted.rename(target)
    elif not target.exists():
        raise SystemExit("解压后没找到仓库目录，请把上面的输出发给 AI 排查。")
    return target


# ---------------------------------------------------------------------------
# venv：创建失败自动降级为无 venv 模式
# ---------------------------------------------------------------------------
def ensure_venv(use_venv: bool = True) -> None:
    global VENV, PY
    if not use_venv:
        VENV, PY = None, Path(sys.executable)
        print("按 --no-venv 跳过虚拟环境，依赖将装进当前解释器。")
        return
    # ROOT 可能被 --from-zip 改写过，venv 路径必须按当前 ROOT 重算
    VENV = ROOT / ".venv"
    PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if PY.exists():
        print(f".venv 已存在，跳过创建（{PY}）")
        return
    step("创建虚拟环境 .venv")
    try:
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        if not PY.exists():
            raise RuntimeError("venv 创建后没有生成解释器")
    except Exception as exc:
        VENV, PY = None, Path(sys.executable)
        print(f"⚠ venv 创建失败（{exc}）—— 降级为无 venv 模式，"
              f"依赖直接装进 {PY}。")


def install_deps() -> None:
    step("安装依赖（requirements.txt + pillow + openpyxl）"
         + ("" if VENV else "（无 venv 模式 → 装进当前解释器）"))
    subprocess.run([str(PY), "-m", "pip", "install", "--quiet",
                    "--upgrade", "pip"], check=True)
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


# ---------------------------------------------------------------------------
# MCP 配置
# ---------------------------------------------------------------------------
def mcp_entry() -> dict:
    return {"command": str(PY), "args": [str(ROOT / "server.py")]}


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
            cfg = json.loads(path.read_text(encoding="utf-8")) \
                if path.exists() else {}
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
    venv_note = "" if VENV else "（无 venv 模式：把命令里的 .venv 路径换成你跑 install.py 的那个 Python）"
    print(f"""
==================================================================
安装完成。接下来：
  1) 重启你的 AI 助手（或到连接器管理里点「信任」），让新 MCP 生效
  2) 如果刚才没录入账号密码，跑：
       .venv/Scripts/python tools/setup_account.py   {venv_note}
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
    ap.add_argument("--from-zip", nargs="?", const="default", default="",
                    help="没有 git 时的兜底：直接下载仓库 zip 解压后安装"
                         "（不带 URL 用默认仓库）")
    ap.add_argument("--target", default="",
                    help="配合 --from-zip：解压目标目录（默认 ./zhixue-wrongbook）")
    ap.add_argument("--no-venv", action="store_true",
                    help="跳过 venv，依赖直接装进当前解释器")
    ap.add_argument("--find-python", action="store_true",
                    help="只列出本机可用的 Python（含 AI 助手自带的）")
    args = ap.parse_args()

    if args.find_python:
        find_python()
        return 0

    if args.from_zip:
        target = Path(args.target or "zhixue-wrongbook").resolve()
        url = "" if args.from_zip in ("", "default") else args.from_zip
        new_root = locate_project(fetch_from_zip(target, url))
        # 重新定位 ROOT 并切换过去继续安装
        global ROOT
        ROOT = new_root
        os.chdir(ROOT)

    ensure_venv(use_venv=not args.no_venv)
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
