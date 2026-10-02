"""图片元数据剥离（移植自 qwen 分支 privacy/strip.ts 的设计）。

为什么要它：错题图片（原卷扫描、手写作答）从智学网下载落盘后，会被
`get_questions` 以本地绝对路径交给宿主模型读图 —— 图片一旦出网，里面
夹带的 EXIF/GPS（拍摄设备、精确经纬度、时间）就跟着走了。redact.py 管
文本出境，这一层管**图片出境**：落盘前先把元数据段真实剥掉。

设计取舍（与 qwen strip.ts 一致，都是「诚实优于干净」）：
  * JPEG / PNG 走**真实的分段 / 分块重建**，只丢掉 EXIF/XMP/Photoshop/
    注释段，其余原样保留 —— 不重新编码，像素一个字节都不动，没有画质损失。
  * 重建走不通（块长越界、截断、缺 IEND）就**不产出副本**、原样返回：
    一个坏掉的图片文件比一份留着元数据的原图更糟。此时 support=malformed，
    调用方如实记录「没剥掉」，绝不谎称 stripped。
  * PDF 只**检测不改写**：没有可靠的增量写入器就去改 PDF，产出的坏文件
    比原文件的元数据更糟。检测到 /Author 等字段就如实报 detected_not_stripped。
  * `removed` 只记真正丢掉的分段：JFIF/ICC 这类保留段写进去就是谎报。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# support 取值：
#   stripped               真的剥掉了元数据段，out 是干净副本
#   clean                  本来就没有可剥的元数据段（out == 原字节）
#   detected_not_stripped  PDF：检测到元数据字段，但不改写（无可靠写入器）
#   unknown_format         不是 jpeg/png/pdf（webp/gif 等）：原样返回
#   malformed              结构走不通（越界/截断/缺 IEND）：不产副本，原样返回
JPEG = "jpeg"
PNG = "png"
PDF = "pdf"
UNKNOWN = "unknown"

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_PDF_SIG = b"%PDF"
# JPEG 里判定为「可丢」的段：APP1(Exif/XMP) / APP13(Photoshop) / COM(注释)。
_PDF_KEYS = ("/Author", "/Creator", "/Producer", "/Title", "/Subject", "/Keywords")


@dataclass
class StripResult:
    support: str
    format: str
    removed: list[str] = field(default_factory=list)
    # 调用方应落盘的字节：malformed/unknown/pdf 时等于原字节（不产副本），
    # jpeg/png 重建成功时是剥掉元数据段后的副本。
    out: bytes = b""
    original_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "support": self.support,
            "format": self.format,
            "removed": list(self.removed),
            "original_bytes": self.original_bytes,
            "out_bytes": len(self.out),
        }


def _ascii(data: bytes, start: int, length: int) -> str:
    """把 [start, start+length) 的字节按 latin1 解成字符串（越界自动截断）。"""
    return data[start:start + length].decode("latin1", "replace")


def sniff_format(data: bytes) -> str:
    if len(data) > 2 and data[0] == 0xFF and data[1] == 0xD8:
        return JPEG
    if len(data) > 8 and data[1:4] == b"PNG":
        return PNG
    if len(data) > 4 and data[0:4] == _PDF_SIG:
        return PDF
    return UNKNOWN


def _strip_jpeg(data: bytes) -> tuple[bytes, list[str], bool]:
    """返回 (重建后的字节, 丢掉的段名, 是否完整走到 SOS)。"""
    removed: list[str] = []
    out = bytearray(data[0:2])  # SOI
    i = 2
    ok = False
    n = len(data)
    while i + 1 < n:
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        # 独立标记：SOI(0xD8) / TEM(0x01) 无长度字段
        if marker in (0xD8, 0x01):
            i += 2
            continue
        # RSTn(0xD0..0xD7) 重启标记，无长度字段
        if 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xDA:
            # SOS：扫描数据从这里到 EOI，原样保留（含末尾 EOI）
            out += data[i:]
            ok = True
            break
        seg_len = (data[i + 2] << 8) | data[i + 3]
        if seg_len < 2 or i + 2 + seg_len > n:
            break  # 段长越界/截断：走不通
        seg = data[i:i + 2 + seg_len]
        tag = _ascii(seg, 4, min(4, len(seg) - 4))
        head = _ascii(seg, 0, min(len(seg), 32))
        is_exif = marker == 0xE1 and (tag == "Exif" or "http:" in head)
        is_xmp = marker == 0xE1 and "http" in head
        is_photoshop = marker == 0xED
        is_comment = marker == 0xFE
        keep = not (is_exif or is_xmp or is_photoshop or is_comment)
        if is_exif or is_xmp:
            removed.append("APP1(exif/xmp)")
        elif is_photoshop:
            removed.append("APP13(photoshop)")
        elif is_comment:
            removed.append("COM")
        if keep:
            out += seg
        i += len(seg)
    return bytes(out), removed, ok


def _strip_png(data: bytes) -> tuple[bytes, list[str], bool]:
    """返回 (重建后的字节, 丢掉的块类型, 是否完整走到 IEND)。"""
    removed: list[str] = []
    out = bytearray(data[0:8])  # PNG 签名
    i = 8
    n = len(data)
    while i + 12 <= n:
        # 块长是 uint32 大端；Python 的 int 从字节构造天然无符号，不会像
        # JS 的位运算那样溢出成负数把循环卡死。
        length = int.from_bytes(data[i:i + 4], "big")
        ctype = _ascii(data, i + 4, 4)
        end = i + 12 + length  # 4 长 + 4 类型 + length 数据 + 4 CRC
        if not (ctype.isalpha() and len(ctype) == 4 and ctype.isascii()) or end > n:
            return b"", [], False  # 块类型非法或越界：走不通
        if ctype in ("tEXt", "iTXt", "zTXt"):
            removed.append(ctype)
        else:
            out += data[i:end]
        i = end
        if ctype == "IEND":
            return bytes(out), removed, True
    return b"", [], False


def _detect_pdf(data: bytes) -> list[str]:
    text = data[:min(len(data), 200_000)].decode("latin1", "replace")
    return [k[1:] for k in _PDF_KEYS if k in text]


def strip_bytes(data: bytes) -> StripResult:
    """剥离图片字节里的元数据段，返回可落盘的结果。

    调用方**总是**落盘 `result.out`：
      * jpeg/png 重建成功 → out 是剥掉元数据段的干净副本；
      * malformed / unknown / pdf → out 等于原字节（不产副本，诚实保留原样）。
    """
    fmt = sniff_format(data)
    original = len(data)

    if fmt in (JPEG, PNG):
        rebuilt, removed, ok = (_strip_jpeg(data) if fmt == JPEG
                                else _strip_png(data))
        if not ok:
            # 重建走不通就不产副本：坏文件比留着元数据的原图更糟。
            return StripResult("malformed", fmt, [], data, original)
        support = "stripped" if removed else "clean"
        return StripResult(support, fmt, removed, rebuilt, original)

    if fmt == PDF:
        found = _detect_pdf(data)
        support = "detected_not_stripped" if found else "clean"
        return StripResult(support, PDF, found, data, original)

    # webp/gif/未知格式：不认得就不动它，如实标 unknown_format。
    return StripResult("unknown_format", UNKNOWN, [], data, original)
