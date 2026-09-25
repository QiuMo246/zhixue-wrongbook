"""会话管理：Cookie 的存取。**不落明文文件。**

主路径：keyring → Windows 凭据管理器（macOS Keychain / Linux Secret Service）。
降级路径：Windows DPAPI 加密后写 `data/.session.bin`（只有当前 Windows 用户
能解密，换用户或换机器都解不开）；其他平台没有 DPAPI，就明确报错，
不偷偷写明文。

设计文档第 4 节 / 第 9 节的硬约束：
  - 不存账号密码（本模块根本没有密码这个参数）
  - Cookie 存系统钥匙串，不落明文文件
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

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
# ---------------------------------------------------------------------------
class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_available() -> bool:
    return sys.platform == "win32"


def _dpapi_encrypt(plaintext: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in = _DataBlob(len(plaintext), ctypes.cast(
        ctypes.create_string_buffer(plaintext, len(plaintext)),
        ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(blob_in), "zhixue-wrongbook session", None, None, None,
        0x01, ctypes.byref(blob_out))  # CRYPTPROTECT_UI_FORBIDDEN
    if not ok:
        raise OSError("CryptProtectData 失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _dpapi_decrypt(ciphertext: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in = _DataBlob(len(ciphertext), ctypes.cast(
        ctypes.create_string_buffer(ciphertext, len(ciphertext)),
        ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0x01,
        ctypes.byref(blob_out))
    if not ok:
        raise OSError("CryptUnprotectData 失败（可能不是本机当前用户加密的）")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _file_set(value: str) -> None:
    payload = json.dumps({"cookie": value, "saved_at": datetime.now(timezone.utc).isoformat()},
                         ensure_ascii=False).encode("utf-8")
    blob = _dpapi_encrypt(payload)
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
        return json.loads(_dpapi_decrypt(blob).decode("utf-8")).get("cookie")
    except Exception:
        return None


def _file_delete() -> None:
    if FALLBACK_PATH.exists():
        FALLBACK_PATH.unlink()


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
def backend_name() -> str:
    if _keyring_available():
        return "keyring(系统凭据管理器)"
    if _dpapi_available():
        return "dpapi(Windows 用户级加密文件)"
    return "none"


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
    if _dpapi_available():
        _file_set(cookie)
        return {"ok": True, "backend": backend_name(), "length": len(cookie),
                "note": "keyring 不可用，已降级为 DPAPI 加密文件；" + "；".join(errors)}
    raise RuntimeError(
        "没有可用的安全存储后端（keyring 不可用，且本平台无 DPAPI）。"
        "为避免把 Cookie 写成明文，这里选择直接失败。"
        "请先安装 keyring 并配置好系统凭据后端。")


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
        removed.append("dpapi-file")
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
