"""会话管理：Cookie 的存取。**不落明文文件。**

三级后端（2026-10-05 按测试反馈 P1-1 补齐）：
  1. keyring —— 系统凭据管理器（Windows 凭据管理器 / macOS Keychain /
     Linux Secret Service）。首选。
  2. Windows DPAPI 加密文件 `data/.session.bin` —— 只有当前 Windows 用户
     能解密，换用户或换机器都解不开。
  3. 跨平台 AES-256-GCM 加密文件 —— 给**没有系统凭据服务**的环境
     （Linux 容器、云沙箱、服务器上跑 MCP）。主密钥单独存一个
     chmod 600 的文件，Cookie 密文与密钥分文件存放。
     诚实声明：这一级的保护强度 = 文件权限。同一用户下的其它进程
     能读到密钥再解密，**比 DPAPI（绑 Windows 账户）弱**。只在
     keyring 和 DPAPI 都不用时才用，且只在类 Unix 平台启用
     （Windows 宁可报错，也不会把弱后端插到 DPAPI 前面）。

设计文档第 4 节 / 第 9 节的硬约束：
  - 不存账号密码（本模块根本没有密码这个参数）
  - Cookie 存系统钥匙串，不落明文文件
"""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.errors import CODE_NO_SAFE_STORAGE, ZxError
from core.pycmd import pip_install, run_tool

ROOT = Path(__file__).resolve().parent.parent

# 凭据的「命名空间」。默认就是生产值。
#
# 为什么要可覆盖（2026-09-24 踩的坑）：tools/mcp_e2e.py 把 ZX_DB_PATH 指到了
# 临时库，就以为「不会碰真实数据」了 —— 但**凭据存储是全局的**，不是库的一部分。
# 它调到 zx_session_clear 时，真的把用户存在 Windows 凭据管理器里的
# `zhixue-wrongbook / zx_cookie` 删掉了，用户被迫重新登录一次。
# 所以这里把命名空间也做成环境变量可覆盖的：测试用一次性名字，
# 物理上不可能碰到真实凭据。
SERVICE_NAME = os.environ.get("ZX_CRED_SERVICE", "zhixue-wrongbook")
KEY_NAME = os.environ.get("ZX_CRED_KEY", "zx_cookie")
FALLBACK_PATH = Path(
    os.environ.get("ZX_CRED_FILE", str(ROOT / "data" / ".session.bin")))
# 第三级后端的主密钥文件（与服务名同名，换命名空间就换一把钥匙，
# 测试环境的隔离规则和上面的 FALLBACK_PATH 一致）。
_KEY_NAME_SAFE = "".join(c if c.isalnum() else "-" for c in SERVICE_NAME)
DEFAULT_KEY_PATH = Path(os.environ.get(
    "XDG_CONFIG_HOME", str(Path.home() / ".config"))
) / f"zhixue-{_KEY_NAME_SAFE}-key" / "master.key"
KEY_PATH = Path(os.environ.get("ZX_CRED_KEY_FILE", str(DEFAULT_KEY_PATH)))


# ---------------------------------------------------------------------------
# 后端 1：系统凭据管理器（首选）
# ---------------------------------------------------------------------------
def _keyring_available() -> bool:
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring
        return not isinstance(keyring.get_keyring(), FailKeyring)
    except Exception:
        return False


def _keyring_set(value: str) -> None:
    import keyring
    keyring.set_password(SERVICE_NAME, KEY_NAME, value)


def _keyring_get() -> str | None:
    import keyring
    return keyring.get_password(SERVICE_NAME, KEY_NAME)


def _keyring_delete() -> None:
    import keyring
    try:
        keyring.delete_password(SERVICE_NAME, KEY_NAME)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 后端 2：Windows DPAPI 加密文件（降级）
#
# ctypes.wintypes 与 windll 都是 Windows 专属（2026-10-05 修，测试反馈 P1-1：
# 以前在模块顶层 `import ctypes.wintypes`、直接引用 ctypes.windll，
# Linux 上要么导入失败要么 AttributeError，本模块在非 Windows 上根本没法用）。
# 现在全部收进 win32 判断里惰性导入。
# ---------------------------------------------------------------------------
def _dpapi_available() -> bool:
    return sys.platform == "win32"


def _dpapi_blobs():
    import ctypes
    import ctypes.wintypes as wt

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    return ctypes, DataBlob


def _dpapi_encrypt(plaintext: bytes) -> bytes:
    import ctypes

    _, DataBlob = _dpapi_blobs()
    blob_in = DataBlob(len(plaintext), ctypes.cast(
        ctypes.create_string_buffer(plaintext, len(plaintext)),
        ctypes.POINTER(ctypes.c_char)))
    blob_out = DataBlob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), "zhixue-wrongbook session", None, None, None,
        0x01, ctypes.byref(blob_out))  # CRYPTPROTECT_UI_FORBIDDEN
    if not ok:
        raise OSError("CryptProtectData 失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _dpapi_decrypt(ciphertext: bytes) -> bytes:
    import ctypes

    _, DataBlob = _dpapi_blobs()
    blob_in = DataBlob(len(ciphertext), ctypes.cast(
        ctypes.create_string_buffer(ciphertext, len(ciphertext)),
        ctypes.POINTER(ctypes.c_char)))
    blob_out = DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0x01,
        ctypes.byref(blob_out))
    if not ok:
        raise OSError("CryptUnprotectData 失败（可能不是本机当前用户加密的）")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


# ---------------------------------------------------------------------------
# 后端 3：跨平台 AES-256-GCM 加密文件（无系统凭据服务的环境）
# ---------------------------------------------------------------------------
_MAGIC = b"ZXE1"          # 版本标记：换算法时能认出旧文件而不是当密文乱解


def _aes_available() -> bool:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        return True
    except Exception:
        return False


def _encfile_available() -> bool:
    """本平台的「加密文件」降级后端能不能用。

    Windows 走 DPAPI（不需要 cryptography）；其它平台需要 AES-GCM，
    且**不给 Windows 插这条路**（弱于 DPAPI，见模块 docstring）。
    """
    if _dpapi_available():
        return True
    return _aes_available()


def _master_key() -> bytes:
    """取（或首次生成）主密钥。32 字节，落在 0600 的独立文件里。"""
    if KEY_PATH.exists():
        raw = KEY_PATH.read_bytes().strip()
        try:
            key = base64.b64decode(raw)
        except Exception:
            key = b""
        if len(key) == 32:
            return key
        raise OSError(f"主密钥文件损坏（期望 32 字节 base64）：{KEY_PATH}")
    key = os.urandom(32)
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(KEY_PATH), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, base64.b64encode(key))
    finally:
        os.close(fd)
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass
    return key


def _aesgcm_encrypt(payload: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    ct = AESGCM(_master_key()).encrypt(nonce, payload, _MAGIC)
    return _MAGIC + nonce + ct


def _aesgcm_decrypt(blob: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not blob.startswith(_MAGIC):
        raise ValueError("密文格式不认识（不是本后端写的 ZXE1 文件）")
    body = blob[len(_MAGIC):]
    nonce, ct = body[:12], body[12:]
    return AESGCM(_master_key()).decrypt(nonce, ct, _MAGIC)


# ---------------------------------------------------------------------------
# 加密文件读写（按平台分发到 DPAPI / AES-GCM）
# ---------------------------------------------------------------------------
def _encrypt_payload(payload: bytes) -> bytes:
    if _dpapi_available():
        return _dpapi_encrypt(payload)
    if _aes_available():
        return _aesgcm_encrypt(payload)
    raise ZxError(
        "本平台没有可用的文件加密后端（既无 DPAPI，也没装 cryptography）。",
        code=CODE_NO_SAFE_STORAGE)


def _decrypt_blob(blob: bytes) -> bytes:
    if blob.startswith(_MAGIC):
        return _aesgcm_decrypt(blob)
    if _dpapi_available():
        return _dpapi_decrypt(blob)
    raise ValueError("密文不是本平台任何后端写的格式")


def _file_set(value: str) -> None:
    payload = json.dumps({"cookie": value,
                          "saved_at": datetime.now(timezone.utc).isoformat()},
                         ensure_ascii=False).encode("utf-8")
    blob = _encrypt_payload(payload)
    FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FALLBACK_PATH.write_bytes(base64.b64encode(blob))
    try:
        os.chmod(FALLBACK_PATH, 0o600)
    except Exception:
        pass


def _file_get() -> str | None:
    if not FALLBACK_PATH.exists():
        return None
    try:
        blob = base64.b64decode(FALLBACK_PATH.read_bytes())
        return json.loads(_decrypt_blob(blob).decode("utf-8")).get("cookie")
    except Exception:
        return None


def _file_delete() -> None:
    if FALLBACK_PATH.exists():
        FALLBACK_PATH.unlink()


# ---------------------------------------------------------------------------
# 通用加密文件（给 adapters/auto_login.py 存账密用，2026-10-05）
#
# 以前存密码只有 keyring → Windows DPAPI 两条路，Linux 上直接抛
# 「凭据保存失败」；现在和 Cookie 共用同一套三级后端，POSIX 走 AES-GCM。
# ---------------------------------------------------------------------------
def encrypt_to_file(obj: dict, path: Path) -> str:
    """把 dict 加密写到 path（0600）。返回实际用的后端名。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    backend = "dpapi(Windows 用户级加密文件)" if _dpapi_available() \
        else "encfile(AES-256-GCM，主密钥 0600)"
    blob = _encrypt_payload(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    path.write_bytes(base64.b64encode(blob))
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return backend


def decrypt_from_file(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(_decrypt_blob(
            base64.b64decode(path.read_bytes())).decode("utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
def backend_name() -> str:
    if _keyring_available():
        return "keyring(系统凭据管理器)"
    if _dpapi_available():
        return "dpapi(Windows 用户级加密文件)"
    if _aes_available():
        return "encfile(AES-256-GCM 加密文件，主密钥 0600)"
    return "none"


def _no_backend_error() -> ZxError:
    """所有后端都不用时，给出**在这台机器上真能执行**的指引。

    2026-10-05 修（测试反馈 P1-1）：原文案让「pip install keyring」，但缺的
    是系统凭据服务而不是 python 包 —— 装了包照样没有后端，学生照做无用。
    """
    hints = [
        f"{pip_install('cryptography')}（本模块自带 AES-GCM 加密文件降级后端，装完即可用）",
        "或在系统里启用钥匙串服务：Linux 桌面装 Secret Service 提供方"
        "（如 `apt install gnome-keyring` 或 KWallet）并让它随桌面会话启动，"
        "macOS 用自带 Keychain —— 之后 keyring 自动可用",
    ]
    if not _keyring_available():
        hints.append(f"{pip_install('keyring')} 只是第一步，还需要上面那个系统凭据服务")
    return ZxError(
        "没有可用的安全存储后端：keyring 没有系统凭据服务，本平台也没有 DPAPI，"
        "并且加密文件降级后端需要的 cryptography 未安装。"
        "为避免把 Cookie 写成明文，这里选择直接失败。",
        code=CODE_NO_SAFE_STORAGE,
        missing=["可用的凭据安全存储后端（keyring / Windows DPAPI / cryptography）"],
        suggested_action=hints)


def set_cookie(cookie: str) -> dict:
    cookie = (cookie or "").strip()
    if not cookie:
        raise ValueError("Cookie 为空")
    if "=" not in cookie:
        raise ValueError(
            "Cookie 格式可疑：里面没有 '='。请确认复制的是完整 Cookie 字符串"
            "（形如 token=xxx; userName=xxx; ...）")
    errors = []
    if _keyring_available():
        try:
            _keyring_set(cookie)
            _file_delete()  # 换到更安全的存储后，清掉旧降级副本
            return {"ok": True, "backend": backend_name(), "length": len(cookie)}
        except Exception as exc:
            errors.append(f"keyring 写入失败：{exc}")
    if _encfile_available():
        _file_set(cookie)
        note = (f"keyring 不可用，已降级为 {_backend_detail()}；"
                + "；".join(errors) if errors
                else f"已用 {_backend_detail()} 存储")
        if not _dpapi_available():
            note += "。（保护强度=文件权限 0600，弱于系统凭据管理器；见 session.py 顶部说明）"
        return {"ok": True, "backend": backend_name(), "length": len(cookie),
                "note": note}
    raise _no_backend_error()


def _backend_detail() -> str:
    if _dpapi_available():
        return "DPAPI 加密文件"
    return f"AES-256-GCM 加密文件（密文 {FALLBACK_PATH} / 主密钥 {KEY_PATH}）"


def get_cookie() -> str | None:
    if _keyring_available():
        try:
            v = _keyring_get()
            if v:
                return v
        except Exception:
            pass
    return _file_get()


def delete_cookie() -> dict:
    """删除已保存的 Cookie。

    只在**确实存在**时才报「已删除」——否则会出现「明明没存过，
    却告诉你删掉了」这种谎报，让人以为凭据被动过。
    """
    removed = []
    if _keyring_available():
        try:
            existed = _keyring_get() is not None
        except Exception:
            existed = False
        if existed:
            _keyring_delete()
            removed.append("keyring")
    if FALLBACK_PATH.exists():
        _file_delete()
        removed.append("file")
    return {"ok": True, "removed": removed,
            "note": "没有已保存的 Cookie" if not removed else "已清除"}


def status() -> dict:
    cookie = get_cookie()
    if not cookie:
        return {"has_cookie": False, "backend": backend_name(),
                "hint": "尚未设置 Cookie。请在浏览器登录智学网后复制 Cookie，"
                        "再调用 zx_session_set。"}
    preview = f"{cookie[:6]}…{cookie[-4:]}" if len(cookie) > 12 else "（过短）"
    return {"has_cookie": True, "backend": backend_name(),
            "length": len(cookie), "preview": preview,
            "note": "只显示首尾各几个字符，完整值不会出现在任何输出里。"}
