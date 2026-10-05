"""给用户看的命令字符串要按平台生成（2026-10-05 修，测试反馈 P2-2）。

以前所有报错话术里硬编码 `.venv/Scripts/python ...`，那是 Windows venv 的
布局；Linux/macOS 的 venv 里根本没有 `Scripts` 目录（是 `bin/`），学生照抄
就是「找不到文件」。这里统一一个出口：显示用的解释器路径由平台决定。

注意这是**展示用相对路径**（假设在项目根目录下执行），不是绝对路径 ——
安装脚本自己拿绝对路径用 `install.py` 里的 `PY`。
"""

from __future__ import annotations

import os
import sys

VENV_NAME = os.environ.get("ZX_VENV_NAME", ".venv")


def is_windows() -> bool:
    return os.name == "nt" or sys.platform == "win32"


def venv_python(venv: str | None = None) -> str:
    """venv 里解释器的相对路径，按当前平台。"""
    v = venv or VENV_NAME
    return f"{v}\\Scripts\\python" if is_windows() else f"{v}/bin/python"


def pip_install(*packages: str) -> str:
    """「装某个包」的可直接执行命令（含解释器路径）。"""
    args = " ".join(packages) if packages else "需求包"
    return f"{venv_python()} -m pip install {args}"


def run_tool(script: str) -> str:
    """「跑某个工具脚本」的可直接执行命令。script 形如 tools/setup_account.py。"""
    return f"{venv_python()} {script.replace(chr(92), '/')}"
