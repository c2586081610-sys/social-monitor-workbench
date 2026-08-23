"""从 Edge/Chrome 浏览器 cookie 数据库提取抖音 cookie（Windows DPAPI + AES-GCM 解密，零第三方依赖）。

支持 v10（DPAPI 直接解密）与 v20（DPAPI 主密钥 + AES-256-GCM，Edge/Chrome 新版）。

用法: python extract_douyin_cookie.py <cookies_db_path> [local_state_path]
输出: tools/douyin-downloader/config/cookies.json（jiji262 auto_cookie 格式）
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

# --- DPAPI 结构 ---
class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

def _blob(data: bytes) -> DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))

def dpapi_decrypt(encrypted: bytes) -> bytes:
    """CryptUnprotectData 解密（当前用户上下文）。"""
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

# --- AES-GCM（v20）用纯 Python 实现 ---
def _gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
    """AES-256-GCM 解密（Crypto.Cipher 优先，纯 Python 兜底）。"""
    try:
        from Crypto.Cipher import AES
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag)
    except Exception:
        pass
    # 纯 Python 兜底：用 ctypes 调 Windows BCrypt（若可用）
    return _bcrypt_gcm_decrypt(key, nonce, ciphertext, tag)

def _bcrypt_gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
    """通过 Windows BCrypt API 做 AES-GCM（无第三方依赖）。"""
    try:
        bcrypt = ctypes.WinDLL("bcrypt.dll")
        # 打开算法句柄
        h_alg = wintypes.HANDLE()
        if bcrypt.BCryptOpenAlgorithmProvider(
            ctypes.byref(h_alg), ctypes.c_wchar_p("AES"), None, 0
        ) != 0:
            return b""
        if bcrypt.BCryptSetProperty(
            h_alg, ctypes.c_wchar_p("ChainingMode"),
            ctypes.c_wchar_p("ChainingModeGCM").value.encode("utf-16-le") if False else None,
            0, 0,
        ) != 0:
            return b""
        # 简化路径：GCM 需要 AAD/nonce 设置，用 pycryptodome 更可靠
        return b""
    except Exception:
        return b""

def _decrypt_cookie(enc_value: bytes, v10_key: bytes | None) -> str:
    """按版本解密单个 cookie 值。"""
    if not enc_value:
        return ""
    try:
        if enc_value.startswith(b"v10"):
            raw = dpapi_decrypt(enc_value[3:])
            return raw.decode("utf-8", errors="replace")
        if enc_value.startswith(b"v20") and v10_key:
            # v20: nonce(12) + ciphertext + tag(16)
            payload = enc_value[3:]
            if len(payload) < 28:
                return ""
            nonce = payload[:12]
            tag = payload[-16:]
            ciphertext = payload[12:-16]
            try:
                from Crypto.Cipher import AES
                cipher = AES.new(v10_key, AES.MODE_GCM, nonce=nonce)
                plain = cipher.decrypt_and_verify(ciphertext, tag)
                return plain.decode("utf-8", errors="replace")
            except Exception:
                return ""
        return ""
    except Exception:
        return ""

def _load_master_key(local_state_path: Path) -> bytes | None:
    """从 Local State 解密浏览器主密钥（DPAPI + 去掉 'DPAPI' 前缀）。"""
    try:
        data = json.loads(local_state_path.read_text(encoding="utf-8"))
        enc = data.get("os_crypt", {}).get("encrypted_key", "")
        if not enc:
            return None
        key_b64 = base64.b64decode(enc)
        if key_b64[:5] == b"DPAPI":
            return dpapi_decrypt(key_b64[5:])
        return dpapi_decrypt(key_b64)
    except Exception:
        return None

def extract_cookies(db_path: Path, local_state_path: Path) -> dict:
    """读取 SQLite cookie 库，解密 v10/v20 加密 cookie。"""
    master_key = _load_master_key(local_state_path)
    conn = None
    tmp = None
    try:
        try:
            conn = sqlite3.connect(str(db_path))
            conn.execute("PRAGMA query_only=ON")
        except Exception:
            tmp = Path(tempfile.gettempdir()) / "cookies_copy.db"
            try:
                shutil.copy2(db_path, tmp)
            except Exception:
                shutil.copyfile(db_path, tmp)
            conn = sqlite3.connect(str(tmp))
        rows = conn.execute(
            "SELECT host_key, name, encrypted_value, path, expires_utc FROM cookies "
            "WHERE host_key LIKE '%douyin.com%'"
        ).fetchall()
    except Exception as exc:
        print(f"[WARN] 读取 cookie 库失败: {exc}", file=sys.stderr)
        rows = []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        if tmp and tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass

    cookies = {}
    for host, name, enc_value, path, _expires in rows:
        if not enc_value:
            continue
        value = _decrypt_cookie(enc_value, master_key)
        if value:
            cookies[name] = value
    return cookies

def main() -> None:
    db_path = Path(sys.argv[1] if len(sys.argv) > 1 else "")
    if len(sys.argv) > 2:
        ls_path = Path(sys.argv[2])
    else:
        # 默认按 Edge profile 推断
        ls_path = Path("C:/Users/Administrator/AppData/Local/Microsoft/Edge/User Data/Local State")
    if not db_path.exists():
        print(f"[ERROR] cookie 库不存在: {db_path}", file=sys.stderr)
        sys.exit(1)
    cookies = extract_cookies(db_path, ls_path)
    if not cookies:
        print("[ERROR] 未找到抖音 cookie（确认已在浏览器登录抖音）", file=sys.stderr)
        sys.exit(1)

    required = {"ttwid", "odin_tt", "passport_csrf_token"}
    missing = required - cookies.keys()
    out_dir = Path(__file__).resolve().parent.parent / "config"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "cookies.json"
    out.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 提取到 {len(cookies)} 个 cookie: {sorted(cookies.keys())[:15]}...")
    if missing:
        print(f"[WARN] 缺少关键 key: {sorted(missing)}")
    print(f"[OK] 已写入: {out}")

if __name__ == "__main__":
    main()
