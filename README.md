# 智学网错题助手

把智学网里的错题自动同步到本机 → AI 助手分析每道题错在哪、标注知识点 → 找出你最弱的地方 → 出同类题给你练 → 做完自动批改。

**项目介绍与功能展示**：https://qiumo-zxw.pages.dev

**代码在 [`deepseek/zhixue-wrongbook/`](deepseek/zhixue-wrongbook/) 目录里**，
安装方法、隐私声明、三条取数通道和「已知局限」都在那份
[完整的 README](deepseek/zhixue-wrongbook/README.md) 里。

## 最快安装方式（推荐）

把下面这段话发给你的 AI 助手，剩下的它替你完成：

> 帮我安装智学网错题助手：从 Gitee 克隆 https://gitee.com/qiu_moRs/zhixue-wrongbook 到本地，
> 阅读 deepseek/zhixue-wrongbook/README.md 并按其中的「学生最懒安装法」完成安装和配置。

## 仓库结构

```
deepseek/zhixue-wrongbook/   # 全部代码、测试、文档都在这里
├─ server.py                 # MCP Server 入口（26 个工具）
├─ adapters/                 # 三条取数通道
├─ core/                     # 校验闸门、画像、导出
├─ tools/                    # 328 项离线自检脚本
└─ web/                      # 宣传网页（https://qiumo-zxw.pages.dev）
```
