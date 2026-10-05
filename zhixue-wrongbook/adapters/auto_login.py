"""账密登录 + 自动重登（2026-09-25 按项目主人决策新增）。

主人决策（覆盖 README 旧隐私约束「不存账号密码」）：允许把智学网账号密码
存在**本机**，目标「用户全程只需登录一次」—— Cookie 失效时用存下的账密
自动重登，不再让用户碰 F12 / 复制 Cookie。

原理（2026-09-25 对 login_v1.html + login_v1.js + rc4.js 实读逆向；
  2026-10-05 按测试反馈 P0-1 补齐 SSO 字段）：
  真登录页是 https://www.zhixue.com/login_v1.html，提交走
    POST /edition/login?from=web_login
    loginName=<账号>
    password=hex( RC4(明文密码, "iflytzhixueweb") )     ← zxlogin_secret，rc4.js
    description=encrypt
    appId=zx-container-client & deviceName=web & client=web & deviceId=<uuid>
      （官方前端必带；不带时**风控账号**服务端只回模糊的「账号或密码错误」）
  同域直接种会话 Cookie，无 CAS、无极验（验证码仅在风控触发时追加参数）。
  顺带修掉一个库的过时假设：zhixuewang 的 playwright 流程填的
  #txtUserName/#signup_button 在现在的 wap_login.html 上根本不存在。

适用范围（2026-10-05 如实限定，测试反馈 P0-1）：
  「全程只需登录一次 + 失效自动重登」只对**未被风控的账号**成立。
  被风控的账号必须人工过验证码，账密登录拿不到会话 —— 这类账号
  走通道 C-2（zx_browser_start，用户在专用浏览器里手动登录一次）
  或复制 Cookie（zx_session_set）。本模块**不尝试绕过验证码**，
  命中风控时以 error_code=captcha_required 明确告知。

密码存储：与 Cookie 同级保护 —— keyring（系统凭据管理器）首选，
降级加密文件（Windows DPAPI / 其它平台 AES-256-GCM，见 adapters/session.py）。
**绝不落明文。**
"""

from __future__ import annotations

import base64
import os
import re
import uuid
from pathlib import Path

import requests

from adapters import session as session_store
from core.errors import (CODE_AUTO_LOGIN_FAILED, CODE_CAPTCHA_REQUIRED,
                         ZxError)
from core.pycmd import run_tool

ROOT = Path(__file__).resolve().parent.parent

_LOGIN_PAGE = "https://www.zhixue.com/login_v1.html"
_LOGIN_URL = "https://www.zhixue.com/edition/login"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
_RC4_KEY = "iflytzhixueweb"          # rc4.js: var zxlogin_secret

# 官方前端提交时额外携带的 SSO 字段（2026-10-05 修，测试反馈 P0-1）。
# 真实环境实测：只发 loginName/password/description 三个字段时，
# **风控账号**服务端回的是模糊的「账号或密码错误」——补上这四个字段后
# 同一账号返回「验证码错误」，才暴露出真实原因。缺字段不仅少信息，
# 还会把用户误导去改密码。
_SSO_APP_ID = "zx-container-client"

_PWD_SERVICE = os.environ.get("ZX_CRED_SERVICE", "zhixue-wrongbook")
_ACC_KEY = os.environ.get("ZX_CRED_ACCOUNT_KEY", "zx_account")
_PWD_KEY = os.environ.get("ZX_CRED_PASSWORD_KEY", "zx_password")
_PWD_FILE = Path(os.environ.get(
    "ZX_CRED_PASSWORD_FILE", str(ROOT / "data" / ".password.bin")))


class AutoLoginError(ZxError):
    """账密登录失败（含服务端拒绝原因）。

    包四（2026-09-26）：改为继承 ZxError，`_guard` 会自动带出
    error_code=auto_login_failed 与协商字段；8 个既有 raise 点
    只传 message，不破坏调用形状。

    2026-10-05（测试反馈 P0-1）：风控验证码单独归类成
    error_code=captcha_required —— 它不是「密码错」，默认话术
    「重新录入账号密码」对它毫无意义。
    """

    def __init__(self, message: str, *, code: str = CODE_AUTO_LOGIN_FAILED,
                 missing: list[str] | None = None,
                 suggested_action: list[str] | None = None):
        super().__init__(
            message, code=code, missing=missing,
            suggested_action=suggested_action or [
                f"跑 {run_tool('tools/setup_account.py')} 重新录入一次账号密码（密码改过时）",
                "或改用 zx_session_set 直接粘贴 Cookie（不走账密）",
                "或改走合规通道 A：zx_import_export_file 解析官方导出文件",
            ])


# 风控/验证码类服务端话术（2026-10-05，测试反馈 P0-1）。
# 命中任意一条 = 这个账号被智学网风控，账密登录这条路走不通，
# 必须走浏览器（通道 C-2）或手工粘贴 Cookie。
_CAPTCHA_MARKERS = ("验证码", "needValidName", "riskPassword", "riskAccount",
                    "captcha")


def is_captcha_blocked(message: str) -> bool:
    """服务端拒绝原因是不是「风控要求验证码」。

    注意「账号或密码错误」里不含上述标记，所以不会被误判 —— 但反过来，
    实测证明**风控账号在缺 SSO 字段时也会回「账号或密码错误」**，
    所以这句话不能当成「密码真的错了」的证据（见 login_with_password）。
    """
    msg = (message or "").strip()
    if not msg:
        return False
    if msg in ("needValidName", "riskPassword", "riskAccount"):
        return True
    return any(k in msg for k in _CAPTCHA_MARKERS)


def _captcha_error(server_msg: str) -> AutoLoginError:
    return AutoLoginError(
        f"登录被拒：{server_msg} —— 这个账号被智学网**风控**，"
        "登录必须通过验证码，程序化账密登录做不到（本项目刻意不绕过风控）。"
        "这不是密码错误，不要去改密码。",
        code=CODE_CAPTCHA_REQUIRED,
        missing=["一次人工完成的验证码登录"],
        suggested_action=[
            "走通道 C-2：调 zx_browser_start 弹出专用 Chrome，"
            "让用户在里面手动登录一次（验证码由人来做），之后 zx_sync_browser 采集",
            "或走复制 Cookie 备选流程：用户在普通浏览器登录后，"
            "把 Cookie 交给 zx_session_set（tools/scan_login.py --from-clipboard）",
            "或用合规通道 A：zx_import_export_file 解析官方导出文件",
        ])


# ---------------------------------------------------------------------------
# RC4（rc4.js 的 Python 复刻）+ 十六进制编码（toHexString）
# ---------------------------------------------------------------------------
def rc4_hex(text: str, key: str = _RC4_KEY) -> str:
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + ord(key[i % len(key)])) % 256
        S[i], S[j] = S[j], S[i]
    i = j = 0
    out = []
    for ch in text:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        # 2026-09-27 修（优化.md #27，属实性核查推翻过一轮的「复刻正确」）：
        # 与 static.zhixue.com 的 rc4.js 原文逐句比对，密钥流是**单重索引**
        #   a = (S[i] + (S[j] % 256)) % 256 ; 输出 ^= S[a]
        # 这里此前多套了一层 S[...]（先 k=S[a] 再 ^=S[k]），与真实前端
        # 逐字节不同 —— 服务端按 rc4.js 解密时账密登录从写下的第一天起
        # 就不可能成功。同一明文/密钥两种逻辑实测输出不同。
        a = (S[i] + (S[j] % 256)) % 256
        out.append(chr(ord(ch) ^ S[a]))
    return "".join(f"{ord(c):02x}" for c in out)


# ---------------------------------------------------------------------------
# 账密存取（keyring 首选，DPAPI 降级；与 Cookie 同级保护，不落明文）
# ---------------------------------------------------------------------------
def save_credentials(account: str, password: str) -> dict:
    account, password = account.strip(), password
    if not account or not password:
        raise ValueError("账号和密码都不能为空")
    try:
        import keyring
        keyring.set_password(_PWD_SERVICE, _ACC_KEY, account)
        keyring.set_password(_PWD_SERVICE, _PWD_KEY, password)
        return {"backend": "keyring(系统凭据管理器)"}
    except Exception:
        pass
    try:
        # 与 Cookie 同一套三级后端（keyring → DPAPI → AES-GCM 文件）；
        # 2026-10-05 前这里只认 DPAPI，Linux 上存密码必失败。
        if not session_store._encfile_available():   # noqa: SLF001
            raise RuntimeError("本平台没有可用的加密文件后端")
        backend = session_store.encrypt_to_file(
            {"account": account, "password": password}, _PWD_FILE)
        return {"backend": backend, "path": str(_PWD_FILE)}
    except Exception as exc:
        raise AutoLoginError(
            f"凭据保存失败（keyring 和加密文件后端都不可用）：{exc}") from exc


def load_credentials() -> tuple[str, str] | None:
    try:
        import keyring
        account = keyring.get_password(_PWD_SERVICE, _ACC_KEY)
        password = keyring.get_password(_PWD_SERVICE, _PWD_KEY)
        if account and password:
            return account, password
    except Exception:
        pass
    d = session_store.decrypt_from_file(_PWD_FILE)
    if d and d.get("account") and d.get("password"):
        return d["account"], d["password"]
    return None


def delete_credentials() -> dict:
    removed = []
    try:
        import keyring
        for k in (_ACC_KEY, _PWD_KEY):
            keyring.delete_password(_PWD_SERVICE, k)
            removed.append("keyring")
    except Exception:
        pass
    if _PWD_FILE.exists():
        _PWD_FILE.unlink()
        removed.append("file")
    return {"removed": removed}


# ---------------------------------------------------------------------------
# 登录链
# ---------------------------------------------------------------------------
def _cookie_from_session(s: requests.Session, account: str) -> str:
    """requests.Session 的 Cookie → 项目通用 cookie 字符串。

    通道 B 的库要求 loginUserName（浏览器 Cookie 里有，程序登录链可能
    没种上）—— 缺了就按库自己的方式补：base64(账号)。
    """
    cookie = "; ".join(f"{k}={v}" for k, v in s.cookies.items())
    if "loginUserName" not in cookie:
        uname = base64.b64encode(account.encode()).decode()
        cookie = (cookie + "; " if cookie else "") + f"loginUserName={uname}"
    return cookie


def _sso_fields() -> dict:
    """官方前端提交登录时携带的 SSO 字段（见 _SSO_APP_ID 上方说明）。

    deviceId 官方是每次登录新生成的 uuid，这里同样用一次性 uuid4 ——
    不需要持久化（持久化反而多一个本机标识）。
    """
    return {"appId": _SSO_APP_ID, "deviceName": "web", "client": "web",
            "deviceId": uuid.uuid4().hex}


def login_payload(account: str, password: str) -> dict:
    """构造登录请求体（纯函数，测试直接断言字段形状）。"""
    return {"loginName": account, "password": rc4_hex(password),
            "description": "encrypt", **_sso_fields()}


def login_with_password(account: str, password: str,
                        timeout: int = 25) -> str:
    """账密登录 → 返回可直接喂给通道 B 的 Cookie 字符串。

    失败抛 AutoLoginError，message 带服务端拒绝原因，并按原因分流
    error_code（2026-10-05 修，测试反馈 P0-1）：
      - captcha_required    —— 风控要验证码，账密这条路到此为止，
                               话术明确引导走 zx_browser_start / zx_session_set；
      - auto_login_failed   —— 其余拒绝（含「账号或密码错误」）。
        ⚠ 「账号或密码错误」**不能当作密码错的结论**：实测风控账号在
        缺 SSO 字段时同样回这句。补字段之后，风控账号会改回
        「验证码错误」，这句话才比较接近字面意思 —— 但仍不排除风控。
    """
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Referer": _LOGIN_PAGE})
    try:
        s.get(_LOGIN_PAGE, timeout=timeout)
    except Exception as exc:
        raise AutoLoginError(f"连不上智学网：{exc}") from exc

    try:
        r = s.post(
            _LOGIN_URL, params={"from": "web_login"},
            data=login_payload(account, password),
            timeout=timeout)
    except Exception as exc:
        raise AutoLoginError(f"登录请求失败：{exc}") from exc

    try:
        res = r.json()
    except Exception:
        raise AutoLoginError(
            f"登录响应不是 JSON（接口可能变更）：{r.text[:200]}")

    if res.get("result") != "success":
        msg = res.get("message") or str(res)[:200]
        if is_captcha_blocked(msg):
            raise _captcha_error(msg)
        raise AutoLoginError(f"登录被拒：{msg}")

    # 登录成功 → 验证会话真的种上了
    probe = s.get("https://www.zhixue.com/container/getCurrentUser",
                  timeout=timeout).json()
    role = (probe.get("result") or {}).get("role")
    if not role:
        raise AutoLoginError(
            "登录成功但 getCurrentUser 不认（可能接口变更），"
            f"响应：{str(probe)[:200]}")
    return _cookie_from_session(s, account)


# ---------------------------------------------------------------------------
# 自动重登
# ---------------------------------------------------------------------------
def ensure_session() -> tuple[str, bool]:
    """返回 (cookie, relogged)。

    Cookie 有效 → 原样返回；失效且有存档账密 → 自动重登并更新 Cookie；
    没有存档账密 → 抛 AutoLoginError，message 告诉用户跑一次 setup。

    2026-09-27 修（优化.md #9）：session_check 返回 unreachable（网络不通）
    时不再往下走账密重登 —— 「连不上智学网」≠「会话失效」，把还能用的
    Cookie 当废的、甚至用账密重登，都会把「网络问题」误报成「账号问题」。
    unreachable 时把 Cookie 原样交回，让调用方的真实请求去暴露网络问题。
    """
    cookie = session_store.get_cookie()
    if cookie:
        from adapters import zhixue_web
        status = zhixue_web.session_check(cookie).get("status")
        if status == "valid":
            return cookie, False
        if status == "unreachable":
            return cookie, False

    cred = load_credentials()
    if not cred:
        raise AutoLoginError(
            "会话失效，且本机没有存档的账号密码，无法自动重登。"
            f"运行 {run_tool('tools/setup_account.py')} 录入一次即可，"
            "之后再也不用手动登录。（风控账号过不了账密登录，"
            "请改走 zx_browser_start 或 zx_session_set。）")
    account, password = cred
    cookie = login_with_password(account, password)
    session_store.set_cookie(cookie)
    return cookie, True
