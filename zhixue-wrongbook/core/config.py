"""配置加载。默认值全部写在 config.yaml 里，代码只负责读。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"

DEFAULTS = {
    "difficulty": {"scale": "unknown", "assumed_max": None,
                   "verified_by": "", "verified_at": ""},
    "data": {"db_path": "data/wrongbook.db", "images_dir": "data/images",
             "taxonomy": "data/taxonomy.yaml"},
    "host": {"model_id": "host:unknown", "prompt_version": "analyze-v3"},
    "sync": {"max_exams": 20, "download_images": True},
}


class Config:
    def __init__(self, data: dict | None = None):
        merged = {}
        for k, v in DEFAULTS.items():
            merged[k] = dict(v)
            merged[k].update((data or {}).get(k) or {})
        self._d = merged

    def __getitem__(self, key: str) -> dict:
        return self._d[key]

    @property
    def difficulty_scale(self) -> str:
        return str(self._d["difficulty"]["scale"]).strip().lower()

    @property
    def assumed_max(self) -> float | None:
        v = self._d["difficulty"].get("assumed_max")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def difficulty_is_verified(self) -> bool:
        """难度刻度是否已被人工核实。false 时难度闸门降级为软参考。"""
        scale = self.difficulty_scale
        if scale == "0-1":
            return True
        if scale == "raw" and self.assumed_max:
            return True
        return False

    def path(self, key: str) -> Path:
        """取数据路径。支持环境变量覆盖，方便测试时不碰真实库：

            ZX_DB_PATH     覆盖 data.db_path
            ZX_IMAGES_DIR  覆盖 data.images_dir
            ZX_TAXONOMY    覆盖 data.taxonomy

        ⚠️ 路径陷阱（2026-09-25 实测踩到的）

        在 Git Bash 里用 `$PWD` 给环境变量赋值，会得到 `/d/Data/...` 这种
        POSIX 风格路径。Python 在 Windows 上把它当成**「当前盘符下的相对路径」**
        `\\d\\Data\\...`，于是：

          · 在别处**静默新建了一个空库**
          · 工具照常运行，只是所有科目都显示「0 道题」
          · 使用者看到「本地还没有任何错题数据」，
            完全猜不到是路径指错了

        所以这里做两件事：
          1. Git Bash 风格路径（`/d/xxx`）在 Windows 上**自动转换成** `D:\\xxx`
             —— 这是 Git Bash 的既定约定，转换是确定性的，不是猜
          2. 其余相对路径**按 ROOT 解析**（而不是按 CWD），行为可预测
        """
        import os
        import re
        import sys as _sys

        env_key = {"db_path": "ZX_DB_PATH", "images_dir": "ZX_IMAGES_DIR",
                   "taxonomy": "ZX_TAXONOMY"}.get(key)
        raw = os.environ.get(env_key) if env_key else None
        if raw:
            if _sys.platform == "win32":
                m = re.match(r"^/([A-Za-z])/(.*)$", raw)
                if m:
                    fixed = "{}:\\{}".format(m.group(1).upper(),
                                             m.group(2).replace("/", "\\"))
                    print(f"[warn] {env_key}={raw!r} 是 Git Bash 风格路径，"
                          f"已自动转换为 {fixed!r}。"
                          f"（不转换的话会被当成「当前盘符下的相对路径」，"
                          f"很可能静默新建一个空库）", file=_sys.stderr)
                    return Path(fixed)
            p = Path(raw)
            if not p.is_absolute():
                print(f"[warn] {env_key}={raw!r} 不是绝对路径，"
                      f"已按项目根目录解析为 {ROOT / p}", file=_sys.stderr)
                p = ROOT / p
            return p
        p = Path(self._d["data"][key])
        return p if p.is_absolute() else ROOT / p

    def normalize_difficulty(self, raw_value) -> tuple[float | None, str]:
        """按配置把平台难度换算到 0~1 刻度。

        返回 (归一化值或 None, 刻度标签)。
        刻度未核实时返回原值 + 'unknown'，让下游知道「这个数不能直接比」。
        """
        if raw_value is None:
            return None, "unknown"
        try:
            v = float(raw_value)
        except (TypeError, ValueError):
            return None, "unknown"
        scale = self.difficulty_scale
        if scale == "0-1":
            return max(0.0, min(1.0, v)), "0-1"
        if scale == "raw" and self.assumed_max:
            return max(0.0, min(1.0, v / self.assumed_max)), "0-1"
        return v, "raw" if scale == "raw" else "unknown"


@lru_cache(maxsize=1)
def get_config(path: str | None = None) -> Config:
    p = Path(path) if path else CONFIG_PATH
    if p.exists():
        with open(p, "r", encoding="utf-8") as fh:
            return Config(yaml.safe_load(fh) or {})
    return Config({})
