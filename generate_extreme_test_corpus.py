from __future__ import annotations

import argparse
import io
import json
import os
import struct
import tarfile
import time
import zipfile
from pathlib import Path


DEFAULT_FILE_COUNT = 12_500


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def sparse_file(path: Path, logical_size: int, tail: bytes = b"X") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.seek(logical_size - len(tail))
        handle.write(tail)


def zip_bytes(entries: list[tuple[str, bytes]], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression, compresslevel=9) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return buffer.getvalue()


def make_ordinary_files(root: Path, count: int) -> dict[str, int]:
    base = root / "01_普通文件与数量压力"
    samples = {
        "中文报告_2026.txt": "项目：极限测试\n状态：正常\n标签：文档、中文、UTF-8\n",
        "English Report FINAL.md": "# Extreme test\n\nMixed CASE extension and spaces.\n",
        "日本語メモ.txt": "日本語の分類テストです。\n",
        "한국어_메모.txt": "한국어 분류 테스트입니다.\n",
        "emoji_😀_🚀_文件.txt": "emoji filename test\n",
        "无扩展名": "extensionless text-like payload\n",
        ".hidden-dotfile.txt": "normally hidden by the scanner\n",
        "multiple.dots.final.v12.TXT": "uppercase extension\n",
        "archive-looking.tar.bz2": "unsupported compound archive suffix\n",
        "data.CSV": "id,name,note\n1,Alice,comma,inside\n2,Bob,\"quoted\"\n",
        "script.PY": "print('classification only; do not execute')\n",
        "markup.HTML": "<html><body><p>preview test &amp; plain text safety</p></body></html>\n",
        "payload.json": json.dumps({"中文": True, "nested": [1, 2, 3]}, ensure_ascii=False),
        "empty.txt": "",
    }
    for name, payload in samples.items():
        write_text(base / "样例" / name, payload)

    write_bytes(base / "编码" / "utf8_bom.txt", b"\xef\xbb\xbfUTF-8 BOM\n")
    write_bytes(base / "编码" / "utf16_le.txt", "UTF-16 中文\n".encode("utf-16"))
    write_bytes(base / "编码" / "invalid_utf8.txt", b"valid\n\xff\xfe\x80broken\x00tail")
    write_bytes(base / "编码" / "nul_bytes.txt", b"before\x00middle\x00after")
    write_bytes(base / "编码" / "binary_named_txt.txt", bytes(range(256)) * 32)
    write_text(base / "内容边界" / "single_line_8MiB.log", "A" * (8 * 1024 * 1024))
    write_text(base / "内容边界" / "mixed_newlines.txt", "CRLF\r\nLF\nCR\rEND")
    sparse_file(base / "内容边界" / "sparse_256MiB.bin", 256 * 1024 * 1024)

    long_name = "超长文件名_" + "界" * 105 + ".txt"
    write_text(base / "文件名边界" / long_name, "near the common Windows filename limit\n")
    for name in ("CON.txt", "PRN.txt", "AUX.txt", "NUL.txt"):
        # Windows rejects these names on disk; the same cases are present inside archives.
        try:
            write_text(base / "文件名边界" / name, "reserved Windows name\n")
        except OSError:
            pass

    bulk = base / "12500_小文件"
    for index in range(count):
        bucket = bulk / f"层_{index % 25:02d}" / f"组_{(index // 25) % 20:02d}"
        suffix = ("txt", "md", "csv", "json", "bin")[index % 5]
        write_text(bucket / f"批量_{index:05d}.{suffix}", f"index={index}; bucket={index % 25}\n")
    return {"bulk_files": count, "sparse_logical_bytes": 256 * 1024 * 1024}


def make_depth_and_collision_files(root: Path) -> dict[str, int]:
    base = root / "02_路径深度_重名_隐藏"
    current = base / "深层目录"
    depth_created = 0
    for index in range(36):
        candidate = current / f"d{index:02d}_abcdefghij"
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            write_text(candidate / f"depth_{index:02d}.txt", f"depth={index}\n")
        except OSError:
            break
        current = candidate
        depth_created += 1

    for folder in ("A", "B", "C", "文档", "文档/子目录"):
        write_text(base / "跨目录同名" / folder / "report.txt", f"source={folder}\n")
    write_text(base / "跨目录同名" / "report.txt", "root collision candidate\n")
    write_text(base / ".隐藏目录" / "secret.txt", "hidden directory test\n")
    write_text(base / ".aifo_stage_should_be_skipped" / "partial.txt", "reserved staging name\n")
    write_text(base / "aifo_extract_should_be_skipped" / "partial.txt", "reserved extraction name\n")
    write_text(base / ".aifo_validation" / "partial.txt", "reserved validation name\n")
    marker_dir = base / "标记归档库"
    write_text(marker_dir / ".aifo-archive-store", "AI File Organizer archive store v1\n")
    write_text(marker_dir / "must_not_scan.txt", "archive store exclusion test\n")

    link_status = 0
    target = base / "链接目标" / "inside.txt"
    write_text(target, "safe in-tree target\n")
    try:
        (base / "file_symlink.txt").symlink_to(target)
        link_status += 1
    except OSError:
        pass
    try:
        (base / "dir_symlink").symlink_to(target.parent, target_is_directory=True)
        link_status += 1
    except OSError:
        pass
    try:
        os.link(target, base / "hardlink_same_content.txt")
        link_status += 1
    except OSError:
        pass
    return {"depth_created": depth_created, "link_variants_created": link_status}


def make_media_and_documents(root: Path) -> dict[str, int]:
    base = root / "03_媒体与文档畸形"
    # Valid 1x1 transparent PNG.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6360000000020001e221bc330000000049454e44ae426082"
    )
    write_bytes(base / "valid_1x1.png", png)
    write_bytes(base / "truncated.png", png[:33])
    write_bytes(base / "fake.jpg", b"\xff\xd8\xff\xe1not-a-real-jpeg\xff\xd9")
    # Tiny BMP header claiming enormous dimensions; decoder should fail safely.
    bmp = bytearray(54)
    bmp[:2] = b"BM"
    struct.pack_into("<I", bmp, 2, 54)
    struct.pack_into("<I", bmp, 10, 54)
    struct.pack_into("<I", bmp, 14, 40)
    struct.pack_into("<ii", bmp, 18, 100_000, 100_000)
    struct.pack_into("<HH", bmp, 26, 1, 24)
    write_bytes(base / "huge_dimensions_tiny_payload.bmp", bytes(bmp))
    write_bytes(base / "empty.pdf", b"")
    write_bytes(base / "corrupt.pdf", b"%PDF-1.7\n1 0 obj << /Length 999999 >> stream\nbroken")
    write_bytes(base / "minimal.pdf", b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF")
    sparse_file(base / "over_50MiB_sparse.pdf", 51 * 1024 * 1024, b"%%EOF")
    write_bytes(base / "office_signature_only.docx", b"PK\x03\x04not-an-office-file")
    write_bytes(base / "audio_signature_only.mp3", b"ID3\x04\x00\x00\x00\x00\x00\x00")
    return {"media_files": 10, "oversize_pdf_logical_bytes": 51 * 1024 * 1024}


def make_archives(root: Path) -> dict[str, int]:
    base = root / "04_压缩包安全边界"
    base.mkdir(parents=True, exist_ok=True)

    write_bytes(base / "valid_mixed.zip", zip_bytes([
        ("docs/readme.txt", "正常中文内容\n".encode()),
        ("images/fake.png", b"not really an image"),
        ("empty.bin", b""),
    ]))
    write_bytes(base / "zip_slip_parent.zip", zip_bytes([("../../escape.txt", b"must never escape")]))
    write_bytes(base / "zip_absolute_path.zip", zip_bytes([("/absolute/escape.txt", b"blocked")]))
    write_bytes(base / "zip_windows_drive_ads.zip", zip_bytes([
        ("C:/escape.txt", b"blocked"), ("safe.txt:evil", b"blocked")
    ]))
    write_bytes(base / "zip_windows_reserved_names.zip", zip_bytes([
        ("CON.txt", b"blocked"), ("folder/NUL.bin", b"blocked"), ("trailing-dot./x.txt", b"blocked")
    ]))
    write_bytes(base / "zip_unicode_collision.zip", zip_bytes([
        ("caf\u00e9.txt", b"NFC"), ("cafe\u0301.txt", b"NFD")
    ]))
    write_bytes(base / "zip_case_collision.zip", zip_bytes([("A/Report.txt", b"one"), ("a/report.TXT", b"two")]))
    write_bytes(base / "zip_high_compression_ratio.zip", zip_bytes([("zeros_16MiB.bin", b"\0" * (16 * 1024 * 1024))]))

    many_path = base / "zip_10001_entries.zip"
    with zipfile.ZipFile(many_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for index in range(10_001):
            archive.writestr(f"tiny/{index:05d}.txt", b"")

    long_member = "/".join(["segment"] * 257) + "/x.txt"
    write_bytes(base / "zip_too_many_path_parts.zip", zip_bytes([(long_member, b"blocked")]))

    symlink_info = zipfile.ZipInfo("link_to_elsewhere")
    symlink_info.create_system = 3
    symlink_info.external_attr = 0o120777 << 16
    with zipfile.ZipFile(base / "zip_symlink_entry.zip", "w") as archive:
        archive.writestr(symlink_info, "../../outside.txt")

    nested = zip_bytes([("payload.txt", b"deep")])
    for depth in range(7):
        nested = zip_bytes([(f"level_{depth}.zip", nested)])
    write_bytes(base / "nested_7_levels.zip", nested)

    with tarfile.open(base / "tar_traversal.tar", "w") as archive:
        info = tarfile.TarInfo("../../escape.txt")
        payload = b"must never escape"
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    with tarfile.open(base / "tar_links_and_fifo.tar", "w") as archive:
        link = tarfile.TarInfo("unsafe_symlink")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside.txt"
        archive.addfile(link)
        fifo = tarfile.TarInfo("unsafe_fifo")
        fifo.type = tarfile.FIFOTYPE
        archive.addfile(fifo)

    write_bytes(base / "corrupt.zip", b"PK\x03\x04truncated")
    write_bytes(base / "not_really.7z", b"7z\xbc\xaf\x27\x1cgarbage")
    write_bytes(base / "not_really.rar", b"Rar!\x1a\x07\x01\x00garbage")
    write_bytes(base / "empty.tar.gz", b"")
    return {"archive_files": 18, "many_entry_count": 10_001, "nested_levels": 7}


def make_manifest(root: Path, details: dict[str, int], started: float) -> None:
    all_files = [path for path in root.rglob("*") if path.is_file()]
    logical_bytes = sum(path.stat().st_size for path in all_files)
    manifest = {
        "purpose": "AI File Organizer 极限/安全边界测试素材",
        "generated_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(root.resolve()),
        "file_count": len(all_files),
        "logical_bytes": logical_bytes,
        "generation_seconds": round(time.monotonic() - started, 3),
        "details": details,
        "notes": [
            "请选择本目录作为扫描目录；源码模式不能扫描项目自身目录。",
            "先关闭自动解压做扫描/UI压力，再单独开启自动解压验证安全拦截。",
            "04_压缩包安全边界包含恶意成员名，但它们只存在于归档内部。",
            "不要把本目录当作真实资料整理；执行整理前务必检查预览。",
            "大文件使用稀疏布局或高压缩内容，逻辑大小明显高于实际占用。",
        ],
    }
    write_text(root / "00_TEST_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    readme = f"""# AI File Organizer 极限测试素材

生成位置：`{root.resolve()}`

规模：约 {manifest['file_count']:,} 个文件，逻辑大小 {logical_bytes / 1024**2:.1f} MiB。

建议顺序：

1. 默认设置、关闭自动解压，扫描整个目录，观察停止响应、UI 滚动/排序/筛选和内存占用。
2. 分别切换递归扫描、扫描隐藏文件，确认隐藏目录、链接和 `.aifo_*` 内部目录被正确排除。
3. 开启自动识别但不开启解压，检查 ZIP/TAR/7z/RAR 状态。
4. 开启自动解压，先把单包最大文件数设为 10000、最大压缩比设为 200、递归层数设为 3，验证危险包被拦截且任务继续。
5. 只对少量普通样例执行整理，再撤销；不要一次移动全部 12,500 个压力文件，除非专门测试长事务。
6. API 极限测试会产生真实费用；如要测试，先只选择少量“待确认”文件。

详细机器可读数据见 `00_TEST_MANIFEST.json`。
"""
    write_text(root / "README_先读我.md", readme)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a safe, disposable extreme-test corpus.")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--file-count", type=int, default=DEFAULT_FILE_COUNT)
    args = parser.parse_args()
    root = args.destination.expanduser().resolve()
    if root.exists():
        raise SystemExit(f"Refusing to overwrite existing destination: {root}")
    if args.file_count < 1 or args.file_count > 100_000:
        raise SystemExit("--file-count must be between 1 and 100000")
    root.mkdir(parents=True)
    started = time.monotonic()
    details: dict[str, int] = {}
    details.update(make_ordinary_files(root, args.file_count))
    details.update(make_depth_and_collision_files(root))
    details.update(make_media_and_documents(root))
    details.update(make_archives(root))
    make_manifest(root, details, started)
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
