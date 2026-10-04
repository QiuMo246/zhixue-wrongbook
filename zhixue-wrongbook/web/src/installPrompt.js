// 发给 AI 助手的安装提示词 —— 首屏的「复制安装提示词」按钮和
// 安装区的懒人安装法共用这一份，改文案只改这里。
//
// 2026-09-27 改版（优化.md 安装链路）：
//   1. 密码不再走命令行参数 —— --password 会留进命令行历史、暴露在
//      进程列表里，还会先出本机到模型供应商。改为引导 AI 带用户跑
//      tools/setup_account.py 的隐藏输入（getpass）路径。
//   2. 路径与实际仓库布局对齐：安装入口在仓库根的 install.py
//      （它会自动定位真正的项目）。
export const AI_PROMPT = `帮我安装智学网错题助手：从 Gitee 克隆 https://gitee.com/qiu_moRs/zhixue-wrongbook 到本地（GitHub 地址 https://github.com/QiuMo246/zhixue-wrongbook 作为后备），运行仓库里的 install.py --config（它会自动定位真正的项目目录）。装好后重启 MCP 连接。

然后录入智学网账号密码：这一步**由我在我自己的终端完成**——你的命令通道是非交互的，直接跑交互式脚本会卡住或读不到我的键盘输入，所以**不要**自己运行它。你要做的：把一条我能直接粘贴运行的完整命令发给我（用安装时那个 Python 解释器，比如仓库 .venv 里的；我电脑可能没装 Python），内容是运行 zhixue-wrongbook/tools/setup_account.py。我在自己的终端里输入账号和密码（输入时不回显，也不会留在命令行历史里 —— 所以**不要**让我把密码发在对话里或写在命令行参数里）。等我说「录好了」再继续。之后我对你说「帮我同步错题」就应该能用了。遇到报错就自己排查修好，卡住了再问我。

补充（按你的实际情况二选一，AI 看得懂）：
· 我的电脑没装 Python → 用你自己（AI）自带的 Python 执行；你也没有的话，Windows 上直接跑仓库里的 zhixue-wrongbook/install.bat（自动下载便携 Python，无需管理员；仅 Windows）。
· 没装 git → 别克隆了，直接给 install.py 加 --from-zip 参数（自动下载 zip 解压安装）。`

export async function copyInstallPrompt() {
  await navigator.clipboard.writeText(AI_PROMPT)
}
