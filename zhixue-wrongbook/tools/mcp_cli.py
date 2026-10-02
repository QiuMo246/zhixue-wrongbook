"""MCP 工具命令行：不写 Python 也能直接调本项目的全部工具。

> 工具数量以 `--list` 的实际输出为准，不要在这个注释里写死数字 ——
> 2026-09-25 实测发现这里写着「16 个」，而实际已经是 **20 个**
> （后来加了 zx_export_wrongbook / zx_review_queue / zx_session_clear /
> zx_sync_log，清单没回头同步）。数字写死在注释里就一定会过期。

为什么需要它
------------
`server.py` 是 MCP 服务，正常只能被 AI 助手调用。想在终端里手动戳一下
某个工具（排错、看数据、跑一次同步），原来只能另写一个脚本。
本文件把「调一次工具」变成一行命令。

用法
----
    # 列工具
    .venv/Scripts/python tools/mcp_cli.py --list

    # 调工具（参数是 JSON，省略则传空）
    .venv/Scripts/python tools/mcp_cli.py zx_session_status
    .venv/Scripts/python tools/mcp_cli.py get_questions '{"limit":5}'
    .venv/Scripts/python tools/mcp_cli.py zx_profile '{"weak_top":5}'

    # 从文件读参数（参数很长时用，比如 submit_analysis 的 evidence）
    .venv/Scripts/python tools/mcp_cli.py submit_analysis --file args.json

    # 只要某个字段（省得看一大坨 JSON）
    .venv/Scripts/python tools/mcp_cli.py zx_profile '{"weak_top":5}' --key weak_top

注意
----
- 直接用**真实的** `data/wrongbook.db` 和真实凭据命名空间 ——
  这不是测试脚本，是操作工具。跑 `zx_sync` / `zx_purge` 会真的改数据。
- 输出是格式化 JSON，便于 Read 工具阅读。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def text_of(res) -> str:
    for block in getattr(res, "content", []) or []:
        if getattr(block, "type", "") == "text":
            return block.text
    return str(res)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tool", nargs="?", help="工具名")
    ap.add_argument("args", nargs="?", default="{}", help="参数 JSON（默认 {}）")
    ap.add_argument("--file", help="从文件读参数 JSON")
    ap.add_argument("--key", help="只输出结果的某个字段")
    ap.add_argument("--list", action="store_true", help="列出所有工具")
    ap.add_argument("--raw", action="store_true", help="不做 JSON 美化，原样输出")
    opts = ap.parse_args()

    import server

    if opts.list or not opts.tool:
        tools = await server.mcp.list_tools()
        for t in sorted(tools, key=lambda x: x.name):
            desc = (t.description or "").replace("\n", " ")
            print(f"{t.name:24s} {desc[:88]}")
        # 数量从实际注册结果算，不写死 —— 写死的数字一定会过期
        print(f"\n共 {len(tools)} 个工具"
              f"（未知参数拦截器：{server.UNKNOWN_ARG_GUARD}）")
        return 0

    if opts.file:
        payload = json.loads(Path(opts.file).read_text(encoding="utf-8"))
    else:
        payload = json.loads(opts.args or "{}")

    res = await server.mcp.call_tool(opts.tool, payload)
    raw = text_of(res)
    if opts.raw:
        print(raw)
        return 0
    try:
        data = json.loads(raw)
    except ValueError:
        print(raw)
        return 0
    if opts.key:
        cur = data
        for part in opts.key.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            elif isinstance(cur, list) and part.isdigit():
                cur = cur[int(part)]
            else:
                cur = None
                break
        print(json.dumps(cur, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
