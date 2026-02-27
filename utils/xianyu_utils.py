"""
闲鱼平台底层工具函数

包含：Cookie 解析、签名生成、消息 ID 生成、MessagePack 解密
"""
import base64
import hashlib
import json
import random
import struct
import time
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Cookie / 设备 ID
# ---------------------------------------------------------------------------

def trans_cookies(cookies_str: str) -> Dict[str, str]:
    """将 Cookie 字符串解析为字典"""
    result = {}
    for pair in cookies_str.split("; "):
        parts = pair.split("=", 1)
        if len(parts) == 2:
            result[parts[0].strip()] = parts[1].strip()
    return result


def generate_device_id(user_id: str) -> str:
    """生成符合闲鱼要求的设备 ID（UUID v4 格式 + 用户 ID 后缀）"""
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    parts = []
    for i in range(36):
        if i in (8, 13, 18, 23):
            parts.append("-")
        elif i == 14:
            parts.append("4")
        elif i == 19:
            parts.append(chars[(int(16 * random.random()) & 0x3) | 0x8])
        else:
            parts.append(chars[int(16 * random.random())])
    return "".join(parts) + "-" + user_id


# ---------------------------------------------------------------------------
# 消息 ID 生成
# ---------------------------------------------------------------------------

def generate_mid() -> str:
    """生成消息 mid（随机数 + 时间戳）"""
    return f"{int(1000 * random.random())}{int(time.time() * 1000)} 0"


def generate_uuid() -> str:
    """生成消息 uuid"""
    return f"-{int(time.time() * 1000)}1"


# ---------------------------------------------------------------------------
# 接口签名
# ---------------------------------------------------------------------------

def generate_sign(t: str, token: str, data: str) -> str:
    """
    生成 API 请求签名（MD5）

    签名原文格式：{token}&{t}&{appKey}&{data}
    """
    app_key = "34839810"
    raw = f"{token}&{t}&{app_key}&{data}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# MessagePack 解码器
# ---------------------------------------------------------------------------

class _MsgPackDecoder:
    """纯 Python 实现的 MessagePack 解码器"""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    # ---- 基础读取 ----

    def _read(self, n: int) -> bytes:
        chunk = self._data[self._pos: self._pos + n]
        if len(chunk) < n:
            raise ValueError("数据不足，MessagePack 解析失败")
        self._pos += n
        return chunk

    def _u8(self) -> int:  return self._read(1)[0]
    def _u16(self) -> int: return struct.unpack(">H", self._read(2))[0]
    def _u32(self) -> int: return struct.unpack(">I", self._read(4))[0]
    def _u64(self) -> int: return struct.unpack(">Q", self._read(8))[0]
    def _i8(self) -> int:  return struct.unpack(">b", self._read(1))[0]
    def _i16(self) -> int: return struct.unpack(">h", self._read(2))[0]
    def _i32(self) -> int: return struct.unpack(">i", self._read(4))[0]
    def _i64(self) -> int: return struct.unpack(">q", self._read(8))[0]
    def _f32(self) -> float: return struct.unpack(">f", self._read(4))[0]
    def _f64(self) -> float: return struct.unpack(">d", self._read(8))[0]
    def _str(self, n: int) -> str: return self._read(n).decode("utf-8")

    # ---- 容器类型 ----

    def _array(self, n: int) -> List[Any]:
        return [self._value() for _ in range(n)]

    def _map(self, n: int) -> Dict[Any, Any]:
        return {self._value(): self._value() for _ in range(n)}

    # ---- 主解析入口 ----

    def _value(self) -> Any:
        b = self._u8()

        if b <= 0x7F:               return b                        # positive fixint
        if 0x80 <= b <= 0x8F:       return self._map(b & 0x0F)     # fixmap
        if 0x90 <= b <= 0x9F:       return self._array(b & 0x0F)   # fixarray
        if 0xA0 <= b <= 0xBF:       return self._str(b & 0x1F)     # fixstr
        if b == 0xC0:               return None
        if b == 0xC2:               return False
        if b == 0xC3:               return True
        if b == 0xC4:               return self._read(self._u8())   # bin 8
        if b == 0xC5:               return self._read(self._u16())  # bin 16
        if b == 0xC6:               return self._read(self._u32())  # bin 32
        if b == 0xCA:               return self._f32()
        if b == 0xCB:               return self._f64()
        if b == 0xCC:               return self._u8()
        if b == 0xCD:               return self._u16()
        if b == 0xCE:               return self._u32()
        if b == 0xCF:               return self._u64()
        if b == 0xD0:               return self._i8()
        if b == 0xD1:               return self._i16()
        if b == 0xD2:               return self._i32()
        if b == 0xD3:               return self._i64()
        if b == 0xD9:               return self._str(self._u8())
        if b == 0xDA:               return self._str(self._u16())
        if b == 0xDB:               return self._str(self._u32())
        if b == 0xDC:               return self._array(self._u16())
        if b == 0xDD:               return self._array(self._u32())
        if b == 0xDE:               return self._map(self._u16())
        if b == 0xDF:               return self._map(self._u32())
        if b >= 0xE0:               return b - 256                  # negative fixint

        raise ValueError(f"未知 MessagePack 格式字节: 0x{b:02X}")

    def decode(self) -> Any:
        try:
            return self._value()
        except Exception:
            return base64.b64encode(self._data).decode("utf-8")


# ---------------------------------------------------------------------------
# 对外解密接口
# ---------------------------------------------------------------------------

def _json_default(obj: Any) -> Any:
    """JSON 序列化兜底：bytes 转 UTF-8 或 base64"""
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except Exception:
            return base64.b64encode(obj).decode("utf-8")
    return str(obj)


def decrypt(data: str) -> str:
    """
    解密闲鱼 WebSocket 推送的加密消息

    流程：base64 解码 → MessagePack 解码 → JSON 序列化
    """
    # 清理非 base64 字符并补齐 padding
    cleaned = "".join(c for c in data if c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
    cleaned += "=" * (-len(cleaned) % 4)

    try:
        raw_bytes = base64.b64decode(cleaned)
    except Exception as e:
        return json.dumps({"error": f"Base64 解码失败: {e}", "raw": data})

    try:
        decoded = _MsgPackDecoder(raw_bytes).decode()
        return json.dumps(decoded, ensure_ascii=False, default=_json_default)
    except Exception:
        try:
            return json.dumps({"text": raw_bytes.decode("utf-8")})
        except Exception:
            return json.dumps({"hex": raw_bytes.hex()})
