"""账密登录 + 自动重登（2026-09-25 按项目主人决策新增）。

主人决策（覆盖 README 旧隐私约束「不存账号密码」）：允许把智学网账号密码
存在**本机**，目标「用户全程只需登录一次」—— Cookie 失效时用存下的账密
自动重登，不再让用户碰 F12 / 复制 Cookie。

原理（2026-09-25 对 login_v1.html + login_v1.js + rc4.js 实读逆向）：
  真登录页是 https://www.zhixue.com/login_v1.html，提交走
    POST /edition/login?from=web_login
    loginName=<账号>
    password=hex( RC4(明文密码, "iflytzhixueweb") )     ← zxlogin_secret，rc4.js
    description=encrypt
  同域直接种会话 Cookie，无 CAS、无极验（验证码仅在风控触发时追加参数）。
  顺带修掉一个库的过时假设：zhixuewang 的 playwright 流程填的
  #txtUserName/#signup_button 在现在的 wap_login.html 上根本不存在。

密码存储：与 Cookie 同级保护 —— keyring（系统凭据管理器）首选，
降级 DPAPI 加密文件（data/.password.bin）。**绝不落明文。**
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

import requests

from adapters import session as session_store

ROOT = Path(__file__).resolve().parent.parent

_LOGIN_PAGE = "https://www.zhixue.com/login_v1.html"
_LOGIN_URL = "https://www.zhixue.com/edition/login"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
_RC4_KEY = "iflytzhixueweb"          # rc4.js: var zxlogin_secret

_PWD_SERVICE = os.environ.get("ZX_CRED_SERVICE", "zhixue-wrongbook")
_ACC_KEY = os.environ.get("ZX_CRED_ACCOUNT_KEY", "zx_account")
_PWD_KEY = os.environ.get("ZX_CRED_PASSWORD_KEY", "zx_password")
_PWD_FILE = Path(os.environ.get(
    "ZX_CRED_PASSWORD_FILE", str(ROOT / "data" / ".password.bin")))


class AutoLoginError(RuntimeError):
    """账密登录失败（含服务端拒绝原因）。"""


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
        k = S[(S[i] + (S[j] % 256)) % 256]
        out.append(chr(ord(ch) ^ S[k]))
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
        from adapters.session import _dpapi_encrypt  # noqa: PLC2701
        _PWD_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PWD_FILE.write_bytes(_dpapi_encrypt(
            json.dumps({"account": account, "password": password}).encode()))
        return {"backend": "DPAPI 加密文件", "path": str(_PWD_FILE)}
    except Exception as exc:
        raise AutoLoginError(
            f"凭据保存失败（keyring 和 DPAPI 都不可用）：{exc}") from exc


def load_credentials() -> tuple[str, str] | None:
    try:
        import keyring
        account = keyring.get_password(_PWD_SERVICE, _ACC_KEY)
        password = keyring.get_password(_PWD_SERVICE, _PWD_KEY)
        if account and password:
            return account, password
    except Exception:
        pass
    if _PWD_FILE.exists():
        try:
            from adapters.session import _dpapi_decrypt  # noqa: PLC2701
            d = json.loads(_dpapi_decrypt(_PWD_FILE.read_bytes()).decode())
            return d["account"], d["password"]
        except Exception:
            return None
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


def login_with_password(account: str, password: str,
                        timeout: int = 25) -> str:
    """账密登录 → 返回可直接喂给通道 B 的 Cookie 字符串。

    失败抛 AutoLoginError，message 带服务端拒绝原因
    （「账号或密码错误」已实测可达 —— 说明加密格式与服务端校验都对上了）。
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
            data={"loginName": account, "password": rc4_hex(password),
                  "description": "encrypt"},
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
        hint = ""
        if "验证码" in msg or res.get("message") in ("needValidName",):
            hint = "（风控要求验证码 —— 等几分钟再试，或先在浏览器里正常登录一次）"
        raise AutoLoginError(f"登录被拒：{msg}{hint}")

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
    """
    cookie = session_store.get_cookie()
    if cookie:
        from adapters import zhixue_web
        if zhixue_web.session_check(cookie).get("status") == "valid":
            return cookie, False

    cred = load_credentials()
    if not cred:
        raise AutoLoginError(
            "会话失效，且本机没有存档的账号密码，无法自动重登。"
            "运行 .venv/Scripts/python tools/setup_account.py 录入一次即可，"
            "之后再也不用手动登录。")
    account, password = cred
    cookie = login_with_password(account, password)
    session_store.set_cookie(cookie)
    return cookie, True
