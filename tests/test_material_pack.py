from __future__ import annotations

import json
from pathlib import Path
import stat
import zipfile

import pytest
from pydantic import ValidationError

from app.core.material_pack import (
    BUILTIN_IDS,
    ColorTokens,
    MaterialManifest,
    MaterialPackError,
    MaterialPackManager,
    UnsafeMaterialPack,
)


BASE_COLORS = {
    "window": "#F4F6F8",
    "panel": "#FFFFFF",
    "elevated": "#FFFFFF",
    "input": "#FFFFFF",
    "text": "#20242A",
    "muted_text": "#667085",
    "accent": "#2F6FED",
    "accent_hover": "#245FD1",
    "accent_pressed": "#1C4BA8",
    "border": "#8A94A3",
    "selection_text": "#FFFFFF",
    "success": "#198754",
    "warning": "#B7791F",
    "danger": "#C0392B",
}


def manifest_dict(pack_id: str = "test-pack", **changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "format_version": 1,
        "id": pack_id,
        "name": "Test Pack",
        "version": "1.0",
        "author": "Tester",
        "description": "Safe test material",
        "colors": BASE_COLORS,
        "background": None,
        "background_mode": "cover",
    }
    result.update(changes)
    return result


def write_pack(path: Path, manifest: dict[str, object], extras: dict[str, bytes] | None = None) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in (extras or {}).items():
            archive.writestr(name, data)
    return path


def small_png(width: int = 1, height: int = 1) -> bytes:
    # The validator intentionally needs only the PNG signature and IHDR to
    # perform its decompression-memory guard; Qt performs full decoding later.
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def test_builtin_materials_and_stylesheet_are_data_only(tmp_path: Path) -> None:
    manager = MaterialPackManager(tmp_path)
    assert {item.id for item in manager.list_packs()} == BUILTIN_IDS
    assert manager.stylesheet("default") == ""
    sheet = manager.stylesheet("ocean")
    assert "#087EA4" in sheet
    assert "url(" not in sheet
    assert "QPushButton:hover" in sheet

    class Target:
        value = ""

        def setStyleSheet(self, value: str) -> None:  # noqa: N802 - mirrors Qt
            self.value = value

    target = Target()
    assert manager.apply(target, "dark") == "dark"
    assert "#171A1F" in target.value
    assert manager.apply(target, "default") == "default"
    assert target.value == ""


def test_manifest_is_strict_and_rejects_qss_injection() -> None:
    with pytest.raises(ValidationError):
        MaterialManifest.model_validate({**manifest_dict(), "qss": "QWidget { color:red; }"})
    bad = manifest_dict()
    bad["colors"] = {**BASE_COLORS, "accent": "red; background:url(file:///secret)"}
    with pytest.raises(ValidationError):
        MaterialManifest.model_validate(bad)
    with pytest.raises(ValidationError):
        ColorTokens.model_validate({**BASE_COLORS, "script": "alert(1)"})
    with pytest.raises(ValidationError):
        MaterialManifest.model_validate(manifest_dict(id="../escape"))


def test_manifest_rejects_unreadable_colour_contrast() -> None:
    unreadable = manifest_dict()
    unreadable["colors"] = {**BASE_COLORS, "text": "#FFFFFF", "input": "#FFFFFF"}
    with pytest.raises(ValidationError, match="对比度不足"):
        MaterialManifest.model_validate(unreadable)


def test_manifest_rejects_ambiguous_eight_digit_qt_colours() -> None:
    ambiguous = manifest_dict()
    ambiguous["colors"] = {**BASE_COLORS, "text": "#000000FF"}
    with pytest.raises(ValidationError, match="#RRGGBB"):
        MaterialManifest.model_validate(ambiguous)


@pytest.mark.parametrize("name", ["<b>System Pack</b>", "Two\nLines", "safe\u202eevil"])
def test_manifest_rejects_deceptive_material_names(name: str) -> None:
    with pytest.raises(ValidationError, match="单行纯文本"):
        MaterialManifest.model_validate(manifest_dict(name=name))


def test_create_import_list_replace_and_delete(tmp_path: Path) -> None:
    manager = MaterialPackManager(tmp_path / "data")
    example = manager.create_example(tmp_path / "sample")
    assert example.suffix == ".aifopack"
    installed = manager.import_pack(example)
    assert installed.id == "my-material"
    assert manager.get_pack("my-material").manifest.name == "My Material"
    assert [item.id for item in manager.list_packs()][-1] == "my-material"

    with pytest.raises(MaterialPackError, match="已存在"):
        manager.import_pack(example)
    manager.import_pack(example, replace=True)
    manager.delete_pack("my-material")
    assert {item.id for item in manager.list_packs()} == BUILTIN_IDS
    with pytest.raises(MaterialPackError, match="内置"):
        manager.delete_pack("default")


def test_import_background_and_generate_safe_uri(tmp_path: Path) -> None:
    manager = MaterialPackManager(tmp_path / "data")
    archive = write_pack(
        tmp_path / "ocean-photo.aifopack",
        manifest_dict("ocean-photo", background="background image.png", background_mode="center"),
        {"background image.png": small_png()},
    )
    installed = manager.import_pack(archive)
    assert installed.background_path is not None
    sheet = manager.stylesheet("ocean-photo")
    assert "background-image: url(" in sheet
    assert "background%20image.png" in sheet


@pytest.mark.parametrize(
    ("member", "payload"),
    [
        ("../manifest.json", b"{}"),
        ("folder/manifest.json", b"{}"),
        ("C:manifest.json", b"{}"),
        ("evil.qss", b"QWidget { background: red; }"),
        ("evil.py", b"raise SystemExit"),
    ],
)
def test_import_rejects_traversal_and_undeclared_payloads(
    tmp_path: Path, member: str, payload: bytes,
) -> None:
    manager = MaterialPackManager(tmp_path / "data")
    archive_path = tmp_path / "unsafe.aifopack"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest_dict()))
        archive.writestr(member, payload)
    with pytest.raises(UnsafeMaterialPack):
        manager.import_pack(archive_path)


def test_import_rejects_duplicate_casefolded_names(tmp_path: Path) -> None:
    manager = MaterialPackManager(tmp_path / "data")
    archive_path = tmp_path / "duplicate.aifopack"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest_dict()))
        archive.writestr("MANIFEST.JSON", json.dumps(manifest_dict()))
    with pytest.raises(UnsafeMaterialPack, match="重复"):
        manager.import_pack(archive_path)


def test_import_rejects_symlink_entry(tmp_path: Path) -> None:
    manager = MaterialPackManager(tmp_path / "data")
    archive_path = tmp_path / "link.aifopack"
    link = zipfile.ZipInfo("background.png")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest_dict(background="background.png")))
        archive.writestr(link, b"manifest.json")
    with pytest.raises(UnsafeMaterialPack, match="链接"):
        manager.import_pack(archive_path)


def test_import_rejects_compression_bomb_ratio(tmp_path: Path) -> None:
    manager = MaterialPackManager(tmp_path / "data")
    archive_path = tmp_path / "bomb.aifopack"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", b" " * 60_000)
    with pytest.raises(UnsafeMaterialPack, match="压缩比"):
        manager.import_pack(archive_path)


def test_import_rejects_huge_image_dimensions(tmp_path: Path) -> None:
    manager = MaterialPackManager(tmp_path / "data")
    archive = write_pack(
        tmp_path / "pixels.aifopack",
        manifest_dict("pixels", background="background.png"),
        {"background.png": small_png(8192, 8192)},
    )
    with pytest.raises(UnsafeMaterialPack, match="像素"):
        manager.import_pack(archive)


def test_invalid_installed_pack_does_not_break_listing(tmp_path: Path) -> None:
    manager = MaterialPackManager(tmp_path / "data")
    broken = manager.storage_directory / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("not json", encoding="utf-8")
    assert {item.id for item in manager.list_packs()} == BUILTIN_IDS
    assert manager.last_errors and manager.last_errors[0].startswith("broken:")
