from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QLocale
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class GuideText:
    window_title: str
    language_label: str
    close_label: str
    html: str


LANGUAGE_NAMES = {
    "zh_CN": "简体中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
}


GUIDE_TEXTS: dict[str, GuideText] = {
    "zh_CN": GuideText(
        window_title="AI File Organizer 使用指南",
        language_label="指南语言：",
        close_label="关闭",
        html="""
        <h1>AI File Organizer 快速指南</h1>
        <p>先扫描、再核对建议，最后通过预览执行。程序默认不删除或覆盖文件；重命名和 AI 都是可选功能。</p>
        <h2>1. 扫描与分类</h2>
        <ol><li>选择文件夹并点击“扫描”。</li><li>前缀和扩展名规则会先分类；只有“待确认”文件才需要手动处理或 AI。</li><li>双击“建议分类”可手动修改。手动选择优先级最高。</li></ol>
        <h2>2. API 与隐私</h2>
        <p>从“API 配置…”填写 Base URL、API Key 和模型并测试连接。无 Key 时规则分类、解压和整理仍可使用。只有主动点击“AI 分析”才联网；文本、完整路径和图片发送均可在设置中控制。</p>
        <h2>3. 可选重命名</h2>
        <p>默认只分类移动。需要改名时，先在“重命名选项…”设置模板，再单独勾选“启用重命名（可选）”。同名文件会生成 <code>(1)</code>、<code>(2)</code>，不会覆盖。</p>
        <h2>4. 解压</h2>
        <p>自动解压默认关闭。开启后会固定查找所选目录的全部子目录，不受普通文件“递归扫描”开关影响；压缩包内部递归仍受最大层数控制。密码库只尝试你提供的密码，不暴力破解，也不在日志显示密码。可疑路径、异常压缩比、超限容量或扫描后被替换的压缩包会被安全拦截。</p>
        <h2>5. 预览、执行与撤销</h2>
        <p>点击“预览整理”查看源路径和目标路径；“执行整理”前可逐条取消。撤销也会先显示预览，并校验文件身份与路径边界。</p>
        <h2>6. 语言与材质</h2>
        <p>可用主窗口“语言”菜单即时切换界面，也可在“设置 → 外观”中选择语言和材质包。材质包是只包含 JSON 颜色与可选背景图的 <code>.aifopack</code>，不允许 QSS 或脚本。</p>
        <h2>遇到问题</h2>
        <p>先查看底部日志和 <code>logs/app.log</code>。权限不足、文件占用、密码错误或 API 超时只影响对应项目；可处理原因后重新扫描或重试。</p>
        """,
    ),
    "en": GuideText(
        window_title="AI File Organizer User Guide",
        language_label="Guide language:",
        close_label="Close",
        html="""
        <h1>AI File Organizer — Quick Guide</h1>
        <p>Scan first, review every suggestion, then organize from the preview. The app does not overwrite or permanently delete files by default. Renaming and AI are optional.</p>
        <h2>1. Scan and classify</h2>
        <ol><li>Choose a folder and select <b>Scan</b>.</li><li>Prefix and extension rules run before AI.</li><li>Double-click the suggested category to make a manual, highest-priority choice.</li></ol>
        <h2>2. API and privacy</h2>
        <p>Open <b>API Settings</b> to enter the Base URL, API key, and model. Rules, extraction, and organizing work without a key. Network requests occur only after you start AI analysis; text, full paths, and images have separate privacy controls.</p>
        <h2>3. Optional rename</h2>
        <p>Organizing normally moves files without renaming. Configure a template, then explicitly enable optional renaming. Name conflicts become <code>(1)</code>, <code>(2)</code>, and are never overwritten.</p>
        <h2>4. Archives</h2>
        <p>Automatic extraction is off by default. When enabled, every subfolder of the selected folder is searched independently of the regular recursive-scan option; recursion inside archives still follows the configured depth limit. Only passwords you provide are tried. Unsafe paths, suspicious compression ratios, capacity limits, and archives changed after scanning are blocked.</p>
        <h2>5. Preview and undo</h2>
        <p>Review source and destination paths before execution and uncheck unwanted rows. Undo has its own preview and verifies both file identity and path boundaries.</p>
        <h2>6. Language and materials</h2>
        <p>Use the main-window <b>Language</b> menu for an immediate switch, or open <b>Settings → Appearance</b> to select a language or material pack. A <code>.aifopack</code> contains JSON colors and one optional background image only—scripts and arbitrary QSS are not allowed.</p>
        <h2>Troubleshooting</h2>
        <p>Check the in-app log and <code>logs/app.log</code>. A locked file, permission error, wrong archive password, or API timeout affects only that item; correct the cause and retry.</p>
        """,
    ),
    "ja": GuideText(
        window_title="AI File Organizer ユーザーガイド",
        language_label="ガイドの言語：",
        close_label="閉じる",
        html="""
        <h1>AI File Organizer クイックガイド</h1>
        <p>最初にスキャンし、提案を確認してからプレビュー経由で整理します。既定では上書きや完全削除を行いません。AI と名前変更は任意です。</p>
        <h2>1. スキャンと分類</h2>
        <p>フォルダーを選んで「スキャン」を押します。接頭辞・拡張子ルールが AI より先に適用されます。提案カテゴリをダブルクリックすると手動分類できます。</p>
        <h2>2. API とプライバシー</h2>
        <p>「API 設定」で Base URL、API Key、モデルを入力します。Key がなくてもルール分類、解凍、整理は利用できます。通信は AI 分析を開始したときだけ行われ、本文・フルパス・画像は個別に送信可否を設定できます。</p>
        <h2>3. 任意の名前変更</h2>
        <p>通常は分類移動のみです。テンプレートを設定し、名前変更のチェックを明示的に有効にしてください。同名ファイルは <code>(1)</code>、<code>(2)</code> となり、上書きされません。</p>
        <h2>4. 圧縮ファイル</h2>
        <p>自動解凍は既定で無効です。有効にすると、通常ファイルの再帰スキャン設定に関係なく選択フォルダーの全サブフォルダーを検索します。アーカイブ内部の再帰は設定した最大階層に従います。登録したパスワードだけを順番に試し、危険なパス、異常な圧縮率、容量超過、スキャン後に変更された書庫は遮断されます。</p>
        <h2>5. プレビューと元に戻す</h2>
        <p>実行前に移動元と移動先を確認し、不要な行を外します。「元に戻す」にもプレビューとファイル同一性の検査があります。</p>
        <h2>6. 言語とマテリアル</h2>
        <p>メインウィンドウの「言語」メニューですぐに切り替えられます。「設定 → 外観」で言語や <code>.aifopack</code> も選択できます。パックには JSON の色と任意の背景画像だけが許可され、QSS やスクリプトは禁止です。</p>
        <h2>問題が発生した場合</h2>
        <p>画面下部のログと <code>logs/app.log</code> を確認してください。権限不足、使用中のファイル、パスワードエラー、API タイムアウトは該当項目だけに影響します。原因を解消してから再スキャンまたは再試行してください。</p>
        """,
    ),
    "ko": GuideText(
        window_title="AI File Organizer 사용자 가이드",
        language_label="가이드 언어:",
        close_label="닫기",
        html="""
        <h1>AI File Organizer 빠른 가이드</h1>
        <p>먼저 스캔하고 제안을 확인한 뒤 미리보기에서 정리를 실행하세요. 기본값은 파일을 덮어쓰거나 영구 삭제하지 않습니다. AI와 이름 변경은 선택 기능입니다.</p>
        <h2>1. 스캔과 분류</h2>
        <p>폴더를 선택하고 “스캔”을 누릅니다. 접두사 및 확장자 규칙이 AI보다 먼저 적용됩니다. 제안 분류를 두 번 클릭하면 최우선 수동 분류를 지정할 수 있습니다.</p>
        <h2>2. API와 개인정보</h2>
        <p>“API 설정”에서 Base URL, API Key, 모델을 입력합니다. Key가 없어도 규칙 분류, 압축 해제, 정리를 사용할 수 있습니다. AI 분석을 직접 시작할 때만 통신하며 본문, 전체 경로, 이미지 전송을 각각 끌 수 있습니다.</p>
        <h2>3. 선택적 이름 변경</h2>
        <p>기본 동작은 분류 이동뿐입니다. 템플릿을 설정한 후 이름 변경 확인란을 별도로 켜세요. 충돌 시 <code>(1)</code>, <code>(2)</code>가 붙고 덮어쓰지 않습니다.</p>
        <h2>4. 압축 파일</h2>
        <p>자동 압축 해제는 기본적으로 꺼져 있습니다. 켜면 일반 파일의 재귀 스캔 설정과 관계없이 선택한 폴더의 모든 하위 폴더를 찾으며, 압축 파일 내부 재귀는 설정한 최대 깊이를 따릅니다. 사용자가 제공한 비밀번호만 순서대로 시도하고 위험한 경로, 비정상 압축률, 용량 초과, 스캔 후 변경된 압축 파일은 차단합니다.</p>
        <h2>5. 미리보기와 실행 취소</h2>
        <p>실행 전에 원본과 대상을 확인하고 원치 않는 행을 해제하세요. 실행 취소도 미리보기를 거치며 파일 신원과 경로 경계를 다시 검사합니다.</p>
        <h2>6. 언어와 머티리얼</h2>
        <p>메인 창의 “언어” 메뉴에서 즉시 전환하거나 “설정 → 모양”에서 언어와 <code>.aifopack</code>을 선택하세요. 팩에는 JSON 색상과 선택적 배경 이미지만 허용되며 QSS와 스크립트는 금지됩니다.</p>
        <h2>문제 해결</h2>
        <p>화면 아래 로그와 <code>logs/app.log</code>를 확인하세요. 권한 부족, 사용 중인 파일, 압축 비밀번호 오류 또는 API 시간 초과는 해당 항목에만 영향을 줍니다. 원인을 해결한 뒤 다시 스캔하거나 재시도하세요.</p>
        """,
    ),
}


def normalized_guide_language(language: str | None) -> str:
    value = (language or QLocale.system().name() or "zh_CN").replace("-", "_").lower()
    if value.startswith("zh"):
        return "zh_CN"
    if value.startswith("ja"):
        return "ja"
    if value.startswith("ko"):
        return "ko"
    return "en"


class UserGuideDialog(QDialog):
    """Self-contained multilingual guide suitable for a one-file build."""

    def __init__(self, parent: QWidget | None = None, language: str | None = None):
        super().__init__(parent)
        self.resize(820, 680)

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.language_label = QLabel()
        self.language_box = QComboBox()
        self.language_box.setAccessibleName("Guide language")
        for code, name in LANGUAGE_NAMES.items():
            self.language_box.addItem(name, code)
        toolbar.addWidget(self.language_label)
        toolbar.addWidget(self.language_box)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.browser = QTextBrowser()
        self.browser.setAccessibleName("User guide")
        self.browser.setOpenExternalLinks(False)
        layout.addWidget(self.browser, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        selected = normalized_guide_language(language)
        self.language_box.setCurrentIndex(self.language_box.findData(selected))
        self.language_box.currentIndexChanged.connect(self._language_changed)
        self.set_language(selected)

    @property
    def language(self) -> str:
        return str(self.language_box.currentData() or "zh_CN")

    def _language_changed(self, _index: int) -> None:
        self.set_language(self.language)

    def set_language(self, language: str) -> None:
        code = normalized_guide_language(language)
        index = self.language_box.findData(code)
        if index >= 0 and index != self.language_box.currentIndex():
            self.language_box.blockSignals(True)
            self.language_box.setCurrentIndex(index)
            self.language_box.blockSignals(False)
        text = GUIDE_TEXTS[code]
        self.setWindowTitle(text.window_title)
        self.language_label.setText(text.language_label)
        self.browser.setHtml(text.html)
        self.browser.moveCursor(QTextCursor.Start)
        close_button = self.buttons.button(QDialogButtonBox.Close)
        if close_button is not None:
            close_button.setText(text.close_label)


__all__ = [
    "GUIDE_TEXTS",
    "LANGUAGE_NAMES",
    "UserGuideDialog",
    "normalized_guide_language",
]
