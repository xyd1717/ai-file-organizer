from __future__ import annotations

import pytest

from app.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    SUPPORTED_LANGUAGES,
    get_language,
    language_choices,
    language_name,
    normalize_language,
    set_language,
    tr,
    translate_widget_tree,
)


@pytest.fixture(autouse=True)
def restore_chinese():
    set_language(DEFAULT_LANGUAGE)
    yield
    set_language(DEFAULT_LANGUAGE)


def test_supported_language_codes_and_names_are_stable():
    assert SUPPORTED_LANGUAGES == ("zh_CN", "en", "ja", "ko")
    assert language_choices() == tuple(LANGUAGE_NAMES.items())
    assert language_name("zh_CN") == "简体中文"
    assert language_name("en") == "English"
    assert language_name("ja") == "日本語"
    assert language_name("ko") == "한국어"


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("zh", "zh_CN"),
        ("ZH-cn", "zh_CN"),
        ("en_US", "en"),
        ("jp", "ja"),
        ("ko-KR", "ko"),
        ("unsupported", "zh_CN"),
        (None, "zh_CN"),
    ],
)
def test_language_normalization_and_safe_fallback(requested, expected):
    assert normalize_language(requested) == expected
    assert set_language(requested) == expected
    assert get_language() == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("zh_CN", "扫描"),
        ("en", "Scan"),
        ("ja", "スキャン"),
        ("ko", "스캔"),
    ],
)
def test_core_action_is_translated_in_all_languages(code, expected):
    set_language(code)
    assert tr("扫描") == expected


def test_representative_main_window_and_dialog_strings_are_translated():
    set_language("en")
    assert tr("设置与规则") == "Settings & Rules"
    assert tr("原文件名") == "Original Name"
    assert tr("启用重命名（可选）") == "Enable Rename (Optional)"
    assert tr("解压密码管理") == "Extraction Passwords"
    assert tr("自动解压") == "Extract Automatically"

    set_language("ja")
    assert tr("执行整理") == "整理を実行"
    assert tr("测试连接") == "接続テスト"

    set_language("ko")
    assert tr("分类规则管理器") == "분류 규칙 관리자"
    assert tr("撤销上次操作") == "마지막 작업 실행 취소"


def test_missing_key_falls_back_to_chinese_source():
    set_language("en")
    assert tr("尚未加入词典的中文") == "尚未加入词典的中文"


def test_keyword_formatting_works_for_each_language():
    source = "扫描完成：{count} 个文件；规则直接处理：{matched}；需要 AI：{ai}"
    set_language("en")
    assert tr(source, count=12, matched=9, ai=3) == "Scan complete: 12 files; 9 handled by rules; 3 need AI"
    set_language("ja")
    assert tr(source, count=12, matched=9, ai=3) == "スキャン完了：12 件、ルール処理 9 件、AI 処理 3 件"
    set_language("ko")
    assert tr(source, count=12, matched=9, ai=3) == "스캔 완료: 12개, 규칙 처리 9개, AI 필요 3개"


def test_bad_or_incomplete_formatting_never_raises():
    source = "进度 {current}/{total}{detail}"
    set_language("en")
    assert tr(source, current=1) == "Progress {current}/{total}{detail}"
    assert tr("未知 {value:bad-format}", value=3) == "未知 {value:bad-format}"
    assert tr("普通文本", unused=object()) == "普通文本"


def test_widget_tree_translation_is_reversible_and_preserves_dynamic_data(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDialogButtonBox,
        QLabel,
        QLineEdit,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )

    app = QApplication.instance() or QApplication([])
    root = QWidget()
    layout = QVBoxLayout(root)
    label = QLabel("运行日志")
    button = QPushButton("扫描")
    user_input = QLineEdit("C:/用户/文件.txt")
    user_input.setPlaceholderText("搜索文件名或路径")
    dynamic = QLabel("客户甲/项目资料")
    combo = QComboBox()
    combo.addItems(["全部", "客户甲"])
    table = QTableWidget(1, 2)
    table.setHorizontalHeaderLabels(["原文件名", "客户自定义列"])
    table.setItem(0, 0, QTableWidgetItem("合同.pdf"))
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "文件")
    tabs.addTab(QWidget(), "客户甲")
    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    for widget in (label, button, user_input, dynamic, combo, table, tabs, buttons):
        layout.addWidget(widget)

    set_language("en")
    translate_widget_tree(root)
    assert label.text() == "Activity Log"
    assert button.text() == "Scan"
    assert user_input.text() == "C:/用户/文件.txt"
    assert user_input.placeholderText() == "Search file name or path"
    assert dynamic.text() == "客户甲/项目资料"
    assert combo.itemText(0) == "All"
    assert combo.itemText(1) == "客户甲"
    assert table.horizontalHeaderItem(0).text() == "Original Name"
    assert table.horizontalHeaderItem(1).text() == "客户自定义列"
    assert table.item(0, 0).text() == "合同.pdf"
    assert tabs.tabText(0) == "Files"
    assert tabs.tabText(1) == "客户甲"
    assert buttons.button(QDialogButtonBox.Save).text() == "Save"

    set_language("ja")
    translate_widget_tree(root)
    assert label.text() == "実行ログ"
    assert button.text() == "スキャン"
    assert combo.itemText(0) == "すべて"

    set_language("zh_CN")
    translate_widget_tree(root)
    assert label.text() == "运行日志"
    assert button.text() == "扫描"
    assert user_input.placeholderText() == "搜索文件名或路径"
    assert combo.itemText(0) == "全部"
    assert table.horizontalHeaderItem(0).text() == "原文件名"
    assert buttons.button(QDialogButtonBox.Save).text() == "保存"
    root.deleteLater()
    app.processEvents()
