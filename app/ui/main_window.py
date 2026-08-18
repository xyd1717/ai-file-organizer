from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDir, QSize, QThread, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFileSystemModel, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QTextEdit, QTreeView, QVBoxLayout, QWidget,
)

from app.api.client import AIClient, extract_limited_text
from app.core.classifier import RuleClassifier
from app.core.extractor import ArchiveExtractor, ArchiveSourceBinding, ExtractionBlocked
from app.core.material_pack import BUILTIN_IDS, MaterialPackError, MaterialPackManager
from app.core.organizer import Organizer, ensure_safe_directory, move_file_no_overwrite, unique_path
from app.core.password_store import PasswordStore
from app.core.scanner import (
    ARCHIVE_SUFFIXES,
    FileScanner,
    compound_suffix,
    is_aifo_archive_store,
    mark_aifo_archive_store,
)
from app.core.secret_store import get_api_key, secure_backend_available
from app.database.repository import Repository
from app.i18n import get_language, language_choices, set_language, tr, translate_widget_tree
from app.models.schemas import ArchiveStatus, ClassificationRule, FileRecord, OperationRecord, RuleType
from app.ui.dialogs import RenameOptionsDialog, RuleManagerDialog, SettingsDialog
from app.ui.user_guide import UserGuideDialog
from app.ui.workers import TaskWorker


COL_CHECK, COL_NAME, COL_TYPE, COL_PATH, COL_CATEGORY, COL_TARGET, COL_CONF, COL_ACTION, COL_RENAME, COL_STATUS, COL_ARCHIVE = range(11)
LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, repository: Repository, app_root: Path, data_dir: Path | None = None,
                 scanner_excluded_roots: list[Path] | None = None, scanner_excluded_files: list[Path] | None = None):
        super().__init__()
        self.repository, self.app_root = repository, app_root.resolve()
        self.settings = repository.load_settings()
        set_language(self.settings.ui_language)
        self.data_dir=(data_dir or app_root / "data").resolve();self.password_store = PasswordStore(self.data_dir / "passwords.json")
        self.material_manager = MaterialPackManager(self.data_dir)
        material_warning = ""
        try:
            self.material_manager.apply(QApplication.instance(), self.settings.material_pack)
        except (MaterialPackError, OSError) as exc:
            material_warning = str(exc)
            self.material_manager.apply(QApplication.instance(), "default")
            self.settings.material_pack = "default"
            self.repository.save_settings(self.settings)
        self.scanner_excluded_roots=scanner_excluded_roots if scanner_excluded_roots is not None else [app_root]
        self.scanner_excluded_files=scanner_excluded_files or []
        self.records: list[FileRecord] = []
        self.scan_root: Path | None = None
        self.task_root: Path | None = None
        self.task_source_roots: list[Path] = []
        self._extractors: list[ArchiveExtractor] = []
        self.archive_source_bindings: dict[str, ArchiveSourceBinding] = {}
        self.thread: QThread | None = None
        self.worker: TaskWorker | None = None
        self.active_ai_client: AIClient | None = None
        self.next_task = None
        self.active_task_label = ""
        self._close_pending = False
        self.setWindowTitle("AI File Organizer")
        self.resize(1500, 860)
        self._build_ui()
        self._build_menu()
        translate_widget_tree(self)
        self.adjust_table_columns()
        self.append_log(tr("应用已启动；无 API Key 时仍可使用规则分类"))
        if material_warning:
            self.append_log(tr("材质包加载失败，已恢复默认材质：{error}", error=material_warning))

    def _build_menu(self):
        for old_menu in getattr(self, "_owned_menus", []): old_menu.deleteLater()
        self.menuBar().clear()
        menu = self.menuBar().addMenu("设置与规则")
        api = QAction("API 配置…", menu); api.triggered.connect(self.open_api_settings); menu.addAction(api)
        rules = QAction("分类规则管理器", menu); rules.triggered.connect(self.open_rules); menu.addAction(rules)
        settings = QAction("设置", menu); settings.triggered.connect(self.open_settings); menu.addAction(settings)

        language_menu = self.menuBar().addMenu("语言")
        self.language_actions = {}
        for code, native_name in language_choices():
            action = QAction(native_name, language_menu); action.setCheckable(True); action.setChecked(code == get_language())
            action.triggered.connect(lambda _checked=False, selected=code: self.switch_language(selected))
            language_menu.addAction(action); self.language_actions[code] = action

        appearance_menu = self.menuBar().addMenu("外观")
        self.material_actions = {}
        for pack in self.material_manager.list_packs():
            action = QAction(tr(pack.name) if pack.id in BUILTIN_IDS else pack.name, appearance_menu); action.setCheckable(True); action.setChecked(pack.id == self.settings.material_pack)
            if pack.id not in BUILTIN_IDS: action.setProperty("_aifo_i18n_skip", True)
            action.triggered.connect(lambda _checked=False, pack_id=pack.id: self.switch_material(pack_id))
            appearance_menu.addAction(action); self.material_actions[pack.id] = action
        appearance_menu.addSeparator()
        manage_materials = QAction("管理材质包…", appearance_menu); manage_materials.triggered.connect(self.open_appearance_settings); appearance_menu.addAction(manage_materials)

        help_menu = self.menuBar().addMenu("帮助")
        guide = QAction("使用说明", help_menu); guide.triggered.connect(self.open_user_guide); help_menu.addAction(guide)
        self._owned_menus=[menu,language_menu,appearance_menu,help_menu]
        translate_widget_tree(self)

    def switch_language(self, language_code: str):
        settings = self.repository.load_settings()
        settings.ui_language = set_language(language_code)
        self.repository.save_settings(settings); self.settings = settings
        self._build_menu(); translate_widget_tree(self); self.adjust_table_columns(); self.refresh_table(); self.update_api_status()
        if self.table.currentRow() >= 0: self.show_details()
        self.append_log(tr("界面语言已切换为：{language}", language=dict(language_choices())[settings.ui_language]))

    def switch_material(self, pack_id: str):
        try:
            applied = self.material_manager.apply(QApplication.instance(), pack_id)
            settings = self.repository.load_settings(); settings.material_pack = applied
            self.repository.save_settings(settings); self.settings = settings
            self._build_menu(); translate_widget_tree(self); self.refresh_table(); self.update_api_status()
            pack=self.material_manager.get_pack(applied);display_name=tr(pack.name) if pack.id in BUILTIN_IDS else pack.name
            self.append_log(tr("界面材质已切换为：{material}", material=display_name))
        except (MaterialPackError, OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("材质包"), tr("无法应用材质包：{error}", error=exc))

    def apply_saved_interface_settings(self):
        settings = self.repository.load_settings(); set_language(settings.ui_language)
        try:
            settings.material_pack = self.material_manager.apply(QApplication.instance(), settings.material_pack)
        except (MaterialPackError, OSError):
            settings.material_pack = self.material_manager.apply(QApplication.instance(), "default")
            self.repository.save_settings(settings)
        self.settings = settings; self._build_menu(); translate_widget_tree(self); self.adjust_table_columns(); self.refresh_table(); self.update_api_status()
        if self.table.currentRow() >= 0: self.show_details()

    def open_appearance_settings(self):
        dialog = SettingsDialog(self.repository, self.password_store, self, initial_tab=5, material_manager=self.material_manager)
        result=dialog.exec()
        if result == QDialog.Accepted:
            self.apply_saved_interface_settings(); self.append_log(tr("设置已更新"))
        elif dialog.materials_changed:self.apply_saved_interface_settings()

    def open_user_guide(self):
        UserGuideDialog(self, get_language()).exec()

    def _build_ui(self):
        central = QWidget(); central.setObjectName("centralWidget"); outer = QVBoxLayout(central); self.setCentralWidget(central)
        top = QHBoxLayout(); self.folder_edit = QLineEdit(); self.folder_edit.setReadOnly(True); self.folder_edit.setAccessibleName("当前扫描目录"); choose = QPushButton("选择文件夹…"); choose.clicked.connect(self.choose_folder)
        self.search = QLineEdit(); self.search.setPlaceholderText("搜索文件名或路径"); self.search.setAccessibleName("搜索文件"); self.search.textChanged.connect(self.apply_filter)
        self.filter_box = QComboBox(); self.filter_box.setAccessibleName("文件筛选")
        for source in ("全部", "待确认", "规则命中", "AI", "压缩包"): self.filter_box.addItem(source, source)
        self.filter_box.currentIndexChanged.connect(self.apply_filter)
        top.addWidget(QLabel("扫描目录：")); top.addWidget(self.folder_edit, 3); top.addWidget(choose); top.addWidget(self.search, 2); top.addWidget(self.filter_box); outer.addLayout(top)
        api_bar=QHBoxLayout();self.api_status=QLabel();self.api_status.setAccessibleName("API 配置状态");self.api_button=QPushButton("API 配置…");self.api_button.clicked.connect(self.open_api_settings);api_bar.addWidget(self.api_status);api_bar.addStretch(1);api_bar.addWidget(QLabel("AI 只处理规则无法判断的文件"));api_bar.addWidget(self.api_button);outer.addLayout(api_bar);self.update_api_status()
        splitter = QSplitter(Qt.Horizontal); outer.addWidget(splitter, 1)

        left = QWidget(); ll = QVBoxLayout(left); self.tree_model = QFileSystemModel(self); self.tree_model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot); self.tree_model.setRootPath(QDir.rootPath()); self.tree = QTreeView(); self.tree.setAccessibleName("文件夹树"); self.tree.setModel(self.tree_model); self.tree.setHeaderHidden(True)
        for c in range(1,4): self.tree.hideColumn(c)
        self.tree.doubleClicked.connect(self.tree_selected); ll.addWidget(QLabel("文件夹树")); ll.addWidget(self.tree, 3)
        rule_button=QPushButton("管理分类规则");rule_button.clicked.connect(self.open_rules);ll.addWidget(rule_button);ll.addWidget(QLabel("分类列表"));self.categories=QListWidget();self.categories.itemClicked.connect(lambda item:self.filter_category(item.text()));ll.addWidget(self.categories,2);splitter.addWidget(left)

        middle = QWidget(); ml = QVBoxLayout(middle); self.table=QTableWidget(0,11);self.table.setAccessibleName("文件整理列表");self.table.setHorizontalHeaderLabels(["勾选","原文件名","类型","当前路径","建议分类","目标路径","置信度","处理方式","重命名","状态","压缩状态"]);self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setSortingEnabled(True);self.table.itemSelectionChanged.connect(self.show_details);self.table.itemChanged.connect(self.item_changed);self.table.cellDoubleClicked.connect(self.cell_double_clicked);self.table.setContextMenuPolicy(Qt.CustomContextMenu);self.table.customContextMenuRequested.connect(self.archive_menu);ml.addWidget(self.table);splitter.addWidget(middle)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setMinimumSectionSize(56)
        self.adjust_table_columns()

        right=QWidget();rl=QVBoxLayout(right);self.preview=QLabel("选择文件查看预览");self.preview.setTextFormat(Qt.TextFormat.PlainText);self.preview.setAlignment(Qt.AlignCenter);self.preview.setMinimumHeight(220);self.preview.setWordWrap(True);rl.addWidget(self.preview);self.details=QTextEdit();self.details.setReadOnly(True);rl.addWidget(self.details,1);splitter.addWidget(right);splitter.setStretchFactor(0,1);splitter.setStretchFactor(1,6);splitter.setStretchFactor(2,2);splitter.setSizes([220,1060,250])

        controls=QHBoxLayout(); self.action_buttons={}
        buttons=[("扫描",self.start_scan),("停止扫描",self.stop_task),("AI 分析",self.start_ai),("停止分析",self.stop_task),("预览整理",self.preview_organize),("执行整理",self.execute_organize),("撤销上次操作",self.undo_last),("停止解压",self.stop_task)]
        for text,slot in buttons:
            b=QPushButton(text);b.clicked.connect(slot);controls.addWidget(b);self.action_buttons[text]=b
        controls.addStretch(1);outer.addLayout(controls)
        options=QHBoxLayout();self.rename_box=QCheckBox("启用重命名（可选）");self.rename_box.setChecked(False);self.rename_box.toggled.connect(self.rename_toggled);options.addWidget(self.rename_box);rename_options=QPushButton("重命名选项…");rename_options.clicked.connect(self.open_rename_options);options.addWidget(rename_options);options.addSpacing(12);options.addWidget(QLabel("任务进度"));self.progress=QProgressBar();self.progress.setRange(0,100);options.addWidget(self.progress,1);outer.addLayout(options)
        self.log=QTextEdit();self.log.setAccessibleName("运行日志");self.log.setReadOnly(True);self.log.setMaximumHeight(150);outer.addWidget(QLabel("运行日志"));outer.addWidget(self.log);self.update_action_availability()

    def adjust_table_columns(self):
        if not hasattr(self, "table"):
            return
        minimums={COL_CHECK:64,COL_NAME:150,COL_TYPE:82,COL_PATH:180,COL_CATEGORY:145,COL_TARGET:180,COL_CONF:105,COL_ACTION:115,COL_RENAME:100,COL_STATUS:135,COL_ARCHIVE:140}
        metrics=self.table.horizontalHeader().fontMetrics()
        for column,minimum in minimums.items():
            header=self.table.horizontalHeaderItem(column);label=header.text() if header else ""
            self.table.setColumnWidth(column,max(minimum,metrics.horizontalAdvance(label)+30))

    def append_log(self, message: str):
        self.log.append(f"[{datetime.now():%H:%M:%S}] {message}")
        LOGGER.info(message)

    def choose_folder(self):
        folder=QFileDialog.getExistingDirectory(self,tr("选择要扫描的目录"),str(self.scan_root or Path.home()))
        if folder:self.set_folder(Path(folder))

    def set_folder(self, folder: Path):
        folder=folder.resolve()
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self,tr("任务进行中"),tr("当前任务结束或停止后才能切换扫描目录。"));return
        if self.make_scanner().folder_is_protected(folder):
            QMessageBox.warning(self,tr("安全拦截"),tr("系统目录和程序安装目录不能作为整理范围。"))
            self.append_log(tr("安全拦截：禁止选择系统目录 {folder}", folder=folder))
            return
        if self.scan_root and folder!=self.scan_root:
            self.records=[];self.archive_source_bindings={};self.task_root=None;self.task_source_roots=[];self.refresh_table();self.details.clear();self.preview.setText(tr("选择文件查看预览"))
        self.scan_root=folder;self.folder_edit.setText(str(self.scan_root));self.tree.setRootIndex(self.tree_model.index(str(self.scan_root)));self.update_action_availability()

    def make_scanner(self):
        return FileScanner(excluded_roots=self.scanner_excluded_roots,excluded_files=self.scanner_excluded_files)

    def tree_selected(self,index):
        path=Path(self.tree_model.filePath(index))
        if path.is_dir():self.set_folder(path)

    def run_task(self, function, on_result, label: str):
        if self.thread and self.thread.isRunning(): QMessageBox.information(self,tr("任务进行中"),tr("请先停止或等待当前任务完成。"));return
        thread=QThread(self);worker=TaskWorker(function);self.thread,self.worker=thread,worker;self.active_task_label=label;worker.moveToThread(thread);thread.started.connect(worker.run);worker.progress.connect(self.on_progress);worker.result.connect(on_result);worker.error.connect(lambda error,current_label=label:self.task_error(current_label,error));worker.finished.connect(thread.quit);worker.finished.connect(worker.deleteLater);thread.finished.connect(lambda t=thread:self.task_finished(t));thread.finished.connect(thread.deleteLater);self.append_log(tr("{label}开始",label=tr(label)));self.update_action_availability();thread.start()

    def task_error(self, label: str, error: str):
        summary = error.splitlines()[-1] if error else tr("未知错误")
        self.append_log(tr("{label}失败：{error}", label=tr(label), error=summary))
        QMessageBox.warning(self, tr(label), error or summary)

    def task_finished(self, thread):
        finished_label = self.active_task_label if self.thread is thread else ""
        if self.thread is thread:
            self.thread=None;self.worker=None;self.active_task_label=""
        if finished_label == "AI 分析":
            self.active_ai_client = None
        self.progress.setRange(0,100);self.progress.setValue(0);self.update_action_availability()
        next_task,self.next_task=self.next_task,None
        if next_task:next_task()
        elif self._close_pending:QTimer.singleShot(0,self.close)

    def stop_task(self):
        requested = False
        if self.worker:
            self.worker.cancel();requested = True
        if self.active_ai_client:
            self.active_ai_client.cancel();requested = True
        if requested:
            self.append_log(tr("已请求安全停止当前任务"))

    def on_progress(self,args):
        if len(args)>=2 and isinstance(args[0],int) and isinstance(args[1],int):
            if args[1] <= 0:self.progress.setRange(0,0)
            else:self.progress.setRange(0,100);self.progress.setValue(int(args[0]*100/max(args[1],1)))
            tail=f"：{args[2]}" if len(args)>2 else "";total="?" if args[1] <= 0 else str(args[1]);self.statusBar().showMessage(tr("进度 {current}/{total}{detail}",current=args[0],total=total,detail=tail))
        elif args:self.statusBar().showMessage(" ".join(map(str,args)))

    def update_action_availability(self):
        if not hasattr(self,"action_buttons"):
            return
        busy=bool(self.thread)
        has_records=bool(self.records and self.task_root)
        self.action_buttons["扫描"].setEnabled(bool(self.scan_root) and not busy)
        self.action_buttons["AI 分析"].setEnabled(has_records and not busy)
        self.action_buttons["预览整理"].setEnabled(has_records and not busy)
        self.action_buttons["执行整理"].setEnabled(has_records and not busy)
        self.action_buttons["撤销上次操作"].setEnabled(not busy and self.settings.history_enabled and self.settings.undo_enabled)
        for name,label in (("停止扫描","扫描"),("停止分析","AI 分析"),("停止解压","解压")):
            self.action_buttons[name].setEnabled(busy and self.active_task_label==label)

    def start_scan(self):
        if not self.scan_root:QMessageBox.information(self,tr("扫描"),tr("请先选择文件夹"));return
        if self._extractors:
            extractors,self._extractors=self._extractors,[];self.next_task=self.start_scan;self.start_extraction_cleanup(extractors);return
        root=self.scan_root;self.task_root=root;self.task_source_roots=[root];self.archive_source_bindings={};settings=self.repository.load_settings().model_copy(deep=True);scanner=self.make_scanner()
        def scan_task(stopped,progress):
            result=scanner.scan(root,settings.recursive_scan,settings.scan_hidden,stopped,lambda n,name:progress(n,-1,name));bindings={}
            if settings.auto_extract and not stopped():
                discovered=scanner.discover_archives(root,settings.scan_hidden,stopped,lambda n,name:progress(n,-1,tr("递归查找压缩包：{name}",name=name)))
                known={ArchiveExtractor.source_key(record.path) for record in result}
                for record in discovered:
                    key=ArchiveExtractor.source_key(record.path)
                    if key not in known:result.append(record);known.add(key)
            for record in result:
                if stopped():break
                if compound_suffix(record.path) not in ARCHIVE_SUFFIXES:continue
                try:
                    binding=ArchiveExtractor.capture_source_binding(record.path,record.scan_root or root);bindings[ArchiveExtractor.source_key(record.path)]=binding
                except (OSError,ExtractionBlocked) as exc:
                    record.archive_status=ArchiveStatus.BLOCKED;record.status="安全拦截";record.reason=str(exc)
            return result,stopped(),bindings,settings
        self.run_task(scan_task,self.scan_done,"扫描")

    def scan_done(self, result):
        records,cancelled,bindings,task_settings=result;self.archive_source_bindings=bindings
        self.settings=self.repository.load_settings()
        if not task_settings.auto_detect_archives and not task_settings.auto_extract:
            for record in records:record.archive_status=ArchiveStatus.NONE
        classifier=RuleClassifier(self.repository.get_rules());self.records=classifier.classify_all(records);self.refresh_table();matched=sum(r.source!="待确认" for r in self.records);self.append_log(tr("扫描完成：{count} 个文件；规则直接处理：{matched}；需要 AI：{ai}",count=len(self.records),matched=matched,ai=len(self.records)-matched))
        archives=[r.path for r in self.records if r.archive_status==ArchiveStatus.WAITING]
        if cancelled:self.append_log(tr("扫描已停止；保留已扫描结果，不继续自动解压"))
        elif archives and task_settings.auto_extract:
            self.append_log(tr("自动解压已在全部子目录中发现 {count} 个压缩包",count=len(archives)))
            self.next_task=lambda:self.start_extract(archives,task_settings=task_settings)

    def start_extract(self, archives:list[Path], extra_password:str|None=None, task_settings=None):
        settings=(task_settings or self.repository.load_settings()).model_copy(deep=True)
        if settings.extract_mode == "unified" and self.make_scanner().folder_is_protected(Path(settings.extract_directory)):
            message = tr("统一解压目录不能位于系统目录或应用自身目录。请在设置中选择普通用户目录。")
            self.append_log(tr("安全拦截：{message}",message=message))
            QMessageBox.warning(self,tr("安全拦截"),message)
            return
        extractor=ArchiveExtractor(settings);self._extractors.append(extractor);passwords=self.password_store.enabled_passwords();roots=tuple(self.task_source_roots)
        expected={Path(path):self.archive_source_bindings[ArchiveExtractor.source_key(path)] for path in archives if ArchiveExtractor.source_key(path) in self.archive_source_bindings}
        if extra_password:passwords=[(0,extra_password)]+passwords
        self.run_task(lambda stopped,progress:extractor.extract_recursive(archives,passwords,stopped,progress,allowed_source_roots=roots,expected_bindings=expected),lambda results:self.extract_done(results,extractor,settings),"解压")

    def start_extraction_cleanup(self, extractors):
        def cleanup_task(stopped,progress):
            errors=[];total=len(extractors)
            for index,extractor in enumerate(extractors,1):
                if stopped():break
                progress(index,total,tr("清理临时解压目录"))
                try:extractor.cleanup_temp()
                except OSError as exc:errors.append(str(exc))
            return errors
        def cleanup_done(errors):
            for error in errors:self.append_log(tr("临时解压目录清理失败：{error}",error=error))
        self.run_task(cleanup_task,cleanup_done,"临时目录清理")

    def extract_done(self, results, extractor:ArchiveExtractor, task_settings):
        success=0;new_files=[]
        self.archive_source_bindings.update(extractor.source_bindings)
        by_path={ArchiveExtractor.source_key(r.path):r for r in self.records}
        for result in results:
            archive_key=ArchiveExtractor.source_key(result.archive);rec=by_path.get(archive_key)
            if rec:
                rec.archive_status=result.status;rec.archive_format=result.format;rec.archive_encrypted=result.encrypted;rec.archive_file_count=result.file_count;rec.archive_unpacked_size=result.unpacked_size;rec.archive_password_index=result.password_index;rec.archive_output=result.output_dir;rec.archive_depth=getattr(result,"depth",0);rec.reason=result.error or ("；".join(result.warnings))
            if result.status==ArchiveStatus.SUCCESS:
                success+=1;new_files.extend(result.files)
                if result.output_dir and result.output_dir not in self.task_source_roots:self.task_source_roots.append(result.output_dir)
                try:
                    binding=self.archive_source_bindings.get(archive_key)
                    if binding is None:raise ExtractionBlocked("缺少压缩包扫描身份，已拒绝原包后处理")
                    processed=self.handle_extracted_archive(result.archive,binding,task_settings)
                    if rec:
                        rec.selected=False
                        if processed and processed != rec.path:
                            rec.path=processed;rec.name=processed.name
                        rec.status={"keep":"原压缩包已保留（不参与整理）","move":"原压缩包已归档（不参与整理）","trash":"原压缩包已放入回收站"}.get(task_settings.archive_after_extract,"解压完成")
                except (OSError,sqlite3.Error,ExtractionBlocked) as exc:self.append_log(tr("原压缩包后处理失败：{name} - {error}",name=result.archive.name,error=exc))
            else:self.append_log(tr("解压未完成：{name} - {status} {error}",name=result.archive.name,status=tr(result.status.value),error=result.error))
        if new_files and task_settings.rescan_extracted:
            scanner=self.make_scanner();fresh=[]
            for result in results:
                if result.status==ArchiveStatus.SUCCESS and result.output_dir:
                    extracted_records=scanner.records_for_paths(result.files,result.output_dir,task_settings.scan_hidden)
                    for record in extracted_records:record.archive_depth=getattr(result,"depth",0)
                    fresh.extend(extracted_records)
            known={r.path for r in self.records};unique={r.path:r for r in fresh if r.path not in known};fresh=RuleClassifier(self.repository.get_rules()).classify_all(list(unique.values()))
            result_map={ArchiveExtractor.source_key(r.archive):r for r in results}
            for record in fresh:
                nested=result_map.get(ArchiveExtractor.source_key(record.path))
                if nested:
                    record.archive_status=nested.status;record.archive_format=nested.format;record.archive_encrypted=nested.encrypted;record.archive_file_count=nested.file_count;record.archive_unpacked_size=nested.unpacked_size;record.archive_password_index=nested.password_index;record.archive_output=nested.output_dir;record.archive_depth=getattr(nested,"depth",record.archive_depth);record.reason=nested.error or ("；".join(nested.warnings));record.selected=nested.status!=ArchiveStatus.SUCCESS;record.status="嵌套压缩包已处理（不参与整理）" if nested.status==ArchiveStatus.SUCCESS else record.status
            self.records.extend(fresh)
        self.refresh_table();self.append_log(tr("解压完成：成功 {success}/{total}；新增文件 {files}",success=success,total=len(results),files=len(new_files)));self.update_action_availability()

    def handle_extracted_archive(self, archive:Path, binding:ArchiveSourceBinding, task_settings=None) -> Path | None:
        settings=task_settings or self.settings;action=settings.archive_after_extract
        if ArchiveExtractor.source_key(archive)!=ArchiveExtractor.source_key(binding.archive_path):raise ExtractionBlocked("原压缩包路径与扫描身份不一致")
        allowed_root=ArchiveExtractor.validate_source_binding(binding,tuple(self.task_source_roots))
        if action=="move" and archive.exists():
            base=archive.parent/"已解压压缩包";directory=None
            for index in range(10_000):
                candidate=base if index==0 else base.with_name(f"{base.name} ({index})")
                if candidate.exists() and not is_aifo_archive_store(candidate):
                    continue
                ensure_safe_directory(candidate,allowed_root);mark_aifo_archive_store(candidate,allowed_root);directory=candidate;break
            if directory is None:raise OSError("无法创建安全的原压缩包归档目录")
            target=unique_path(directory/archive.name);row_id=None;identity=binding.identity;operation_id=str(uuid.uuid4())
            if settings.history_enabled:
                pending=OperationRecord(operation_id=operation_id,timestamp=datetime.now(),source_path=archive,target_path=target,original_name=archive.name,new_name=target.name,action="archive_move",status="pending")
                row_id=self.repository.begin_operation_item(pending,source_root=allowed_root,target_root=allowed_root,expected_size=identity.size,expected_mtime_ns=identity.mtime_ns,expected_fingerprint=identity.fingerprint)
            ArchiveExtractor.validate_source_binding(binding,(allowed_root,))
            try:move_file_no_overwrite(archive,target,expected_identity=identity)
            except Exception as exc:
                if row_id is not None:
                    try:self.repository.set_operation_item_status_by_id(row_id,"failed",str(exc))
                    except sqlite3.Error:pass
                raise
            if row_id is not None:
                try:self.repository.update_operation_item(row_id,status="success",target_path=target,new_name=target.name,error="")
                except sqlite3.Error as exc:self.append_log(tr("原压缩包已移动，但历史确认将在下次启动恢复：{error}",error=exc))
            self.archive_source_bindings.pop(ArchiveExtractor.source_key(archive),None)
            try:self.archive_source_bindings[ArchiveExtractor.source_key(target)]=ArchiveExtractor.capture_source_binding(target,allowed_root)
            except (OSError,ExtractionBlocked):pass
            self.append_log(tr("原压缩包已移动：{name}",name=archive.name));return target
        elif action=="trash" and archive.exists():
            from send2trash import send2trash
            identity=binding.identity;operation_id=str(uuid.uuid4());row_id=None
            if settings.history_enabled:
                pending=OperationRecord(operation_id=operation_id,timestamp=datetime.now(),source_path=archive,target_path=archive,original_name=archive.name,new_name=archive.name,action="archive_trash",status="pending")
                row_id=self.repository.begin_operation_item(pending,source_root=allowed_root,target_root=allowed_root,expected_size=identity.size,expected_mtime_ns=identity.mtime_ns,expected_fingerprint=identity.fingerprint)
            ArchiveExtractor.validate_source_binding(binding,(allowed_root,))
            try:send2trash(str(archive))
            except Exception as exc:
                if row_id is not None:
                    try:self.repository.set_operation_item_status_by_id(row_id,"failed",str(exc))
                    except sqlite3.Error:pass
                raise OSError(str(exc)) from exc
            if row_id is not None:
                try:self.repository.set_operation_item_status_by_id(row_id,"trashed","已放入系统回收站，应用内不自动撤销")
                except sqlite3.Error as exc:self.append_log(tr("原压缩包已进入回收站，但历史确认失败：{error}",error=exc))
            self.archive_source_bindings.pop(ArchiveExtractor.source_key(archive),None)
            self.append_log(tr("原压缩包已放入回收站：{name}",name=archive.name));return None
        return archive

    def start_ai(self):
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self,tr("任务进行中"),tr("请先停止或等待当前任务完成。"));return
        settings=self.repository.load_settings();key=get_api_key(settings.api_base_url);pending=[r for r in self.records if r.category=="待确认" and r.selected and r.archive_status in (ArchiveStatus.NONE,ArchiveStatus.SUCCESS)]
        if not key:
            if QMessageBox.question(self,tr("需要 API 配置"),tr("尚未配置 API Key。规则分类仍可正常使用。\n是否现在打开 API 配置？"))==QMessageBox.Yes:self.open_api_settings()
            return
        if not pending:QMessageBox.information(self,tr("AI 分析"),tr("没有需要 AI 判断的文件。"));return
        client=AIClient(settings,key)
        self.active_ai_client=client
        def done(records):
            cost=client.estimated_cost if (settings.input_cost_per_million or settings.output_cost_per_million) else None
            self.repository.record_usage(len(records),client.input_tokens if client.usage_known else None,client.output_tokens if client.usage_known else None,cost);self.refresh_table();tokens=f"Input {client.input_tokens} / Output {client.output_tokens}" if client.usage_known else tr("Token 使用量未知");cost_text=f"{cost:.6f}" if cost is not None else (tr("未知（API 未返回 Token）") if not client.usage_known else tr("未配置费率"));self.append_log(tr("AI 已分析：{count} 个；{tokens}；Estimated Cost {cost}",count=len(records),tokens=tokens,cost=cost_text))
        self.run_task(lambda stopped,progress:client.analyze_many(pending,stopped,progress),done,"AI 分析")

    def refresh_table(self):
        self.table.blockSignals(True);self.table.setSortingEnabled(False);self.table.setRowCount(len(self.records))
        categories={}
        try:tokens=self.material_manager.get_pack(self.settings.material_pack).manifest.colors
        except MaterialPackError:tokens=self.material_manager.get_pack("default").manifest.colors
        for row,r in enumerate(self.records):
            values=["",r.name,r.suffix or r.mime_type,str(r.path),r.category,str(r.target_path or ""),f"{r.confidence:.0%}",tr("移动分类"),tr("启用") if self.rename_box.isChecked() else tr("关闭"),tr(r.status),tr(r.archive_status.value)]
            for col,value in enumerate(values):
                item=QTableWidgetItem(value);item.setData(Qt.UserRole,row)
                if col in (COL_PATH,COL_TARGET):item.setToolTip(value)
                if col==COL_CHECK:item.setFlags((item.flags()|Qt.ItemIsUserCheckable)&~Qt.ItemIsEditable);item.setCheckState(Qt.Checked if r.selected else Qt.Unchecked)
                elif col not in (COL_CATEGORY,):item.setFlags(item.flags()&~Qt.ItemIsEditable)
                if col==COL_CONF:
                    colour=QColor(tokens.danger if r.confidence<self.settings.low_confidence else tokens.warning if r.confidence<self.settings.high_confidence else tokens.success);colour.setAlpha(55);item.setBackground(colour)
                self.table.setItem(row,col,item)
            categories[r.category]=categories.get(r.category,0)+1
        self.table.setSortingEnabled(True);self.table.blockSignals(False);self.categories.clear()
        for category,count in sorted(categories.items()):self.categories.addItem(f"{category} ({count})")
        self.apply_filter();self.update_action_availability()

    def rename_toggled(self,enabled):
        self.settings=self.repository.load_settings()
        if enabled and not self.settings.allow_rename:
            QMessageBox.information(self,tr("重命名已禁用"),tr("请先在“重命名选项”或设置页允许重命名。"))
            self.rename_box.blockSignals(True);self.rename_box.setChecked(False);self.rename_box.blockSignals(False);return
        self.refresh_table()

    def record_for_row(self,row:int):
        item=self.table.item(row,COL_NAME);index=item.data(Qt.UserRole) if item else None
        return self.records[index] if isinstance(index,int) and index<len(self.records) else None

    def item_changed(self,item):
        rec=self.record_for_row(item.row())
        if rec and item.column()==COL_CHECK:rec.selected=item.checkState()==Qt.Checked
        elif rec and item.column()==COL_CATEGORY and item.text()!=rec.category:self.set_manual_category(rec,item.text());QTimer.singleShot(0,self.maybe_suggest_rule)

    def cell_double_clicked(self,row,col):
        if col!=COL_CATEGORY:return
        rec=self.record_for_row(row);categories=sorted({r.category for r in self.records if r.category!="待确认"})
        value,ok=QInputDialog.getItem(self,tr("手动分类"),tr("{name} 的分类：",name=rec.name),categories,editable=True)
        if ok and value:self.set_manual_category(rec,value);self.refresh_table();self.maybe_suggest_rule()

    def set_manual_category(self,rec,value):
        rec.category=value.strip() or "待确认";rec.confidence=1;rec.source="手动";rec.reason="用户手动选择";self.repository.record_manual_choice(rec.name,rec.prefix,rec.category)

    def maybe_suggest_rule(self):
        suggestion=self.repository.learning_suggestion()
        if not suggestion:return
        prefix,category,count=suggestion
        if any(r.rule_type==RuleType.PREFIX and r.pattern.lower()==prefix.lower() for r in self.repository.get_rules()):return
        answer=QMessageBox.question(self,tr("规则学习"),tr("发现你已将 {count} 个不同文件（{prefix} 开头）分类到“{category}”。\n是否创建规则？\n{prefix} -> {category}",count=count,prefix=prefix,category=category))
        if answer==QMessageBox.Yes:self.repository.save_rule(ClassificationRule(pattern=prefix,category=category,priority=100));self.append_log(tr("已按用户确认创建规则：{prefix} -> {category}",prefix=prefix,category=category))
        else:self.repository.dismiss_learning_suggestion(prefix,category);self.append_log(tr("已忽略规则建议：{prefix} -> {category}",prefix=prefix,category=category))

    def apply_filter(self,*_):
        query=self.search.text().lower();mode=self.filter_box.currentData() or "全部"
        for row in range(self.table.rowCount()):
            rec=self.record_for_row(row);match=not query or query in rec.name.lower() or query in str(rec.path).lower()
            if mode=="待确认":match&=rec.category=="待确认"
            elif mode=="规则命中":match&="规则" in rec.source
            elif mode=="AI":match&=rec.source=="AI"
            elif mode=="压缩包":match&=compound_suffix(rec.path) in ARCHIVE_SUFFIXES
            self.table.setRowHidden(row,not match)

    def filter_category(self,item_text):
        category=item_text.rsplit(" (",1)[0]
        for row in range(self.table.rowCount()):self.table.setRowHidden(row,self.record_for_row(row).category!=category)

    def show_details(self):
        row=self.table.currentRow();rec=self.record_for_row(row)
        if not rec:return
        self.preview.clear()
        if rec.mime_type.startswith("image/"):
            try:
                if rec.path.stat().st_size > 50 * 1024**2:
                    raise ValueError(tr("图片超过 50 MB，已跳过预览"))
                QImageReader.setAllocationLimit(128)
                reader=QImageReader(str(rec.path));size=reader.size()
                if not size.isValid() or size.width()*size.height() > 100_000_000:
                    raise ValueError(tr("图片像素尺寸异常，已跳过预览"))
                size.scale(QSize(300,220),Qt.KeepAspectRatio);reader.setScaledSize(size);image=reader.read();pix=QPixmap.fromImage(image)
                self.preview.setPixmap(pix) if not pix.isNull() else self.preview.setText(tr("图片预览不可用"))
            except (OSError,ValueError) as exc:self.preview.setText(str(exc))
        else:
            try:
                if rec.suffix.lower()==".pdf":self.preview.setText(tr("PDF 文本会在后台 AI 分析时有限提取；详情区不在界面线程解析 PDF。"))
                else:text=extract_limited_text(rec.path,2000);self.preview.setText(text or tr("此类型无文本预览"))
            except Exception as exc:self.preview.setText(tr("预览不可用：{error}",error=exc))
        detail_lines=[
            tr("原始信息"),
            tr("文件：{value}",value=rec.name), tr("路径：{value}",value=rec.path),
            tr("大小：{value} 字节",value=f"{rec.size:,}"), tr("MIME：{value}",value=rec.mime_type),
            tr("创建：{value}",value=rec.created_at), tr("修改：{value}",value=rec.modified_at), "",
            tr("分类判断"), tr("类别：{value}",value=rec.category), tr("子类：{value}",value=rec.subcategory or "-"),
            tr("来源：{value}",value=tr(rec.source)), tr("置信度：{value}",value=f"{rec.confidence:.0%}"),
            tr("理由：{value}",value=rec.reason or "-"), tr("建议名称：{value}",value=rec.suggested_name or "-"),
            tr("目标：{value}",value=rec.target_path or "-"), "", tr("压缩信息"),
            tr("格式：{value}",value=rec.archive_format or "-"), tr("状态：{value}",value=tr(rec.archive_status.value)),
            tr("加密：{value}",value=rec.archive_encrypted if rec.archive_encrypted is not None else "-"),
            tr("内部文件：{value}",value=rec.archive_file_count if rec.archive_file_count is not None else "-"),
            tr("预计大小：{value}",value=rec.archive_unpacked_size if rec.archive_unpacked_size is not None else "-"),
            tr("密码序号：{value}",value=rec.archive_password_index if rec.archive_password_index is not None else "-"),
            tr("解压目录：{value}",value=rec.archive_output or "-"), tr("递归层级：{value}",value=rec.archive_depth),
        ]
        self.details.setPlainText("\n".join(detail_lines))

    def build_plan(self):
        if not self.task_root:return []
        return Organizer(self.repository,self.repository.load_settings()).build_plan(self.records,self.task_root,self.rename_box.isChecked(),self.task_source_roots)

    def preview_dialog(self,plan,title="整理预览"):
        dialog=QDialog(self);dialog.setWindowTitle(tr(title));dialog.resize(1000,600);layout=QVBoxLayout(dialog);table=QTableWidget(len(plan),3);table.setHorizontalHeaderLabels([tr("执行"),tr("源路径"),tr("目标路径")]);table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch);table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
        for row,(rec,target) in enumerate(plan):
            check=QTableWidgetItem();check.setFlags(check.flags()|Qt.ItemIsUserCheckable);check.setCheckState(Qt.Checked);table.setItem(row,0,check);table.setItem(row,1,QTableWidgetItem(str(rec.path)));table.setItem(row,2,QTableWidgetItem(str(target)))
        layout.addWidget(table);buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()!=QDialog.Accepted:return []
        return [plan[row] for row in range(len(plan)) if table.item(row,0).checkState()==Qt.Checked]

    def preview_organize(self):
        plan=self.build_plan()
        if not plan:QMessageBox.information(self,tr("预览"),tr("没有可整理的已确认文件。"));return
        self.preview_dialog(plan)

    def execute_organize(self):
        plan=self.build_plan()
        if not plan:QMessageBox.information(self,tr("整理"),tr("没有可整理的已确认文件。"));return
        # The per-file preview is a non-negotiable safety boundary, including
        # for databases created by older versions with confirmation disabled.
        plan=self.preview_dialog(plan)
        if not plan:return
        organizer=Organizer(self.repository,self.repository.load_settings())
        self.run_task(lambda stopped,progress:organizer.execute(plan,stopped,progress,root=self.task_root,source_roots=self.task_source_roots),self.organize_done,"执行整理")

    def organize_done(self,result):
        _,history=result;success=sum(r.status=="success" for r in history);self.refresh_table();self.append_log(tr("整理完成：成功 {success}/{total}，失败不会中断其他文件",success=success,total=len(history)))

    def undo_last(self):
        settings=self.repository.load_settings()
        if not settings.history_enabled or not settings.undo_enabled:QMessageBox.information(self,tr("撤销"),tr("操作历史或撤销功能已在设置中关闭。"));return
        organizer=Organizer(self.repository,settings);preview=organizer.undo_preview()
        if not preview:QMessageBox.information(self,tr("撤销"),tr("没有可撤销的成功操作。"));return
        pairs=[(FileRecord(path=s,name=s.name,created_at=datetime.now(),modified_at=datetime.now()),t) for s,t in preview]
        selected=self.preview_dialog(pairs,"撤销预览")
        if not selected:return
        selected_targets={rec.path for rec,_ in selected}
        def done(result):
            restored,errors=result
            for preview_record,source_path in selected:
                if not source_path.exists() or preview_record.path.exists():continue
                for record in self.records:
                    if record.path.resolve()==preview_record.path.resolve():
                        record.path=source_path;record.name=source_path.name;record.suffix=compound_suffix(source_path);record.target_path=None;record.status="已撤销"
                        try:
                            stat=source_path.stat();record.size=stat.st_size;record.modified_at=datetime.fromtimestamp(stat.st_mtime)
                        except OSError:pass
                        break
            self.refresh_table();self.append_log(tr("撤销完成：恢复 {restored} 个，失败 {failed} 个",restored=restored,failed=len(errors)));QMessageBox.information(self,tr("撤销"),tr("已恢复 {count} 个文件。",count=restored)+("\n"+"\n".join(errors[:5]) if errors else ""))
        self.run_task(lambda stopped,progress:organizer.undo_last(selected_targets,stopped,progress),done,"撤销")

    def archive_menu(self,position):
        rec=self.record_for_row(self.table.rowAt(position.y()))
        if not rec or compound_suffix(rec.path) not in ARCHIVE_SUFFIXES:return
        menu=QMenu(self);now=menu.addAction(tr("立即解压"));specified=menu.addAction(tr("使用指定密码解压"));retry=menu.addAction(tr("更换密码重试"));skip=menu.addAction(tr("跳过此压缩包"));open_dir=menu.addAction(tr("打开解压目录"))
        action=menu.exec(self.table.viewport().mapToGlobal(position))
        if action==now:self.start_extract([rec.path])
        elif action in (specified,retry):
            password,save=self.prompt_archive_password()
            if password:
                if save:self.password_store.add(password,f"为 {rec.name} 添加")
                self.start_extract([rec.path],password)
        elif action==skip:rec.archive_status=ArchiveStatus.NONE;rec.status="已跳过解压";self.refresh_table()
        elif action==open_dir and rec.archive_output:QDesktopServices.openUrl(QUrl.fromLocalFile(str(rec.archive_output)))

    def prompt_archive_password(self):
        dialog=QDialog(self);dialog.setWindowTitle(tr("输入解压密码"));layout=QVBoxLayout(dialog);layout.addWidget(QLabel(tr("该压缩包无法使用现有密码打开。请输入新的密码：")));edit=QLineEdit();edit.setEchoMode(QLineEdit.Password);layout.addWidget(edit);save=QCheckBox(tr("保存到密码库（不勾选则仅本次使用）"));layout.addWidget(save);buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);translate_widget_tree(dialog)
        return (edit.text(),save.isChecked()) if dialog.exec()==QDialog.Accepted else ("",False)

    def open_rules(self):
        RuleManagerDialog(self.repository,self).exec()

    def open_rename_options(self):
        dialog=RenameOptionsDialog(self.repository,self)
        if dialog.exec()==QDialog.Accepted:self.settings=self.repository.load_settings();self.append_log(tr("重命名模板已更新；重命名仍需单独勾选才会执行"))

    def open_settings(self):
        dialog=SettingsDialog(self.repository,self.password_store,self,material_manager=self.material_manager)
        result=dialog.exec()
        if result==QDialog.Accepted:self.apply_saved_interface_settings();self.update_action_availability();self.append_log(tr("设置已更新"))
        elif dialog.materials_changed:self.apply_saved_interface_settings()

    def open_api_settings(self):
        dialog=SettingsDialog(self.repository,self.password_store,self,initial_tab=0,material_manager=self.material_manager);dialog.setWindowTitle(tr("API 配置"))
        result=dialog.exec()
        if result==QDialog.Accepted:self.apply_saved_interface_settings();self.append_log(tr("API 配置已更新"))
        elif dialog.materials_changed:self.apply_saved_interface_settings()

    def update_api_status(self):
        settings=self.repository.load_settings();key=bool(get_api_key(settings.api_base_url))
        if key:
            storage=tr("系统凭据") if secure_backend_available() else tr("仅本次运行")
            self.api_status.setText(tr("API：已配置 · {model} · Key：{storage}",model=settings.api_model,storage=storage));self.api_status.setProperty("status","success")
        else:
            self.api_status.setText(tr("API：未配置 · 当前使用规则分类模式"));self.api_status.setProperty("status","warning")
        self.api_status.setStyleSheet("");self.api_status.style().unpolish(self.api_status);self.api_status.style().polish(self.api_status)

    def closeEvent(self,event):
        if self.thread:
            event.ignore();self._close_pending=True
            if self.worker:self.worker.cancel()
            if self.active_ai_client:self.active_ai_client.cancel()
            self.next_task=None;self.setEnabled(False);self.statusBar().showMessage(tr("正在安全停止后台任务，完成后将自动关闭…"))
            self.append_log(tr("正在安全停止后台任务，完成后关闭应用"))
            return
        if self._extractors:
            event.ignore();self._close_pending=True;self.setEnabled(False)
            extractors,self._extractors=self._extractors,[];self.start_extraction_cleanup(extractors);return
        event.accept()
