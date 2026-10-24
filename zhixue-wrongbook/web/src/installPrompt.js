// 发给 AI 助手的安装提示词 —— 首屏的「复制安装提示词」按钮和
// 安装区的懒人安装法共用这一份，改文案只改这里。
//
// 2026-09-27 改版（优化.md 安装链路）：
//   1. 密码不再走命令行参数 —— --password 会留进命令行历史、暴露在
//      进程列表里，还会先出本机到模型供应商。改为引导 AI 带用户跑
//      tools/setup_account.py 的隐藏输入（getpass）路径。
//   2. 路径与实际仓库布局对齐：安装入口在仓库根的 install.py
//      （它会自动定位真正的项目）。
//
// 2026-10-24 改版（登录默认走浏览器）：
//   1. 账密登录降为备选。智学网对部分账号开了风控，账密必然返回
//      「验证码错误」，而终端里弹不出验证码 —— 原提示词让用户跑
//      setup_account.py，在风控账号上直接卡死。
//   2. 默认入口改为 tools/login.py：拉起专用 Chrome（独立 profile），
//      用户人工登录一次，脚本自动取 Cookie 存进系统凭据管理器。
export const AI_PROMPT = `帮我安装智学网错题助手：从 Gitee 克隆 https://gitee.com/qiu_moRs/zhixue-wrongbook 到本地（GitHub 地址 https://github.com/QiuMo246/zhixue-wrongbook 作为后备），运行仓库里的 install.py --config（它会自动定位真正的项目目录）。装好后重启 MCP 连接。

然后登录智学网：**默认走浏览器，不要让我把密码打到命令行里**。智学网对部分账号开了风控，账密登录会返回「验证码错误」（这不是密码错，别让我去改密码），而终端里弹不出验证码，所以账密这条路在很多机器上走不通。你要做的：把一条我能直接粘贴运行的完整命令发给我（用安装时那个 Python 解释器，比如仓库 .venv 里的；我电脑可能没装 Python），内容是运行 zhixue-wrongbook/tools/login.py；如果你的 MCP 工具里已经有 zx_browser_start，直接调它启动浏览器也一样。它会拉起一个**专用** Chrome 窗口（独立 profile，绝不碰我日常浏览器），我在窗口里人工登录（含验证码）。等我说「登录完了」再继续 —— 之后你跑 tools/login.py --no-wait 取会话。只有确认我的账号没被风控、并且我明确要求账密登录时，才用 tools/login.py --password；密码必须由我在终端里隐藏输入，不要写进命令行参数，也不要让我发在对话里。之后我对你说「帮我同步错题」就应该能用了。遇到报错就自己排查修好，卡住了再问我。

补充（按你的实际情况二选一，AI 看得懂）：
· 我的电脑没装 Python → 用你自己（AI）自带的 Python 执行；你也没有的话，Windows 上直接跑仓库里的 zhixue-wrongbook/install.bat（自动下载便携 Python，无需管理员；仅 Windows）。
· 没装 git → 别克隆了，直接给 install.py 加 --from-zip 参数（自动下载 zip 解压安装）。`

export async function copyInstallPrompt() {
  await navigator.clipboard.writeText(AI_PROMPT)
}
