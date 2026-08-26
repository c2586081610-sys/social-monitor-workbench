"""从 Edge/Chrome 浏览器 cookie 数据库提取小红书网页版 cookie（复用抖音提取脚本的 DPAPI+AES-GCM 解密）。

用法: python extract_xhs_cookie.py
扫描: Edge Default + Chrome 全部 Profile，取第一个含小红书登录态的
输出: config/platform_cookies.json -> xhs.cookie（Cookie 串，XHS-Downloader --cookie 格式）
前置: 先在浏览器登录 xiaohongshu.com 网页版
"""
import base64
import ctypes
import json
import shutil
import sqlite3
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))


def dpapi_decrypt(encrypted: bytes) -> bytes:
    if not encrypted:
        return b""
    try:
        in_blob = _blob(encrypted)
        out_blob = DATA_BLOB()
        if ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        ):
            data = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return data
    except Exception:
        pass
    return b""


def _decrypt_cookie(enc_value: bytes, master_key: bytes | None) -> str:
    if not enc_value:
        return ""
    try:
        if enc_value.startswith(b"v10"):
            return dpapi_decrypt(enc_value[3:]).decode("utf-8", errors="replace")
        if enc_value.startswith(b"v20") and master_key:
            payload = enc_value[3:]
            if len(payload) < 28:
                return ""
            nonce, tag, ciphertext = payload[:12], payload[-16:], payload[12:-16]
            from Crypto.Cipher import AES
            plain = AES.new(master_key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(ciphertext, tag)
            return plain.decode("utf-8", errors="replace")
    except Exception:
        return ""
    return ""


def _load_master_key(local_state_path: Path) -> bytes | None:
    try:
        data = json.loads(local_state_path.read_text(encoding="utf-8"))
        enc = data.get("os_crypt", {}).get("encrypted_key", "")
        key_b64 = base64.b64decode(enc)
        if key_b64[:5] == b"DPAPI":
            return dpapi_decrypt(key_b64[5:])
        return dpapi_decrypt(key_b64)
    except Exception:
        return None


def extract_cookies(db_path: Path, local_state_path: Path, host_filter: str) -> dict:
    master_key = _load_master_key(local_state_path)
    tmp = None
    try:
        try:
            conn = sqlite3.connect(str(db_path))
            conn.execute("PRAGMA query_only=ON")
        except Exception:
            tmp = Path(tempfile.gettempdir()) / "xhs_cookies_copy.db"
            try:
                shutil.copyfile(db_path, tmp)
                conn = sqlite3.connect(str(tmp))
            except Exception as e2:
                print(f"[WARN] 复制 cookie 库失败: {e2}", file=sys.stderr)
                return {}
        rows = conn.execute(
            "SELECT host_key, name, encrypted_value, path, expires_utc FROM cookies "
            "WHERE host_key LIKE ? AND name NOT LIKE '%_1P_JAR%'",
            (host_filter,),
        ).fetchall()
        conn.close()
    except Exception as exc:
        print(f"[WARN] 读取 {db_path} 失败: {exc}", file=sys.stderr)
        return {}
    finally:
        if tmp and tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass

    cookies = {}
    for host, name, enc_value, _path, _exp in rows:
        if not enc_value:
            continue
        value = _decrypt_cookie(enc_value, master_key)
        if value:
            cookies[f"{host}|{name}"] = value  # 保留 host 去重
    return cookies


def to_cookie_string(cookies: dict) -> str:
    seen = {}
    for hostname, value in cookies.items():
        _host, name = hostname.split("|", 1)
        seen[name] = value  # 后写覆盖，host 更具体的优先（遍历顺序保证）
    return "; ".join(f"{k}={v}" for k, v in seen.items() if v)


BROWSERS = [
    ("Edge", "C:/Users/Administrator/AppData/Local/Microsoft/Edge/User Data"),
    ("Chrome", "C:/Users/Administrator/AppData/Local/Google/Chrome/User Data"),
]

KEY_HINTS = ("web_session", "a1", "webId", "xsecappid", "customerClientId", "abRequestId")


def main() -> None:
    best = {}
    best_label = ""
    for name, base in BROWSERS:
        ls = Path(base) / "Local State"
        if not ls.exists():
            continue
        for prof in sorted(Path(base).glob("*/Network/Cookies")):
            db = prof
            if not db.exists():
                continue
            cookies = extract_cookies(db, ls, "%xiaohongshu.com%")
            keys = {k.split("|", 1)[1] for k in cookies}
            hit = KEY_HINTS[0] in keys  # web_session 是登录态关键
            print(f"  {name} {db.parent.parent.name}: {len(cookies)} 个 cookie, web_session={'有' if hit else '无'}")
            if hit and len(cookies) > len(best):
                best = cookies
                best_label = f"{name}/{db.parent.parent.name}"

    if not best:
        print("[ERROR] 未找到小红书登录 cookie。请先在 Edge/Chrome 登录 xiaohongshu.com 网页版后重试。", file=sys.stderr)
        sys.exit(1)

    cookie_str = to_cookie_string(best)
    print(f"[OK] 来源: {best_label}，提取 {len(best)} 个 cookie，串长 {len(cookie_str)} 字符")
    print(f"     关键 key: {sorted(k.split('|',1)[1] for k in best)[:20]}")

    # 写入 config/platform_cookies.json
    cfg_path = ROOT / "config" / "platform_cookies.json"
    cfg = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    cfg.setdefault("xhs", {})["cookie"] = cookie_str
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 已写入: {cfg_path} -> xhs.cookie")
    # 提示过期
    print("[提示] cookie 有效期不定（通常数天~数周），失效后重新运行本脚本即可")


if __name__ == "__main__":
    main()
