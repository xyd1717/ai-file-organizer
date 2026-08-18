from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSizePolicy, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.api.client import AIClient
from app.api.providers import (
    API_PROVIDER_PRESETS,
    CUSTOM_PROVIDER_ID,
    provider_by_id,
    provider_for_base_url,
)
from app.core.extractor import find_7zip
from app.core.material_pack import BUILTIN_IDS, MaterialPackError, MaterialPackManager
from app.core.password_store import PasswordStore
from app.core.secret_store import get_api_key, normalized_api_origin, set_api_key
from app.database.repository import Repository
from app.i18n import language_choices, tr, translate_widget_tree
from app.models.schemas import AppSettings, ClassificationRule, RuleType
from app.ui.workers import TaskWorker


class RuleManagerDialog(QDialog):
    def __init__(self, repository: Repository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle("分类规则管理器")
        self.resize(850, 480)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["ID", "类型", "匹配内容", "分类", "启用", "优先级", "区分大小写"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        for text, slot in (("新增", self.add_rule), ("删除", self.delete_rule), ("上移", lambda: self.move_priority(-10)), ("下移", lambda: self.move_priority(10)), ("保存修改", self.save_all), ("测试规则", self.test_rule)):
            button = QPushButton(text); button.clicked.connect(slot); buttons.addWidget(button)
        layout.addLayout(buttons)
        close = QDialogButtonBox(QDialogButtonBox.Close); close.rejected.connect(self.accept); layout.addWidget(close)
        self.table.itemChanged.connect(self._sync_boolean_item)
        self.reload()
        translate_widget_tree(self)

    def _boolean_item(self, value: bool) -> QTableWidgetItem:
        item = QTableWidgetItem(tr("是") if value else tr("否"))
        item.setData(Qt.ItemDataRole.UserRole, bool(value))
        item.setFlags((item.flags() & ~Qt.ItemFlag.ItemIsEditable) | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)
        return item

    def _sync_boolean_item(self, item: QTableWidgetItem):
        if item.column() not in {4, 6}:
            return
        value = item.checkState() == Qt.CheckState.Checked
        self.table.blockSignals(True)
        try:
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setText(tr("是") if value else tr("否"))
        finally:
            self.table.blockSignals(False)

    @staticmethod
    def _item_boolean(item: QTableWidgetItem | None) -> bool:
        if item is None:
            return False
        value = item.data(Qt.ItemDataRole.UserRole)
        return bool(value) if isinstance(value, bool) else item.checkState() == Qt.CheckState.Checked

    def reload(self):
        rules = self.repository.get_rules()
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(rules))
            for row, rule in enumerate(rules):
                values = [str(rule.id or ""), rule.rule_type.value, rule.pattern, rule.category, "", str(rule.priority), ""]
                for col, value in enumerate(values):
                    item = self._boolean_item(rule.enabled if col == 4 else rule.case_sensitive) if col in {4, 6} else QTableWidgetItem(value)
                    if col == 0: item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row, col, item)
        finally:
            self.table.blockSignals(False)

    def add_rule(self):
        row = self.table.rowCount(); self.table.insertRow(row)
        values = ["", "prefix", "", "", "", str(100 + row * 10), ""]
        for col, value in enumerate(values):
            self.table.setItem(row, col, self._boolean_item(col == 4) if col in {4, 6} else QTableWidgetItem(value))
        self.table.setCurrentCell(row, 2)

    def save_all(self):
        try:
            for row in range(self.table.rowCount()):
                value = lambda c: self.table.item(row, c).text().strip()
                rule = ClassificationRule(id=int(value(0)) if value(0) else None, rule_type=RuleType(value(1)), pattern=value(2), category=value(3), enabled=self._item_boolean(self.table.item(row, 4)), priority=int(value(5)), case_sensitive=self._item_boolean(self.table.item(row, 6)))
                rule.id = self.repository.save_rule(rule)
            self.reload(); QMessageBox.information(self, tr("规则"), tr("规则已保存"))
        except Exception as exc:
            QMessageBox.warning(self, tr("无法保存"), str(exc))

    def delete_rule(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            value = self.table.item(row, 0).text()
            if value: self.repository.delete_rule(int(value))
            self.table.removeRow(row)

    def move_priority(self, delta: int):
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 5); item.setText(str(max(0, int(item.text()) + delta)))

    def test_rule(self):
        row = self.table.currentRow()
        if row < 0: return
        filename, ok = QInputDialog.getText(self, tr("测试规则"), tr("输入文件名："))
        if not ok: return
        try:
            value = lambda c: self.table.item(row, c).text().strip()
            rule = ClassificationRule(rule_type=RuleType(value(1)), pattern=value(2), category=value(3), case_sensitive=self._item_boolean(self.table.item(row, 6)))
            from app.core.classifier import RuleClassifier
            QMessageBox.information(self, tr("测试结果"), tr("匹配成功") if RuleClassifier.matches(rule, filename) else tr("不匹配"))
        except Exception as exc: QMessageBox.warning(self, tr("测试失败"), str(exc))


class PasswordManagerDialog(QDialog):
    def __init__(self, store: PasswordStore, parent=None):
        super().__init__(parent); self.store = store
        self.setWindowTitle("解压密码管理"); self.resize(650, 380)
        layout = QVBoxLayout(self)
        hint = "密码保存在系统凭据存储中。" if store.backend_available() else "系统安全凭据存储不可用：新增密码仅在本次运行中有效。"
        layout.addWidget(QLabel(hint))
        self.table = QTableWidget(0, 5); self.table.setHorizontalHeaderLabels(["ID", "密码", "备注", "启用", "优先级"])
        self.table.setColumnHidden(0, True); self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch); layout.addWidget(self.table)
        bar = QHBoxLayout(); self.show_box = QCheckBox("显示密码"); self.show_box.toggled.connect(self.reload); bar.addWidget(self.show_box)
        for text, fn in (("添加", self.add), ("修改", self.edit), ("启用/禁用", self.toggle), ("删除", self.delete), ("上移", lambda: self.shift(-10)), ("下移", lambda: self.shift(10))):
            b=QPushButton(text); b.clicked.connect(fn); bar.addWidget(b)
        layout.addLayout(bar); close=QDialogButtonBox(QDialogButtonBox.Close); close.rejected.connect(self.accept); layout.addWidget(close); self.reload()
        translate_widget_tree(self)

    def reload(self):
        entries=self.store.list_entries(); self.table.setRowCount(len(entries))
        for r,e in enumerate(entries):
            visible=self.store.get_secret(e.id) or "（当前不可用）"
            vals=[e.id, visible if self.show_box.isChecked() else "••••••••", e.note, tr("是") if e.enabled else tr("否"), str(e.priority)]
            for c,v in enumerate(vals):
                item=QTableWidgetItem(v)
                if c==3:item.setData(Qt.ItemDataRole.UserRole,bool(e.enabled))
                self.table.setItem(r,c,item)

    def add(self):
        password, ok=QInputDialog.getText(self,tr("添加密码"),tr("密码："),QLineEdit.Password)
        if not ok or not password: return
        note, _=QInputDialog.getText(self,tr("添加密码"),tr("备注："))
        self.store.add(password,note); self.reload()

    def edit(self):
        row=self.table.currentRow()
        if row<0:return
        eid=self.table.item(row,0).text(); old=next(x for x in self.store.list_entries() if x.id==eid)
        note,ok=QInputDialog.getText(self,tr("修改密码"),tr("备注："),text=old.note)
        if not ok:return
        password,change=QInputDialog.getText(self,tr("修改密码"),tr("新密码（取消则不变）："),QLineEdit.Password)
        old.note=note; self.store.update(old,password if change and password else None); self.reload()

    def delete(self):
        row=self.table.currentRow()
        if row>=0:self.store.delete(self.table.item(row,0).text());self.reload()

    def toggle(self):
        row=self.table.currentRow()
        if row<0:return
        eid=self.table.item(row,0).text();entry=next(x for x in self.store.list_entries() if x.id==eid);entry.enabled=not entry.enabled;self.store.update(entry);self.reload()

    def shift(self,delta):
        row=self.table.currentRow()
        if row<0:return
        eid=self.table.item(row,0).text(); entry=next(x for x in self.store.list_entries() if x.id==eid); entry.priority=max(0,entry.priority+delta); self.store.update(entry); self.reload()


class RenameOptionsDialog(QDialog):
    PRESETS = {
        "日期_分类_原文件名": "{date}_{category}_{original_name}",
        "分类_AI标题": "{category}_{ai_title}",
        "年-月-标题": "{year}-{month}-{title}",
        "自定义": "",
    }

    def __init__(self, repository: Repository, parent=None):
        super().__init__(parent);self.repository=repository;self.settings=repository.load_settings()
        self.setWindowTitle("重命名选项（独立可选功能）");self.resize(560,260);layout=QVBoxLayout(self)
        layout.addWidget(QLabel("重命名默认关闭。只有主窗口单独勾选“启用重命名”时，整理过程才会修改文件名。"))
        form=QFormLayout();self.preset=QComboBox()
        for label,template in self.PRESETS.items():self.preset.addItem(label,template)
        preset_index=self.preset.findData(self.settings.rename_template,Qt.ItemDataRole.UserRole)
        self.preset.setCurrentIndex(preset_index if preset_index>=0 else self.preset.count()-1)
        self.template=QLineEdit(self.settings.rename_template);self.example=QLabel();self.example.setWordWrap(True);form.addRow("模板预设",self.preset);form.addRow("模板",self.template);form.addRow("示例",self.example);layout.addLayout(form)
        self.preset.currentIndexChanged.connect(self.apply_preset);self.template.textChanged.connect(self.update_example);self.update_example()
        box=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);box.button(QDialogButtonBox.Save).setText("保存");box.button(QDialogButtonBox.Cancel).setText("取消");box.accepted.connect(self.save);box.rejected.connect(self.reject);layout.addWidget(box)
        translate_widget_tree(self)

    def apply_preset(self,_index=None):
        value=self.preset.currentData(Qt.ItemDataRole.UserRole)
        if value:self.template.setText(value)

    def update_example(self,*_):
        values={"date":"2026-08-18","year":"2026","month":"08","category":"财务","original_name":"invoice_001","ai_title":"酒店发票","title":"酒店发票"}
        try:preview=self.template.text().format(**values)+".pdf"
        except (KeyError,ValueError) as exc:preview=tr("模板错误：{error}",error=exc)
        self.example.setText(preview)

    def save(self):
        try:
            self.settings.rename_template=self.template.text().strip();self.settings.allow_rename=True;self.repository.save_settings(self.settings);self.accept()
        except Exception as exc:QMessageBox.warning(self,tr("无法保存"),str(exc))


class SettingsDialog(QDialog):
    def __init__(self, repository: Repository, password_store: PasswordStore, parent=None, initial_tab: int = 0, material_manager: MaterialPackManager | None = None):
        super().__init__(parent); self.repository=repository; self.password_store=password_store; self.settings=repository.load_settings();self.material_manager=material_manager or MaterialPackManager(repository.db_path.parent);self.materials_changed=False
        self.test_thread=None;self.test_worker=None;self.test_client:AIClient|None=None;self._close_pending=False;self._loaded_origin=normalized_api_origin(self.settings.api_base_url);self._current_origin=self._loaded_origin
        self.setWindowTitle("设置"); self.resize(690,560); root=QVBoxLayout(self); self.tabs=QTabWidget(); root.addWidget(self.tabs);tabs=self.tabs
        api=QWidget(); api_layout=QVBoxLayout(api); privacy=QLabel("API 配置只在此界面管理。仅在你主动点击“AI 分析”时才会联网；API Key 按服务地址隔离保存在系统凭据中，不写入 SQLite 或源码。");privacy.setWordWrap(True);privacy.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum);privacy.setProperty("role","notice");api_layout.addWidget(privacy);f=QFormLayout();api_layout.addLayout(f)
        self.provider=QComboBox();self.provider.setObjectName("apiProviderCombo");self.provider.setProperty("_aifo_i18n_skip_items",True);self.provider.addItem(tr("自定义（OpenAI 兼容）"),CUSTOM_PROVIDER_ID)
        for preset in API_PROVIDER_PRESETS:self.provider.addItem(tr(preset.name),preset.id)
        matched_provider=provider_for_base_url(self.settings.api_base_url);provider_id=matched_provider.id if matched_provider else CUSTOM_PROVIDER_ID;self.provider.setCurrentIndex(max(0,self.provider.findData(provider_id)))
        self.base=QLineEdit(self.settings.api_base_url);self.base.setAccessibleName("API Base URL");self.base.editingFinished.connect(self.base_url_changed);self.base.textEdited.connect(self._base_manually_edited)
        self.key=QLineEdit(get_api_key(self.settings.api_base_url));self.key.setEchoMode(QLineEdit.Password);self.key.setAccessibleName("API Key")
        self.model=QComboBox();self.model.setEditable(True);self.model.setInsertPolicy(QComboBox.NoInsert);self.model.setAccessibleName("API Model")
        self.provider_note=QLabel();self.provider_note.setWordWrap(True);self.provider_note.setTextFormat(Qt.TextFormat.PlainText);self.provider_note.setProperty("role","muted")
        self.provider_docs=QPushButton("打开厂商文档");self.provider_docs.clicked.connect(self.open_provider_docs)
        self.timeout=QSpinBox();self.timeout.setRange(3,300);self.timeout.setValue(self.settings.api_timeout);self.concurrent=QSpinBox();self.concurrent.setRange(1,20);self.concurrent.setValue(self.settings.api_concurrency);self.temp=QDoubleSpinBox();self.temp.setRange(0,2);self.temp.setValue(self.settings.temperature);self.input_cost=QDoubleSpinBox();self.input_cost.setRange(0,10000);self.input_cost.setDecimals(6);self.input_cost.setValue(self.settings.input_cost_per_million);self.output_cost=QDoubleSpinBox();self.output_cost.setRange(0,10000);self.output_cost.setDecimals(6);self.output_cost.setValue(self.settings.output_cost_per_million)
        for label,w in (("API 厂商预设",self.provider),("Base URL",self.base),("API Key",self.key),("模型",self.model),("厂商说明",self.provider_note),("",self.provider_docs),("超时（秒）",self.timeout),("并发数",self.concurrent),("Temperature",self.temp),("输入费用 / 百万 Token",self.input_cost),("输出费用 / 百万 Token",self.output_cost)):f.addRow(label,w)
        self.show_key=QCheckBox("显示 API Key");self.show_key.toggled.connect(lambda visible:self.key.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password));f.addRow("",self.show_key);self.test_button=QPushButton("测试连接");self.test_button.clicked.connect(self.test_api);f.addRow(self.test_button);self.api_result=QLabel("尚未测试连接");self.api_result.setWordWrap(True);self.api_result.setProperty("role","muted");f.addRow("连接状态",self.api_result);tabs.addTab(api,"API")
        self.provider.currentIndexChanged.connect(self.provider_changed);self._populate_provider_models(provider_id,self.settings.api_model)
        ai=QWidget(); ai_layout=QVBoxLayout(ai);ai_note=QLabel("隐私提示：文件名和基础元数据会发送给 API；正文、完整目录和图片分别由下列开关控制。图片会先缩略并重新编码，移除 EXIF/GPS。");ai_note.setWordWrap(True);ai_note.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum);ai_note.setProperty("role","notice");ai_layout.addWidget(ai_note);f=QFormLayout();ai_layout.addLayout(f); self.high=QDoubleSpinBox();self.high.setRange(0,1);self.high.setSingleStep(.05);self.high.setValue(self.settings.high_confidence);self.low=QDoubleSpinBox();self.low.setRange(0,1);self.low.setValue(self.settings.low_confidence);self.vision=QCheckBox();self.vision.setChecked(self.settings.allow_vision);self.send_text=QCheckBox();self.send_text.setChecked(self.settings.ai_send_text_content);self.send_path=QCheckBox();self.send_path.setChecked(self.settings.ai_send_full_path);self.chars=QSpinBox();self.chars.setRange(100,100000);self.chars.setValue(self.settings.max_text_chars)
        for label,w in (("自动建议阈值",self.high),("待确认阈值",self.low),("发送有限文本内容",self.send_text),("发送完整所在目录",self.send_path),("允许图片识别",self.vision),("文本最大字符",self.chars)):f.addRow(label,w)
        tabs.addTab(ai,"AI")
        files=QWidget(); f=QFormLayout(files); self.recursive=QCheckBox();self.recursive.setChecked(self.settings.recursive_scan);self.hidden=QCheckBox();self.hidden.setChecked(self.settings.scan_hidden);self.keep_structure=QCheckBox();self.keep_structure.setChecked(self.settings.keep_structure);self.rename=QCheckBox();self.rename.setChecked(self.settings.allow_rename);self.template=QLineEdit(self.settings.rename_template)
        for label,w in (("递归扫描",self.recursive),("扫描隐藏/系统文件",self.hidden),("保留原目录结构",self.keep_structure),("允许使用可选重命名",self.rename),("默认重命名模板",self.template)):f.addRow(label,w)
        tabs.addTab(files,"文件")
        security=QWidget();f=QFormLayout(security);self.confirm=QCheckBox();self.confirm.setChecked(True);self.confirm.setEnabled(False);self.confirm.setToolTip(tr("安全要求：实际移动前始终显示可逐条取消的预览"));self.history=QCheckBox();self.history.setChecked(self.settings.history_enabled);self.undo=QCheckBox();self.undo.setChecked(self.settings.undo_enabled)
        for label,w in (("执行前必须确认",self.confirm),("启用操作历史",self.history),("允许撤销",self.undo)):f.addRow(label,w)
        tabs.addTab(security,"安全")
        extract=QWidget();f=QFormLayout(extract);extract_note=QLabel("自动解压会固定递归查找所选目录的全部子目录，不受普通文件“递归扫描”开关影响。");extract_note.setWordWrap(True);extract_note.setProperty("role","muted");f.addRow(extract_note);self.detect=QCheckBox();self.detect.setChecked(self.settings.auto_detect_archives);self.auto_extract=QCheckBox();self.auto_extract.setChecked(self.settings.auto_extract);self.rescan=QCheckBox();self.rescan.setChecked(self.settings.rescan_extracted);self.archive_action=QComboBox();self.archive_action.addItem("保留原压缩包","keep");self.archive_action.addItem("移动到“已解压压缩包”","move");self.archive_action.addItem("放入回收站","trash");self.archive_action.setCurrentIndex(max(0,self.archive_action.findData(self.settings.archive_after_extract)));self.extract_mode=QComboBox();self.extract_mode.addItem("当前目录","beside");self.extract_mode.addItem("统一目录","unified");self.extract_mode.addItem("临时目录","temporary");self.extract_mode.setCurrentIndex(max(0,self.extract_mode.findData(self.settings.extract_mode)));self.extract_dir=QLineEdit(self.settings.extract_directory);self.named=QCheckBox();self.named.setChecked(self.settings.create_named_folder);self.depth=QSpinBox();self.depth.setRange(0,5);self.depth.setValue(self.settings.max_extract_depth);self.max_size=QSpinBox();self.max_size.setRange(1,102400);self.max_size.setValue(self.settings.max_archive_unpacked_bytes//1024//1024);self.max_files=QSpinBox();self.max_files.setRange(1,1000000);self.max_files.setValue(self.settings.max_archive_files);self.ratio=QDoubleSpinBox();self.ratio.setRange(1,10000);self.ratio.setValue(self.settings.max_compression_ratio);self.task_size=QSpinBox();self.task_size.setRange(1,1024000);self.task_size.setValue(self.settings.max_task_extract_bytes//1024//1024)
        for label,w in (("自动识别压缩包",self.detect),("自动解压",self.auto_extract),("解压后继续扫描",self.rescan),("解压成功后处理原包",self.archive_action),("解压模式",self.extract_mode),("统一解压目录",self.extract_dir),("创建同名文件夹",self.named),("最大递归层数",self.depth),("单包最大 MB",self.max_size),("单包最大文件数",self.max_files),("最大压缩比",self.ratio),("任务最大 MB",self.task_size)):f.addRow(label,w)
        seven=find_7zip();f.addRow("7-Zip 检测",QLabel(str(seven) if seven else "未检测到（ZIP/7z/TAR 仍可由 Python 库处理；RAR 可能不可用）"))
        manage=QPushButton("管理解压密码…");manage.clicked.connect(lambda:PasswordManagerDialog(self.password_store,self).exec());f.addRow(manage);tabs.addTab(extract,"解压")

        appearance=QWidget();appearance_layout=QVBoxLayout(appearance);appearance_form=QFormLayout();appearance_layout.addLayout(appearance_form)
        self.language=QComboBox();self.language.setObjectName("languageCombo")
        for code,native_name in language_choices():self.language.addItem(native_name,code)
        language_index=self.language.findData(self.settings.ui_language,Qt.ItemDataRole.UserRole);self.language.setCurrentIndex(max(0,language_index))
        self.material=QComboBox();self.material.setObjectName("materialPackCombo");self.material.setProperty("_aifo_i18n_skip_items",True)
        appearance_form.addRow("界面语言",self.language);appearance_form.addRow("界面材质包",self.material)
        material_buttons=QHBoxLayout();self.import_material_button=QPushButton("导入材质包…");self.delete_material_button=QPushButton("删除材质包");self.example_material_button=QPushButton("生成示例包…")
        for button in (self.import_material_button,self.delete_material_button,self.example_material_button):material_buttons.addWidget(button)
        appearance_layout.addLayout(material_buttons);self.material_status=QLabel();self.material_status.setWordWrap(True);appearance_layout.addWidget(self.material_status);self.material_preview=QLabel();self.material_preview.setTextFormat(Qt.TextFormat.PlainText);self.material_preview.setWordWrap(True);self.material_preview.setProperty("role","notice");appearance_layout.addWidget(self.material_preview);appearance_layout.addStretch(1)
        self.import_material_button.clicked.connect(self.import_material);self.delete_material_button.clicked.connect(self.delete_material);self.example_material_button.clicked.connect(self.create_example_material);self.material.currentIndexChanged.connect(self._material_selection_changed)
        self.refresh_materials(self.settings.material_pack);tabs.addTab(appearance,"外观")
        tabs.setCurrentIndex(max(0,min(initial_tab,tabs.count()-1)))
        box=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);self.button_box=box;box.button(QDialogButtonBox.Save).setText("保存");box.button(QDialogButtonBox.Cancel).setText("取消");box.accepted.connect(self.save);box.rejected.connect(self.reject);root.addWidget(box)
        translate_widget_tree(self)

    def _populate_provider_models(self, provider_id: str, selected_model: str = ""):
        preset=provider_by_id(provider_id);models=preset.models if preset else ()
        self.model.blockSignals(True)
        try:
            self.model.clear()
            for model_name in models:self.model.addItem(model_name)
            if selected_model:
                index=self.model.findText(selected_model,Qt.MatchFlag.MatchFixedString)
                if index<0:self.model.addItem(selected_model);index=self.model.count()-1
                self.model.setCurrentIndex(index)
            elif models:self.model.setCurrentIndex(0)
        finally:self.model.blockSignals(False)
        self.provider_note.setText(tr(preset.note) if preset else tr("填写任意 OpenAI-compatible 服务地址和模型名称。"))
        self.provider_docs.setEnabled(preset is not None)

    def provider_changed(self,*_):
        provider_id=self.provider.currentData(Qt.ItemDataRole.UserRole) or CUSTOM_PROVIDER_ID
        preset=provider_by_id(provider_id)
        if preset is None:
            self._populate_provider_models(CUSTOM_PROVIDER_ID,self.model.currentText().strip())
            return
        self.base.setText(preset.base_url)
        self._populate_provider_models(provider_id,preset.default_model)
        self.base_url_changed()
        self._set_api_result(tr("已载入 {provider} 预设；请填写该厂商的 API Key 后测试连接。",provider=tr(preset.name)),None)

    def _base_manually_edited(self,*_):
        custom_index=self.provider.findData(CUSTOM_PROVIDER_ID,Qt.ItemDataRole.UserRole)
        if custom_index>=0 and self.provider.currentIndex()!=custom_index:
            self.provider.blockSignals(True);self.provider.setCurrentIndex(custom_index);self.provider.blockSignals(False)
            self._populate_provider_models(CUSTOM_PROVIDER_ID,self.model.currentText().strip())

    def open_provider_docs(self):
        preset=provider_by_id(self.provider.currentData(Qt.ItemDataRole.UserRole) or "")
        if preset:QDesktopServices.openUrl(QUrl(preset.docs_url))

    def refresh_materials(self, selected_id: str | None = None):
        selected_id=selected_id or self.material.currentData(Qt.ItemDataRole.UserRole) or "default"
        self.material.blockSignals(True)
        try:
            self.material.clear()
            for pack in self.material_manager.list_packs():
                self.material.addItem(tr(pack.name) if pack.id in BUILTIN_IDS else pack.name,pack.id)
            index=self.material.findData(selected_id,Qt.ItemDataRole.UserRole)
            if index<0:index=self.material.findData("default",Qt.ItemDataRole.UserRole)
            self.material.setCurrentIndex(max(0,index))
        finally:
            self.material.blockSignals(False)
        if self.material_manager.last_errors:
            self.material_status.setText(tr("部分材质包无法读取：")+"；".join(self.material_manager.last_errors[:3]))
        else:self.material_status.setText(tr("材质包只允许颜色令牌和一张背景图片，不执行 QSS 或脚本。"))
        self._material_selection_changed()

    def _material_selection_changed(self,*_):
        pack_id=self.material.currentData(Qt.ItemDataRole.UserRole)
        self.delete_material_button.setEnabled(bool(pack_id) and pack_id not in BUILTIN_IDS)
        try:
            pack=self.material_manager.get_pack(pack_id or "default");manifest=pack.manifest
            display_name=tr(pack.name) if pack.id in BUILTIN_IDS else pack.name
            origin=tr("内置材质（不可删除）") if pack.id in BUILTIN_IDS else tr("自定义材质")
            background=manifest.background or tr("无")
            description=tr(manifest.description) if pack.id in BUILTIN_IDS else manifest.description
            self.material_preview.setText(tr("材质预览\n名称：{name}\n来源：{origin}\n版本：{version}\n作者：{author}\n背景：{background}\n说明：{description}",name=display_name,origin=origin,version=manifest.version,author=manifest.author or "-",background=background,description=description or "-"))
        except (MaterialPackError,OSError):self.material_preview.clear()

    def import_material(self):
        filename,_=QFileDialog.getOpenFileName(self,tr("导入材质包"),str(Path.home()),"AI File Organizer (*.aifopack)")
        if not filename:return
        try:
            pack=self.material_manager.import_pack(Path(filename));self.materials_changed=True;self.refresh_materials(pack.id)
            QMessageBox.information(self,tr("材质包"),tr("已导入：{name}",name=pack.name))
        except (MaterialPackError,OSError) as exc:QMessageBox.warning(self,tr("无法导入材质包"),str(exc))

    def delete_material(self):
        pack_id=self.material.currentData(Qt.ItemDataRole.UserRole)
        if not isinstance(pack_id,str) or pack_id in BUILTIN_IDS:return
        if QMessageBox.question(self,tr("删除材质包"),tr("确定删除自定义材质包“{name}”吗？",name=self.material.currentText()))!=QMessageBox.Yes:return
        try:
            self.material_manager.delete_pack(pack_id);self.materials_changed=True
            if self.settings.material_pack==pack_id:
                self.settings.material_pack="default";self.repository.save_settings(self.settings)
            self.refresh_materials("default")
        except (MaterialPackError,OSError) as exc:QMessageBox.warning(self,tr("无法删除材质包"),str(exc))

    def create_example_material(self):
        filename,_=QFileDialog.getSaveFileName(self,tr("生成示例材质包"),str(Path.home()/"my-material.aifopack"),"AI File Organizer (*.aifopack)")
        if not filename:return
        try:
            output=self.material_manager.create_example(Path(filename));QMessageBox.information(self,tr("材质包"),tr("示例包已生成：{path}",path=output))
        except (MaterialPackError,OSError) as exc:QMessageBox.warning(self,tr("无法生成示例包"),str(exc))

    def collect(self):
        action=self.archive_action.currentData()
        return AppSettings(ui_language=self.language.currentData(Qt.ItemDataRole.UserRole) or "zh_CN",material_pack=self.material.currentData(Qt.ItemDataRole.UserRole) or "default",api_base_url=self.base.text().strip(),api_model=self.model.currentText().strip(),api_timeout=self.timeout.value(),api_concurrency=self.concurrent.value(),api_max_retries=self.settings.api_max_retries,api_max_batch_chars=self.settings.api_max_batch_chars,api_max_response_bytes=self.settings.api_max_response_bytes,input_cost_per_million=self.input_cost.value(),output_cost_per_million=self.output_cost.value(),temperature=self.temp.value(),high_confidence=self.high.value(),low_confidence=self.low.value(),allow_vision=self.vision.isChecked(),ai_send_text_content=self.send_text.isChecked(),ai_send_full_path=self.send_path.isChecked(),vision_max_dimension=self.settings.vision_max_dimension,vision_max_source_bytes=self.settings.vision_max_source_bytes,max_text_chars=self.chars.value(),recursive_scan=self.recursive.isChecked(),scan_hidden=self.hidden.isChecked(),keep_structure=self.keep_structure.isChecked(),allow_rename=self.rename.isChecked(),rename_template=self.template.text(),require_confirmation=True,history_enabled=self.history.isChecked(),undo_enabled=self.undo.isChecked(),auto_detect_archives=self.detect.isChecked(),auto_extract=self.auto_extract.isChecked(),rescan_extracted=self.rescan.isChecked(),keep_archive=action=="keep",archive_after_extract=action,extract_mode=self.extract_mode.currentData(Qt.ItemDataRole.UserRole) or "beside",extract_directory=self.extract_dir.text(),create_named_folder=self.named.isChecked(),max_extract_depth=self.depth.value(),max_archive_unpacked_bytes=self.max_size.value()*1024**2,max_archive_files=self.max_files.value(),max_compression_ratio=self.ratio.value(),max_task_extract_bytes=self.task_size.value()*1024**2)

    def save(self):
        if self.test_thread:
            QMessageBox.information(self,tr("连接测试进行中"),tr("请等待连接测试完成后再保存。"));return
        try:
            new_settings=self.collect()
            if new_settings.archive_after_extract=="trash" and self.settings.archive_after_extract!="trash":
                answer=QMessageBox.question(self,tr("确认回收站行为"),tr("启用后，解压成功的原压缩包会被放入系统回收站。此项不是永久删除，但应用内撤销不保证可恢复。是否启用？"))
                if answer!=QMessageBox.Yes:return
            self.settings=new_settings;self.repository.save_settings(self.settings);secure=set_api_key(self.key.text(),self.settings.api_base_url);QMessageBox.information(self,tr("设置"),tr("设置已保存。")+(tr("API Key 已存入系统凭据。") if secure else tr("API Key 仅保存在本次运行中。")));self.accept()
        except Exception as exc:QMessageBox.warning(self,tr("保存失败"),str(exc))

    def base_url_changed(self):
        try:new_origin=normalized_api_origin(self.base.text())
        except ValueError:return
        if new_origin == self._current_origin:return
        self._current_origin=new_origin
        if new_origin != self._loaded_origin:
            self.key.clear();self.key.setPlaceholderText("服务地址已变化，请为该服务重新输入 API Key")
        else:
            self.key.setText(get_api_key(self.settings.api_base_url));self.key.setPlaceholderText("")

    def test_api(self):
        if self.test_thread and self.test_thread.isRunning():return
        try:
            settings=self.collect();key=self.key.text().strip()
            if not key:raise ValueError("请先填写 API Key")
        except Exception as exc:
            self._set_api_result(tr("配置有误：{error}",error=exc),"danger");return
        self.test_button.setEnabled(False);self.test_button.setText(tr("正在测试…"));self.button_box.setEnabled(False);self._set_api_result(tr("正在连接，请稍候…"),None)
        client=AIClient(settings,key);self.test_client=client
        def check(stopped,_progress):
            client.set_stop_check(stopped)
            try:
                model,latency=client.test_connection();return True,model,latency
            except Exception as exc:return False,str(exc),None
        thread=QThread(self);worker=TaskWorker(check);self.test_thread,self.test_worker=thread,worker;worker.moveToThread(thread);thread.started.connect(worker.run);worker.result.connect(self.test_api_done);worker.finished.connect(thread.quit);worker.finished.connect(worker.deleteLater);thread.finished.connect(lambda t=thread:self._test_thread_done(t));thread.finished.connect(thread.deleteLater);thread.start()

    def test_api_done(self,result):
        ok,message,latency=result
        if ok:self._set_api_result(tr("连接成功 · 模型：{model} · 延迟：{latency} ms",model=message,latency=latency),"success")
        else:self._set_api_result(tr("连接失败：{error}",error=message),"danger")

    def _set_api_result(self,text,status):
        self.api_result.setText(text);self.api_result.setProperty("role","muted" if status is None else "")
        self.api_result.setProperty("status",status);self.api_result.style().unpolish(self.api_result);self.api_result.style().polish(self.api_result)

    def _test_thread_done(self,thread):
        if self.test_thread is thread:self.test_thread=None;self.test_worker=None;self.test_client=None
        self.test_button.setEnabled(True);self.test_button.setText(tr("测试连接"));self.button_box.setEnabled(True)
        if self._close_pending:self.reject()

    def _cancel_connection_test(self):
        if self.test_worker:self.test_worker.cancel()
        if self.test_client:self.test_client.cancel()
        self._close_pending=True;self._set_api_result(tr("正在取消连接测试，随后关闭…"),None)

    def reject(self):
        if self.test_thread:
            self._cancel_connection_test();return
        super().reject()

    def closeEvent(self,event):
        if self.test_thread:
            event.ignore();self._cancel_connection_test();return
        super().closeEvent(event)
