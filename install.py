"""仓库根的安装入口：本仓库把项目放在 deepseek/zhixue-wrongbook/ 子目录，
学生的 AI 不应该关心目录结构 —— 本脚本自动定位真正的项目并委派安装。

    python install.py --config --account <账号> --password <密码>
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def find_project() -> Path:
    direct = HERE / "deepseek" / "zhixue-wrongbook"
    if (direct / "install.py").exists():
        return direct
    for cand in sorted(HERE.glob("*/install.py")) + \
            sorted(HERE.glob("*/*/install.py")):
        d = cand.parent
        if (d / "server.py").exists() and (d / "requirements.txt").exists():
            return d
    raise SystemExit(
        "没找到 zhixue-wrongbook 项目（含 server.py 的目录）。"
        "把这段输出发给你的 AI 排查。")


def main() -> int:
    project = find_project()
    print(f"==> 项目位于 {project}", flush=True)
    return subprocess.run([sys.executable, str(project / "install.py"),
                           *sys.argv[1:]]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
