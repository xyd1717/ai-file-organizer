"""Small, dependency-free runtime translations for the desktop UI.

Chinese is the source language used by the application.  Keeping source strings
as translation keys makes adoption incremental: a missed key remains readable in
Chinese instead of producing an empty label or an exception.
"""

from __future__ import annotations

from threading import RLock
from typing import Any, Final


DEFAULT_LANGUAGE: Final = "zh_CN"
LANGUAGE_NAMES: Final[dict[str, str]] = {
    "zh_CN": "简体中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
}
SUPPORTED_LANGUAGES: Final[tuple[str, ...]] = tuple(LANGUAGE_NAMES)

_ALIASES: Final[dict[str, str]] = {
    "zh": "zh_CN",
    "zh-cn": "zh_CN",
    "zh_cn": "zh_CN",
    "cn": "zh_CN",
    "en-us": "en",
    "en_us": "en",
    "en-gb": "en",
    "en_gb": "en",
    "jp": "ja",
    "ja-jp": "ja",
    "ja_jp": "ja",
    "kr": "ko",
    "ko-kr": "ko",
    "ko_kr": "ko",
}

# source: (English, Japanese, Korean)
_TEXT: Final[dict[str, tuple[str, str, str]]] = {
    # Main navigation and table
    "设置与规则": ("Settings & Rules", "設定とルール", "설정 및 규칙"),
    "API 配置…": ("API Settings…", "API 設定…", "API 설정…"),
    "分类规则管理器": ("Classification Rule Manager", "分類ルール管理", "분류 규칙 관리자"),
    "设置": ("Settings", "設定", "설정"),
    "语言": ("Language", "言語", "언어"),
    "外观": ("Appearance", "外観", "모양"),
    "帮助": ("Help", "ヘルプ", "도움말"),
    "使用说明": ("User Guide", "使用ガイド", "사용 설명서"),
    "管理材质包…": ("Manage Material Packs…", "マテリアルパックを管理…", "머티리얼 팩 관리…"),
    "当前扫描目录": ("Current scan folder", "現在のスキャンフォルダー", "현재 스캔 폴더"),
    "选择文件夹…": ("Choose Folder…", "フォルダーを選択…", "폴더 선택…"),
    "搜索文件名或路径": ("Search file name or path", "ファイル名またはパスを検索", "파일 이름 또는 경로 검색"),
    "搜索文件": ("Search files", "ファイルを検索", "파일 검색"),
    "文件筛选": ("File filter", "ファイルフィルター", "파일 필터"),
    "全部": ("All", "すべて", "전체"),
    "待确认": ("Needs Review", "要確認", "확인 필요"),
    "规则命中": ("Rule Match", "ルール一致", "규칙 일치"),
    "压缩包": ("Archives", "アーカイブ", "압축 파일"),
    "扫描目录：": ("Scan folder:", "スキャンフォルダー：", "스캔 폴더:"),
    "AI 只处理规则无法判断的文件": (
        "AI only processes files that rules cannot classify",
        "AI はルールで分類できないファイルのみ処理します",
        "AI는 규칙으로 분류할 수 없는 파일만 처리합니다",
    ),
    "API 配置状态": ("API configuration status", "API 設定状態", "API 설정 상태"),
    "文件夹树": ("Folder Tree", "フォルダーツリー", "폴더 트리"),
    "管理分类规则": ("Manage Classification Rules", "分類ルールを管理", "분류 규칙 관리"),
    "分类列表": ("Categories", "カテゴリー", "분류 목록"),
    "文件整理列表": ("File organization list", "ファイル整理一覧", "파일 정리 목록"),
    "勾选": ("Select", "選択", "선택"),
    "原文件名": ("Original Name", "元のファイル名", "원본 파일명"),
    "类型": ("Type", "種類", "유형"),
    "当前路径": ("Current Path", "現在のパス", "현재 경로"),
    "建议分类": ("Suggested Category", "推奨カテゴリー", "추천 분류"),
    "目标路径": ("Target Path", "移動先パス", "대상 경로"),
    "置信度": ("Confidence", "信頼度", "신뢰도"),
    "处理方式": ("Action", "処理方法", "처리 방식"),
    "重命名": ("Rename", "名前変更", "이름 바꾸기"),
    "状态": ("Status", "状態", "상태"),
    "压缩状态": ("Archive Status", "解凍状態", "압축 해제 상태"),
    "选择文件查看预览": ("Select a file to preview", "ファイルを選択してプレビュー", "미리 볼 파일을 선택하세요"),
    "扫描": ("Scan", "スキャン", "스캔"),
    "停止扫描": ("Stop Scan", "スキャン停止", "스캔 중지"),
    "AI 分析": ("AI Analysis", "AI 分析", "AI 분석"),
    "停止分析": ("Stop Analysis", "分析停止", "분석 중지"),
    "预览整理": ("Preview Organization", "整理をプレビュー", "정리 미리보기"),
    "执行整理": ("Organize Files", "整理を実行", "정리 실행"),
    "撤销上次操作": ("Undo Last Operation", "前回の操作を元に戻す", "마지막 작업 실행 취소"),
    "停止解压": ("Stop Extraction", "解凍停止", "압축 해제 중지"),
    "启用重命名（可选）": ("Enable Rename (Optional)", "名前変更を有効化（任意）", "이름 바꾸기 사용(선택)"),
    "重命名选项…": ("Rename Options…", "名前変更オプション…", "이름 바꾸기 옵션…"),
    "任务进度": ("Task Progress", "タスク進捗", "작업 진행률"),
    "运行日志": ("Activity Log", "実行ログ", "실행 로그"),

    # Common dialogs and messages
    "选择要扫描的目录": ("Choose a folder to scan", "スキャンするフォルダーを選択", "스캔할 폴더 선택"),
    "任务进行中": ("Task in Progress", "タスク実行中", "작업 진행 중"),
    "当前任务结束或停止后才能切换扫描目录。": (
        "You can change the scan folder after the current task finishes or stops.",
        "現在のタスクが完了または停止してからスキャンフォルダーを変更できます。",
        "현재 작업이 완료되거나 중지된 후 스캔 폴더를 변경할 수 있습니다.",
    ),
    "请先停止或等待当前任务完成。": (
        "Stop the current task or wait for it to finish.",
        "現在のタスクを停止するか、完了するまでお待ちください。",
        "현재 작업을 중지하거나 완료될 때까지 기다리세요.",
    ),
    "安全拦截": ("Security Block", "セキュリティブロック", "보안 차단"),
    "系统目录和程序安装目录不能作为整理范围。": (
        "System and application installation folders cannot be organized.",
        "システムおよびアプリのインストールフォルダーは整理対象にできません。",
        "시스템 및 앱 설치 폴더는 정리 대상으로 사용할 수 없습니다.",
    ),
    "请先选择文件夹": ("Choose a folder first.", "先にフォルダーを選択してください。", "먼저 폴더를 선택하세요."),
    "已请求安全停止当前任务": ("A safe stop was requested", "タスクの安全な停止を要求しました", "현재 작업의 안전 중지를 요청했습니다"),
    "进度 {current}/{total}{detail}": ("Progress {current}/{total}{detail}", "進捗 {current}/{total}{detail}", "진행률 {current}/{total}{detail}"),
    "应用已启动；无 API Key 时仍可使用规则分类": (
        "Application started; rule-based classification works without an API key",
        "アプリを起動しました。API キーがなくてもルール分類を利用できます",
        "앱이 시작되었습니다. API 키 없이도 규칙 분류를 사용할 수 있습니다",
    ),
    "界面语言已切换为：{language}": (
        "Interface language changed to: {language}",
        "表示言語を切り替えました：{language}",
        "인터페이스 언어 변경: {language}",
    ),
    "界面材质已切换为：{material}": (
        "Material pack changed to: {material}",
        "マテリアルパックを切り替えました：{material}",
        "머티리얼 팩 변경: {material}",
    ),
    "材质包加载失败，已恢复默认材质：{error}": (
        "Material pack failed to load; the default was restored: {error}",
        "マテリアルパックを読み込めなかったため既定に戻しました：{error}",
        "머티리얼 팩을 불러오지 못해 기본값으로 복원했습니다: {error}",
    ),
    "材质包": ("Material Pack", "マテリアルパック", "머티리얼 팩"),
    "无法应用材质包：{error}": (
        "Could not apply the material pack: {error}",
        "マテリアルパックを適用できません：{error}",
        "머티리얼 팩을 적용할 수 없습니다: {error}",
    ),
    "默认": ("Default", "デフォルト", "기본"),
    "Windows 黑白": ("Windows Black & White", "Windows 白黒", "Windows 흑백"),
    "使用原生 Windows 黑白系统控件，不附加自定义界面样式。": (
        "Uses native Windows black-and-white system controls without a custom stylesheet.",
        "カスタムスタイルを追加せず、Windows 標準の白黒システムコントロールを使用します。",
        "사용자 지정 스타일 없이 Windows 기본 흑백 시스템 컨트롤을 사용합니다.",
    ),
    "深色": ("Dark", "ダーク", "다크"),
    "海洋": ("Ocean", "オーシャン", "오션"),
    "暖色": ("Warm", "ウォーム", "웜"),
    "明亮、清晰的默认材质。": ("A bright, clear default material.", "明るく見やすい既定のマテリアルです。", "밝고 선명한 기본 머티리얼입니다."),
    "适合低光环境的深色材质。": ("A dark material for low-light environments.", "暗い環境に適したダークマテリアルです。", "어두운 환경에 적합한 다크 머티리얼입니다."),
    "冷静的海蓝色材质。": ("A calm ocean-blue material.", "落ち着いた海の青を基調にしたマテリアルです。", "차분한 바다색 머티리얼입니다."),
    "柔和的暖色纸张质感。": ("A soft, warm paper-like material.", "柔らかな暖色の紙調マテリアルです。", "부드럽고 따뜻한 종이 질감 머티리얼입니다."),
    "{label}开始": ("{label} started", "{label}を開始しました", "{label} 시작"),
    "{label}失败：{error}": ("{label} failed: {error}", "{label}に失敗：{error}", "{label} 실패: {error}"),
    "未知错误": ("Unknown error", "不明なエラー", "알 수 없는 오류"),
    "安全拦截：禁止选择系统目录 {folder}": (
        "Security block: system folder cannot be selected: {folder}",
        "セキュリティブロック：システムフォルダーは選択できません：{folder}",
        "보안 차단: 시스템 폴더를 선택할 수 없습니다: {folder}",
    ),
    "安全拦截：{message}": ("Security block: {message}", "セキュリティブロック：{message}", "보안 차단: {message}"),
    "递归查找压缩包：{name}": (
        "Searching subfolders for archives: {name}",
        "サブフォルダーのアーカイブを検索：{name}",
        "하위 폴더에서 압축 파일 검색: {name}",
    ),
    "自动解压已在全部子目录中发现 {count} 个压缩包": (
        "Automatic extraction found {count} archives across all subfolders",
        "自動解凍：すべてのサブフォルダーから {count} 件のアーカイブを検出しました",
        "자동 압축 해제에서 모든 하위 폴더의 압축 파일 {count}개를 찾았습니다",
    ),
    "扫描完成：{count} 个文件；规则直接处理：{matched}；需要 AI：{ai}": (
        "Scan complete: {count} files; {matched} handled by rules; {ai} need AI",
        "スキャン完了：{count} 件、ルール処理 {matched} 件、AI 処理 {ai} 件",
        "스캔 완료: {count}개, 규칙 처리 {matched}개, AI 필요 {ai}개",
    ),
    "扫描已停止；保留已扫描结果，不继续自动解压": (
        "Scan stopped; scanned results were kept and automatic extraction will not continue",
        "スキャンを停止しました。結果は保持され、自動解凍は続行しません",
        "스캔이 중지되었습니다. 결과는 유지되며 자동 압축 해제는 계속하지 않습니다",
    ),
    "统一解压目录不能位于系统目录或应用自身目录。请在设置中选择普通用户目录。": (
        "The shared extraction folder cannot be inside a system or application folder. Choose a regular user folder in Settings.",
        "共通の解凍先にシステムまたはアプリのフォルダーは指定できません。設定で通常のユーザーフォルダーを選択してください。",
        "통합 압축 해제 폴더는 시스템 또는 앱 폴더 안에 둘 수 없습니다. 설정에서 일반 사용자 폴더를 선택하세요.",
    ),
    "临时解压目录清理失败：{error}": (
        "Could not clean temporary extraction folder: {error}",
        "一時解凍フォルダーの削除に失敗しました：{error}",
        "임시 압축 해제 폴더 정리 실패: {error}",
    ),
    "临时目录清理": ("Temporary Folder Cleanup", "一時フォルダーのクリーンアップ", "임시 폴더 정리"),
    "清理临时解压目录": ("Cleaning temporary extraction folders", "一時解凍フォルダーを整理中", "임시 압축 해제 폴더 정리 중"),
    "解压完成": ("Extraction Complete", "解凍完了", "압축 해제 완료"),
    "解压完成：成功 {success}；新增文件 {files}": (
        "Extraction complete: {success} succeeded; {files} files added",
        "解凍完了：{success} 件成功、新規ファイル {files} 件",
        "압축 해제 완료: {success}개 성공, 새 파일 {files}개",
    ),
    "解压完成：成功 {success}/{total}；新增文件 {files}": (
        "Extraction complete: {success}/{total} succeeded; {files} files added",
        "解凍完了：{success}/{total} 件成功、新規ファイル {files} 件",
        "압축 해제 완료: {success}/{total}개 성공, 새 파일 {files}개",
    ),
    "解压未完成：{name} - {status} {error}": (
        "Extraction incomplete: {name} - {status} {error}",
        "解凍未完了：{name} - {status} {error}",
        "압축 해제 미완료: {name} - {status} {error}",
    ),
    "原压缩包后处理失败：{name} - {error}": (
        "Archive post-processing failed: {name} - {error}",
        "元アーカイブの後処理に失敗：{name} - {error}",
        "원본 압축 파일 후처리 실패: {name} - {error}",
    ),
    "原压缩包已移动，但历史确认将在下次启动恢复：{error}": (
        "The archive was moved; history confirmation will be recovered next launch: {error}",
        "元アーカイブは移動済みです。履歴確認は次回起動時に復元されます：{error}",
        "원본 압축 파일이 이동되었으며 기록 확인은 다음 실행 시 복구됩니다: {error}",
    ),
    "原压缩包已移动：{name}": ("Original archive moved: {name}", "元アーカイブを移動しました：{name}", "원본 압축 파일 이동됨: {name}"),
    "原压缩包已进入回收站，但历史确认失败：{error}": (
        "The archive is in the Recycle Bin, but history confirmation failed: {error}",
        "元アーカイブはごみ箱に入りましたが、履歴確認に失敗しました：{error}",
        "원본 압축 파일이 휴지통으로 이동했지만 기록 확인에 실패했습니다: {error}",
    ),
    "原压缩包已放入回收站：{name}": ("Original archive moved to the Recycle Bin: {name}", "元アーカイブをごみ箱へ移動しました：{name}", "원본 압축 파일을 휴지통으로 이동함: {name}"),
    "尚未配置 API Key。规则分类仍可正常使用。\n是否现在打开 API 配置？": (
        "No API key is configured. Rule-based classification remains available.\nOpen API settings now?",
        "API キーが設定されていません。ルール分類は引き続き利用できます。\nAPI 設定を開きますか？",
        "API 키가 설정되지 않았습니다. 규칙 분류는 계속 사용할 수 있습니다.\n지금 API 설정을 여시겠습니까?",
    ),
    "需要 API 配置": ("API Setup Required", "API 設定が必要です", "API 설정 필요"),
    "没有需要 AI 判断的文件。": ("No files need AI classification.", "AI 分類が必要なファイルはありません。", "AI 분류가 필요한 파일이 없습니다."),
    "Token 使用量未知": ("Token usage unknown", "トークン使用量：不明", "토큰 사용량 알 수 없음"),
    "未知（API 未返回 Token）": ("Unknown (API returned no token usage)", "不明（API がトークン数を返しませんでした）", "알 수 없음(API가 토큰 사용량을 반환하지 않음)"),
    "未配置费率": ("Rates not configured", "料金未設定", "요금 미설정"),
    "AI 已分析：{count} 个；{tokens}；Estimated Cost {cost}": (
        "AI analyzed {count} files; {tokens}; Estimated Cost {cost}",
        "AI 分析：{count} 件、{tokens}、推定コスト {cost}",
        "AI 분석: {count}개, {tokens}, 예상 비용 {cost}",
    ),
    "重命名已禁用": ("Rename Disabled", "名前変更は無効です", "이름 바꾸기 비활성화됨"),
    "请先在“重命名选项”或设置页允许重命名。": (
        "Enable renaming in Rename Options or Settings first.",
        "名前変更オプションまたは設定で名前変更を有効にしてください。",
        "이름 바꾸기 옵션 또는 설정에서 이름 바꾸기를 먼저 허용하세요.",
    ),
    "手动分类": ("Manual Classification", "手動分類", "수동 분류"),
    "用户手动选择": ("Selected manually", "ユーザーが手動選択", "사용자가 수동으로 선택함"),
    "规则学习": ("Rule Learning", "ルール学習", "규칙 학습"),
    "{name} 的分类：": ("Category for {name}:", "{name} のカテゴリー：", "{name}의 분류:"),
    "发现你已将 {count} 个不同文件（{prefix} 开头）分类到“{category}”。\n是否创建规则？\n{prefix} -> {category}": (
        "You classified {count} different files beginning with {prefix} as “{category}”.\nCreate this rule?\n{prefix} -> {category}",
        "{prefix} で始まる {count} 個の異なるファイルを「{category}」に分類しています。\nこのルールを作成しますか？\n{prefix} -> {category}",
        "{prefix}(으)로 시작하는 서로 다른 파일 {count}개를 ‘{category}’로 분류했습니다.\n이 규칙을 만드시겠습니까?\n{prefix} -> {category}",
    ),
    "已按用户确认创建规则：{prefix} -> {category}": (
        "Rule created after confirmation: {prefix} -> {category}",
        "確認後にルールを作成しました：{prefix} -> {category}",
        "확인 후 규칙 생성: {prefix} -> {category}",
    ),
    "已忽略规则建议：{prefix} -> {category}": (
        "Rule suggestion dismissed: {prefix} -> {category}",
        "ルール提案を無視しました：{prefix} -> {category}",
        "규칙 제안 무시: {prefix} -> {category}",
    ),
    "图片超过 50 MB，已跳过预览": ("Image exceeds 50 MB; preview skipped", "画像が 50 MB を超えるためプレビューを省略しました", "이미지가 50MB를 초과하여 미리보기를 건너뜁니다"),
    "图片像素尺寸异常，已跳过预览": ("Unusual image dimensions; preview skipped", "画像サイズが異常なためプレビューを省略しました", "이미지 크기가 비정상적이어서 미리보기를 건너뜁니다"),
    "图片预览不可用": ("Image preview unavailable", "画像プレビューを利用できません", "이미지 미리보기를 사용할 수 없음"),
    "预览不可用：{error}": ("Preview unavailable: {error}", "プレビューを利用できません：{error}", "미리보기를 사용할 수 없음: {error}"),
    "PDF 文本会在后台 AI 分析时有限提取；详情区不在界面线程解析 PDF。": (
        "Limited PDF text is extracted during background AI analysis; PDFs are not parsed on the UI thread.",
        "PDF テキストはバックグラウンドの AI 分析時に一部抽出されます。画面スレッドでは解析しません。",
        "PDF 텍스트는 백그라운드 AI 분석 중 제한적으로 추출되며 UI 스레드에서는 분석하지 않습니다.",
    ),
    "此类型无文本预览": ("No text preview for this file type", "この種類はテキストプレビューに対応していません", "이 파일 유형은 텍스트 미리보기를 지원하지 않습니다"),
    "原始信息": ("Original Information", "元の情報", "원본 정보"),
    "分类判断": ("Classification", "分類判定", "분류 판단"),
    "压缩信息": ("Archive Information", "アーカイブ情報", "압축 정보"),
    "文件：{value}": ("File: {value}", "ファイル：{value}", "파일: {value}"),
    "路径：{value}": ("Path: {value}", "パス：{value}", "경로: {value}"),
    "大小：{value} 字节": ("Size: {value} bytes", "サイズ：{value} バイト", "크기: {value}바이트"),
    "MIME：{value}": ("MIME: {value}", "MIME：{value}", "MIME: {value}"),
    "创建：{value}": ("Created: {value}", "作成日時：{value}", "생성: {value}"),
    "修改：{value}": ("Modified: {value}", "更新日時：{value}", "수정: {value}"),
    "类别：{value}": ("Category: {value}", "カテゴリー：{value}", "분류: {value}"),
    "子类：{value}": ("Subcategory: {value}", "サブカテゴリー：{value}", "하위 분류: {value}"),
    "来源：{value}": ("Source: {value}", "判定元：{value}", "출처: {value}"),
    "置信度：{value}": ("Confidence: {value}", "信頼度：{value}", "신뢰도: {value}"),
    "理由：{value}": ("Reason: {value}", "理由：{value}", "이유: {value}"),
    "建议名称：{value}": ("Suggested Name: {value}", "推奨名：{value}", "제안 이름: {value}"),
    "目标：{value}": ("Destination: {value}", "移動先：{value}", "대상: {value}"),
    "格式：{value}": ("Format: {value}", "形式：{value}", "형식: {value}"),
    "状态：{value}": ("Status: {value}", "状態：{value}", "상태: {value}"),
    "加密：{value}": ("Encrypted: {value}", "暗号化：{value}", "암호화: {value}"),
    "内部文件：{value}": ("Files Inside: {value}", "内部ファイル：{value}", "내부 파일: {value}"),
    "预计大小：{value}": ("Estimated Size: {value}", "推定サイズ：{value}", "예상 크기: {value}"),
    "密码序号：{value}": ("Password Number: {value}", "パスワード番号：{value}", "비밀번호 번호: {value}"),
    "解压目录：{value}": ("Extraction Folder: {value}", "解凍先：{value}", "압축 해제 폴더: {value}"),
    "递归层级：{value}": ("Recursion Level: {value}", "再帰レベル：{value}", "재귀 단계: {value}"),
    "整理预览": ("Organization Preview", "整理プレビュー", "정리 미리보기"),
    "源路径": ("Source Path", "元のパス", "원본 경로"),
    "执行": ("Execute", "実行", "실행"),
    "没有可整理的已确认文件。": ("There are no confirmed files to organize.", "整理できる確認済みファイルはありません。", "정리할 확인된 파일이 없습니다."),
    "预览": ("Preview", "プレビュー", "미리보기"),
    "整理": ("Organize", "整理", "정리"),
    "整理完成：成功 {success}，失败不会中断其他文件": (
        "Organization complete: {success} succeeded; failures did not interrupt other files",
        "整理完了：{success} 件成功。失敗しても他のファイルは続行されました",
        "정리 완료: {success}개 성공. 실패해도 다른 파일은 계속 처리되었습니다",
    ),
    "整理完成：成功 {success}/{total}，失败不会中断其他文件": (
        "Organization complete: {success}/{total} succeeded; failures did not interrupt other files",
        "整理完了：{success}/{total} 件成功。失敗しても他のファイルは続行されました",
        "정리 완료: {success}/{total}개 성공. 실패해도 다른 파일은 계속 처리되었습니다",
    ),
    "撤销完成：恢复 {restored} 个，失败 {failed} 个": (
        "Undo complete: {restored} restored, {failed} failed",
        "元に戻す操作完了：{restored} 件復元、{failed} 件失敗",
        "실행 취소 완료: {restored}개 복원, {failed}개 실패",
    ),
    "已恢复 {count} 个文件。": ("Restored {count} files.", "{count} 件のファイルを復元しました。", "파일 {count}개를 복원했습니다."),
    "撤销": ("Undo", "元に戻す", "실행 취소"),
    "操作历史或撤销功能已在设置中关闭。": (
        "Operation history or undo is disabled in Settings.",
        "操作履歴または元に戻す機能が設定で無効です。",
        "설정에서 작업 기록 또는 실행 취소가 비활성화되어 있습니다.",
    ),
    "没有可撤销的成功操作。": ("There is no successful operation to undo.", "元に戻せる成功した操作はありません。", "실행 취소할 성공한 작업이 없습니다."),
    "撤销预览": ("Undo Preview", "元に戻す操作のプレビュー", "실행 취소 미리보기"),
    "已撤销": ("Undone", "元に戻しました", "실행 취소됨"),
    "立即解压": ("Extract Now", "今すぐ解凍", "지금 압축 해제"),
    "使用指定密码解压": ("Extract with Password", "指定パスワードで解凍", "지정 비밀번호로 압축 해제"),
    "更换密码重试": ("Retry with Another Password", "別のパスワードで再試行", "다른 비밀번호로 다시 시도"),
    "跳过此压缩包": ("Skip This Archive", "このアーカイブをスキップ", "이 압축 파일 건너뛰기"),
    "打开解压目录": ("Open Extraction Folder", "解凍先を開く", "압축 해제 폴더 열기"),
    "已跳过解压": ("Extraction skipped", "解凍をスキップしました", "압축 해제를 건너뜀"),
    "输入解压密码": ("Enter Extraction Password", "解凍パスワードを入力", "압축 해제 비밀번호 입력"),
    "该压缩包无法使用现有密码打开。请输入新的密码：": (
        "This archive cannot be opened with the saved passwords. Enter a new password:",
        "保存済みのパスワードでは開けません。新しいパスワードを入力してください：",
        "저장된 비밀번호로 이 압축 파일을 열 수 없습니다. 새 비밀번호를 입력하세요:",
    ),
    "保存到密码库（不勾选则仅本次使用）": (
        "Save to password vault (otherwise use once)",
        "パスワード保管庫に保存（未選択の場合は今回のみ）",
        "비밀번호 저장소에 저장(선택하지 않으면 이번에만 사용)",
    ),
    "重命名模板已更新；重命名仍需单独勾选才会执行": (
        "Rename template updated; renaming still requires its separate checkbox",
        "名前変更テンプレートを更新しました。実行には個別のチェックが必要です",
        "이름 바꾸기 템플릿이 업데이트되었습니다. 실행하려면 별도로 선택해야 합니다",
    ),
    "设置已更新": ("Settings updated", "設定を更新しました", "설정 업데이트됨"),
    "API 配置": ("API Settings", "API 設定", "API 설정"),
    "API 配置已更新": ("API settings updated", "API 設定を更新しました", "API 설정 업데이트됨"),
    "仅本次运行": ("This session only", "今回の実行のみ", "이번 실행에서만"),
    "系统凭据": ("System credential store", "システム資格情報", "시스템 자격 증명"),
    "API：未配置 · 当前使用规则分类模式": (
        "API: not configured · Rule-based classification is active",
        "API：未設定 · ルール分類モードを使用中",
        "API: 미설정 · 규칙 분류 모드 사용 중",
    ),
    "API：已配置 · {model} · Key：{storage}": (
        "API: configured · {model} · Key: {storage}",
        "API：設定済み · {model} · キー：{storage}",
        "API: 설정됨 · {model} · 키: {storage}",
    ),
    "正在安全停止后台任务，完成后将自动关闭…": (
        "Safely stopping background tasks; the app will close automatically…",
        "バックグラウンドタスクを安全に停止中です。完了後に自動で閉じます…",
        "백그라운드 작업을 안전하게 중지 중입니다. 완료 후 자동으로 종료됩니다…",
    ),
    "正在安全停止后台任务，完成后关闭应用": (
        "Safely stopping background tasks; the application will close when finished",
        "バックグラウンドタスクを安全に停止しています。完了後にアプリを閉じます",
        "백그라운드 작업을 안전하게 중지하는 중이며 완료 후 앱이 종료됩니다",
    ),

    # Rule manager and password manager
    "优先级": ("Priority", "優先度", "우선순위"),
    "匹配内容": ("Match Pattern", "一致内容", "일치 내용"),
    "分类": ("Category", "カテゴリー", "분류"),
    "启用": ("Enabled", "有効", "사용"),
    "区分大小写": ("Case Sensitive", "大文字と小文字を区別", "대/소문자 구분"),
    "新增": ("Add", "追加", "추가"),
    "删除": ("Delete", "削除", "삭제"),
    "保存修改": ("Save Changes", "変更を保存", "변경 사항 저장"),
    "上移": ("Move Up", "上へ", "위로"),
    "下移": ("Move Down", "下へ", "아래로"),
    "测试规则": ("Test Rule", "ルールをテスト", "규칙 테스트"),
    "是": ("Yes", "はい", "예"),
    "否": ("No", "いいえ", "아니요"),
    "规则": ("Rule", "ルール", "규칙"),
    "规则已保存": ("Rule saved", "ルールを保存しました", "규칙이 저장되었습니다"),
    "无法保存": ("Could Not Save", "保存できません", "저장할 수 없음"),
    "输入文件名：": ("File name:", "ファイル名：", "파일 이름:"),
    "测试结果": ("Test Result", "テスト結果", "테스트 결과"),
    "匹配成功": ("Match", "一致しました", "일치함"),
    "不匹配": ("No Match", "一致しません", "일치하지 않음"),
    "测试失败": ("Test Failed", "テスト失敗", "테스트 실패"),
    "解压密码管理": ("Extraction Passwords", "解凍パスワード管理", "압축 해제 비밀번호 관리"),
    "密码保存在系统凭据存储中。": ("Passwords are stored in the system credential store.", "パスワードはシステム資格情報に保存されます。", "비밀번호는 시스템 자격 증명 저장소에 저장됩니다."),
    "系统安全凭据存储不可用：新增密码仅在本次运行中有效。": (
        "The secure credential store is unavailable; new passwords last only for this session.",
        "安全な資格情報ストアを利用できません。新しいパスワードは今回のみ有効です。",
        "보안 자격 증명 저장소를 사용할 수 없어 새 비밀번호는 이번 실행에서만 유효합니다.",
    ),
    "密码": ("Password", "パスワード", "비밀번호"),
    "备注": ("Note", "メモ", "메모"),
    "显示密码": ("Show Passwords", "パスワードを表示", "비밀번호 표시"),
    "添加": ("Add", "追加", "추가"),
    "修改": ("Edit", "編集", "수정"),
    "启用/禁用": ("Enable/Disable", "有効／無効", "사용/사용 안 함"),
    "（当前不可用）": ("(currently unavailable)", "（現在利用不可）", "(현재 사용할 수 없음)"),
    "添加密码": ("Add Password", "パスワードを追加", "비밀번호 추가"),
    "密码：": ("Password:", "パスワード：", "비밀번호:"),
    "备注：": ("Note:", "メモ：", "메모:"),
    "修改密码": ("Edit Password", "パスワードを編集", "비밀번호 수정"),
    "新密码（取消则不变）：": ("New password (Cancel to keep current):", "新しいパスワード（キャンセルで変更なし）：", "새 비밀번호(취소하면 변경 안 함):"),

    # Rename dialog
    "重命名选项（独立可选功能）": ("Rename Options (Independent & Optional)", "名前変更オプション（独立した任意機能）", "이름 바꾸기 옵션(독립 선택 기능)"),
    "重命名默认关闭。只有主窗口单独勾选“启用重命名”时，整理过程才会修改文件名。": (
        "Renaming is off by default. Files are renamed only when Enable Rename is checked separately in the main window.",
        "名前変更は既定で無効です。メイン画面で個別に有効化した場合のみファイル名を変更します。",
        "이름 바꾸기는 기본적으로 꺼져 있습니다. 메인 창에서 별도로 활성화한 경우에만 파일명을 변경합니다.",
    ),
    "模板预设": ("Template Preset", "テンプレートプリセット", "템플릿 사전 설정"),
    "模板": ("Template", "テンプレート", "템플릿"),
    "示例": ("Example", "例", "예시"),
    "保存": ("Save", "保存", "저장"),
    "取消": ("Cancel", "キャンセル", "취소"),
    "自定义": ("Custom", "カスタム", "사용자 지정"),
    "日期_分类_原文件名": ("Date_Category_OriginalName", "日付_分類_元のファイル名", "날짜_분류_원본파일명"),
    "分类_AI标题": ("Category_AI-Title", "分類_AIタイトル", "분류_AI제목"),
    "年-月-标题": ("Year-Month-Title", "年-月-タイトル", "연도-월-제목"),
    "模板错误：{error}": ("Template error: {error}", "テンプレートエラー：{error}", "템플릿 오류: {error}"),

    # Settings dialog
    "API 配置只在此界面管理。仅在你主动点击“AI 分析”时才会联网；API Key 按服务地址隔离保存在系统凭据中，不写入 SQLite 或源码。": (
        "API settings are managed only here. The app connects only when you click AI Analysis. API keys are isolated by service address in the system credential store and never written to SQLite or source code.",
        "API 設定はこの画面でのみ管理します。「AI 分析」を押したときだけ接続します。API キーはサービスごとにシステム資格情報へ保存され、SQLite やソースコードには書き込みません。",
        "API 설정은 이 화면에서만 관리합니다. AI 분석을 직접 클릭할 때만 연결하며 API 키는 서비스 주소별로 시스템 자격 증명에 저장되고 SQLite나 소스 코드에 기록되지 않습니다.",
    ),
    "API 厂商预设": ("API Provider Preset", "API プロバイダーのプリセット", "API 공급자 사전 설정"),
    "厂商说明": ("Provider Notes", "プロバイダー情報", "공급자 안내"),
    "打开厂商文档": ("Open Provider Documentation", "プロバイダー文書を開く", "공급자 문서 열기"),
    "自定义（OpenAI 兼容）": ("Custom (OpenAI-compatible)", "カスタム（OpenAI 互換）", "사용자 지정(OpenAI 호환)"),
    "Kimi（月之暗面，中国区）": ("Kimi (Moonshot AI, China)", "Kimi（月之暗面、中国）", "Kimi(Moonshot AI, 중국)"),
    "阿里云百炼（千问，中国区）": ("Alibaba Cloud Model Studio (Qwen, China)", "Alibaba Cloud Model Studio（Qwen、中国）", "Alibaba Cloud Model Studio(Qwen, 중국)"),
    "硅基流动（中国区）": ("SiliconFlow (China)", "SiliconFlow（中国）", "SiliconFlow(중국)"),
    "填写任意 OpenAI-compatible 服务地址和模型名称。": (
        "Enter any OpenAI-compatible service URL and model name.",
        "任意の OpenAI 互換サービス URL とモデル名を入力します。",
        "OpenAI 호환 서비스 URL과 모델 이름을 입력하세요.",
    ),
    "适合通用文件分类；账号可用模型以连接测试结果为准。": (
        "Suitable for general file classification. Available models depend on your account and the connection test.",
        "一般的なファイル分類向けです。利用可能なモデルはアカウントと接続テスト結果によります。",
        "일반 파일 분류에 적합합니다. 사용 가능한 모델은 계정 및 연결 테스트 결과에 따라 다릅니다.",
    ),
    "Flash 更适合低成本批量分类，Pro 更适合复杂内容判断。": (
        "Flash suits low-cost batch classification; Pro suits more complex content decisions.",
        "Flash は低コストの一括分類向け、Pro は複雑な内容判断向けです。",
        "Flash는 저비용 일괄 분류에, Pro는 복잡한 콘텐츠 판단에 적합합니다.",
    ),
    "此预设使用中国区开放平台；中国区与国际区 API Key 不互通。": (
        "This preset uses the China platform; China and international API keys are not interchangeable.",
        "このプリセットは中国向けプラットフォームを使用します。中国版と国際版の API キーは共用できません。",
        "이 사전 설정은 중국 플랫폼을 사용하며 중국 및 국제 API 키는 서로 호환되지 않습니다.",
    ),
    "使用北京地域 OpenAI 兼容端点；API Key 必须与地域和计费方案匹配。": (
        "Uses the Beijing OpenAI-compatible endpoint. The API key must match its region and billing plan.",
        "北京リージョンの OpenAI 互換エンドポイントを使用します。API キーはリージョンと料金プランに合わせる必要があります。",
        "베이징 OpenAI 호환 엔드포인트를 사용합니다. API 키는 지역 및 요금제와 일치해야 합니다.",
    ),
    "聚合多家模型；请选择与你账号权限对应的模型 ID。": (
        "Aggregates multiple model families; choose a model ID available to your account.",
        "複数のモデルを集約しています。アカウントで利用可能なモデル ID を選択してください。",
        "여러 모델 계열을 제공하므로 계정 권한에 맞는 모델 ID를 선택하세요.",
    ),
    "使用智谱开放平台的 OpenAI 兼容 Chat Completions 接口。": (
        "Uses Zhipu's OpenAI-compatible Chat Completions endpoint.",
        "Zhipu の OpenAI 互換 Chat Completions エンドポイントを使用します。",
        "Zhipu의 OpenAI 호환 Chat Completions 엔드포인트를 사용합니다.",
    ),
    "已载入 {provider} 预设；请填写该厂商的 API Key 后测试连接。": (
        "Loaded the {provider} preset. Enter that provider's API key and test the connection.",
        "{provider} のプリセットを読み込みました。そのプロバイダーの API キーを入力して接続をテストしてください。",
        "{provider} 사전 설정을 불러왔습니다. 해당 공급자의 API 키를 입력하고 연결을 테스트하세요.",
    ),
    "模型": ("Model", "モデル", "모델"),
    "超时（秒）": ("Timeout (seconds)", "タイムアウト（秒）", "시간 제한(초)"),
    "并发数": ("Concurrent Requests", "同時リクエスト数", "동시 요청 수"),
    "输入费用 / 百万 Token": ("Input Cost / 1M Tokens", "入力料金 / 100万トークン", "입력 비용 / 백만 토큰"),
    "输出费用 / 百万 Token": ("Output Cost / 1M Tokens", "出力料金 / 100万トークン", "출력 비용 / 백만 토큰"),
    "显示 API Key": ("Show API Key", "API キーを表示", "API 키 표시"),
    "测试连接": ("Test Connection", "接続テスト", "연결 테스트"),
    "尚未测试连接": ("Connection not tested", "接続は未テストです", "연결 테스트 안 함"),
    "连接状态": ("Connection Status", "接続状態", "연결 상태"),
    "隐私提示：文件名和基础元数据会发送给 API；正文、完整目录和图片分别由下列开关控制。图片会先缩略并重新编码，移除 EXIF/GPS。": (
        "Privacy: file names and basic metadata are sent to the API. The switches below separately control content, full paths, and images. Images are resized and re-encoded to remove EXIF/GPS.",
        "プライバシー：ファイル名と基本メタデータは API に送信されます。本文、完全なパス、画像は下のスイッチで個別に制御します。画像は縮小・再エンコードして EXIF/GPS を削除します。",
        "개인정보: 파일명과 기본 메타데이터가 API로 전송됩니다. 아래 스위치에서 본문, 전체 경로 및 이미지를 각각 제어합니다. 이미지는 축소 및 재인코딩되어 EXIF/GPS가 제거됩니다.",
    ),
    "自动建议阈值": ("Auto-suggestion Threshold", "自動提案しきい値", "자동 제안 임계값"),
    "待确认阈值": ("Review Threshold", "要確認しきい値", "확인 필요 임계값"),
    "发送有限文本内容": ("Send Limited Text Content", "限定したテキストを送信", "제한된 텍스트 내용 전송"),
    "发送完整所在目录": ("Send Full Folder Path", "完全なフォルダーパスを送信", "전체 폴더 경로 전송"),
    "允许图片识别": ("Allow Image Recognition", "画像認識を許可", "이미지 인식 허용"),
    "文本最大字符": ("Maximum Text Characters", "テキスト最大文字数", "최대 텍스트 글자 수"),
    "文件": ("Files", "ファイル", "파일"),
    "递归扫描": ("Scan Subfolders", "サブフォルダーをスキャン", "하위 폴더 스캔"),
    "扫描隐藏文件（系统文件始终跳过）": ("Scan Hidden Files (System Files Always Skipped)", "隠しファイルをスキャン（システムファイルは常に除外）", "숨김 파일 스캔(시스템 파일은 항상 제외)"),
    "扫描隐藏/系统文件": ("Scan Hidden Files (System Files Are Protected)", "隠しファイルをスキャン（システムファイルは保護）", "숨김 파일 스캔(시스템 파일 보호)"),
    "保留原目录结构": ("Preserve Folder Structure", "元のフォルダー構成を維持", "원본 폴더 구조 유지"),
    "允许使用可选重命名": ("Allow Optional Rename", "任意の名前変更を許可", "선택적 이름 바꾸기 허용"),
    "默认重命名模板": ("Default Rename Template", "既定の名前変更テンプレート", "기본 이름 바꾸기 템플릿"),
    "安全": ("Safety", "安全", "안전"),
    "执行前必须确认": ("Require Confirmation Before Changes", "実行前に確認を必須にする", "실행 전 확인 필수"),
    "安全要求：实际移动前始终显示可逐条取消的预览": (
        "Safety requirement: a per-file preview is always shown before files are moved",
        "安全要件：実際の移動前に、項目ごとに除外できるプレビューを必ず表示します",
        "안전 요구 사항: 실제 이동 전에 파일별로 제외할 수 있는 미리보기를 항상 표시합니다",
    ),
    "启用操作历史": ("Enable Operation History", "操作履歴を有効化", "작업 기록 사용"),
    "允许撤销": ("Allow Undo", "元に戻す機能を許可", "실행 취소 허용"),
    "解压": ("Extraction", "解凍", "압축 해제"),
    "自动识别压缩包": ("Detect Archives Automatically", "アーカイブを自動検出", "압축 파일 자동 감지"),
    "自动解压": ("Extract Automatically", "自動解凍", "자동 압축 해제"),
    "解压后继续扫描": ("Scan Extracted Files", "解凍後にスキャンを続行", "압축 해제 후 계속 스캔"),
    "解压成功后处理原包": ("After Successful Extraction", "解凍成功後の元ファイル処理", "압축 해제 성공 후 원본 처리"),
    "保留原压缩包": ("Keep Original Archive", "元のアーカイブを保持", "원본 압축 파일 유지"),
    "移动到“已解压压缩包”": ("Move to “Extracted Archives”", "「解凍済みアーカイブ」へ移動", "‘압축 해제된 파일’로 이동"),
    "放入回收站": ("Move to Recycle Bin", "ごみ箱へ移動", "휴지통으로 이동"),
    "解压模式": ("Extraction Mode", "解凍モード", "압축 해제 모드"),
    "当前目录": ("Beside the Archive", "アーカイブと同じ場所", "압축 파일과 같은 위치"),
    "统一目录": ("Shared Folder", "共通フォルダー", "통합 폴더"),
    "临时目录": ("Temporary Folder", "一時フォルダー", "임시 폴더"),
    "统一解压目录": ("Shared Extraction Folder", "共通の解凍先", "통합 압축 해제 폴더"),
    "创建同名文件夹": ("Create Matching Folder", "同名フォルダーを作成", "동일한 이름의 폴더 만들기"),
    "最大递归层数": ("Maximum Recursion Depth", "最大再帰レベル", "최대 재귀 깊이"),
    "单包最大 MB": ("Maximum MB per Archive", "アーカイブごとの最大 MB", "압축 파일당 최대 MB"),
    "单包最大文件数": ("Maximum Files per Archive", "アーカイブごとの最大ファイル数", "압축 파일당 최대 파일 수"),
    "最大压缩比": ("Maximum Compression Ratio", "最大圧縮率", "최대 압축률"),
    "任务最大 MB": ("Maximum MB per Task", "タスクごとの最大 MB", "작업당 최대 MB"),
    "7-Zip 检测": ("7-Zip Detection", "7-Zip 検出", "7-Zip 감지"),
    "未检测到（ZIP/7z/TAR 仍可由 Python 库处理；RAR 可能不可用）": (
        "Not detected (Python libraries still support ZIP/7z/TAR; RAR may be unavailable)",
        "未検出（ZIP/7z/TAR は Python ライブラリで処理可能。RAR は利用できない場合があります）",
        "감지되지 않음(Python 라이브러리로 ZIP/7z/TAR 처리 가능, RAR는 사용하지 못할 수 있음)",
    ),
    "管理解压密码…": ("Manage Extraction Passwords…", "解凍パスワードを管理…", "압축 해제 비밀번호 관리…"),
    "自动解压会固定递归查找所选目录的全部子目录，不受普通文件“递归扫描”开关影响。": (
        "Automatic extraction always searches every subfolder of the selected folder, independently of the regular file scan option.",
        "自動解凍は通常ファイルの設定に関係なく、選択したフォルダーの全サブフォルダーを検索します。",
        "자동 압축 해제는 일반 파일 스캔 옵션과 관계없이 선택한 폴더의 모든 하위 폴더를 검색합니다.",
    ),
    "界面语言": ("Interface Language", "表示言語", "인터페이스 언어"),
    "界面材质包": ("Interface Material Pack", "UI マテリアルパック", "인터페이스 머티리얼 팩"),
    "导入材质包…": ("Import Material Pack…", "マテリアルパックを読み込む…", "머티리얼 팩 가져오기…"),
    "删除材质包": ("Delete Material Pack", "マテリアルパックを削除", "머티리얼 팩 삭제"),
    "生成示例包…": ("Create Example Pack…", "サンプルパックを作成…", "예제 팩 만들기…"),
    "材质包只允许颜色令牌和一张背景图片，不执行 QSS 或脚本。": (
        "Material packs allow only color tokens and one background image; QSS and scripts are never executed.",
        "マテリアルパックで許可されるのは色と背景画像1枚のみで、QSSやスクリプトは実行しません。",
        "머티리얼 팩은 색상 토큰과 배경 이미지 한 장만 허용하며 QSS나 스크립트를 실행하지 않습니다.",
    ),
    "内置材质（不可删除）": ("Built-in (cannot be deleted)", "内蔵（削除不可）", "기본 제공(삭제 불가)"),
    "自定义材质": ("Custom", "カスタム", "사용자 지정"),
    "无": ("None", "なし", "없음"),
    "材质预览\n名称：{name}\n来源：{origin}\n版本：{version}\n作者：{author}\n背景：{background}\n说明：{description}": (
        "Material Preview\nName: {name}\nSource: {origin}\nVersion: {version}\nAuthor: {author}\nBackground: {background}\nDescription: {description}",
        "マテリアルプレビュー\n名前：{name}\n種類：{origin}\nバージョン：{version}\n作者：{author}\n背景：{background}\n説明：{description}",
        "머티리얼 미리보기\n이름: {name}\n출처: {origin}\n버전: {version}\n제작자: {author}\n배경: {background}\n설명: {description}",
    ),
    "部分材质包无法读取：": ("Some material packs could not be read: ", "一部のマテリアルパックを読み込めません：", "일부 머티리얼 팩을 읽을 수 없습니다: "),
    "导入材质包": ("Import Material Pack", "マテリアルパックを読み込む", "머티리얼 팩 가져오기"),
    "已导入：{name}": ("Imported: {name}", "読み込みました：{name}", "가져옴: {name}"),
    "无法导入材质包": ("Could Not Import Material Pack", "マテリアルパックを読み込めません", "머티리얼 팩을 가져올 수 없음"),
    "确定删除自定义材质包“{name}”吗？": (
        "Delete the custom material pack “{name}”?",
        "カスタムマテリアルパック「{name}」を削除しますか？",
        "사용자 머티리얼 팩 ‘{name}’을 삭제하시겠습니까?",
    ),
    "无法删除材质包": ("Could Not Delete Material Pack", "マテリアルパックを削除できません", "머티리얼 팩을 삭제할 수 없음"),
    "生成示例材质包": ("Create Example Material Pack", "サンプルマテリアルパックを作成", "예제 머티리얼 팩 만들기"),
    "示例包已生成：{path}": ("Example pack created: {path}", "サンプルパックを作成しました：{path}", "예제 팩 생성됨: {path}"),
    "无法生成示例包": ("Could Not Create Example Pack", "サンプルパックを作成できません", "예제 팩을 만들 수 없음"),
    "连接测试进行中": ("Connection Test in Progress", "接続テスト実行中", "연결 테스트 진행 중"),
    "请等待连接测试完成后再保存。": ("Wait for the connection test to finish before saving.", "接続テストが完了してから保存してください。", "연결 테스트가 완료된 후 저장하세요."),
    "确认回收站行为": ("Confirm Recycle Bin Action", "ごみ箱への移動を確認", "휴지통 동작 확인"),
    "启用后，解压成功的原压缩包会被放入系统回收站。此项不是永久删除，但应用内撤销不保证可恢复。是否启用？": (
        "When enabled, successfully extracted archives are moved to the system Recycle Bin. This is not permanent deletion, but in-app undo cannot guarantee recovery. Enable it?",
        "有効にすると、解凍成功後の元アーカイブをシステムのごみ箱へ移動します。完全削除ではありませんが、アプリ内の元に戻す機能では復元を保証できません。有効にしますか？",
        "활성화하면 압축 해제에 성공한 원본 압축 파일이 시스템 휴지통으로 이동합니다. 영구 삭제는 아니지만 앱 내 실행 취소로 복구를 보장할 수 없습니다. 활성화하시겠습니까?",
    ),
    "设置已保存。": ("Settings saved. ", "設定を保存しました。", "설정이 저장되었습니다. "),
    "API Key 已存入系统凭据。": ("API key saved to the system credential store.", "API キーをシステム資格情報に保存しました。", "API 키가 시스템 자격 증명에 저장되었습니다."),
    "API Key 仅保存在本次运行中。": ("API key is stored only for this session.", "API キーは今回の実行中のみ保持されます。", "API 키는 이번 실행에서만 저장됩니다."),
    "保存失败": ("Save Failed", "保存失敗", "저장 실패"),
    "服务地址已变化，请为该服务重新输入 API Key": (
        "The service address changed; enter the API key for this service",
        "サービスアドレスが変わりました。このサービスの API キーを再入力してください",
        "서비스 주소가 변경되었습니다. 이 서비스의 API 키를 다시 입력하세요",
    ),
    "请先填写 API Key": ("Enter an API key first", "先に API キーを入力してください", "먼저 API 키를 입력하세요"),
    "配置有误：{error}": ("Invalid configuration: {error}", "設定エラー：{error}", "설정 오류: {error}"),
    "正在测试…": ("Testing…", "テスト中…", "테스트 중…"),
    "正在连接，请稍候…": ("Connecting, please wait…", "接続中です。お待ちください…", "연결 중입니다. 잠시 기다리세요…"),
    "连接成功 · 模型：{model} · 延迟：{latency} ms": (
        "Connected · Model: {model} · Latency: {latency} ms",
        "接続成功 · モデル：{model} · 遅延：{latency} ms",
        "연결 성공 · 모델: {model} · 지연 시간: {latency}ms",
    ),
    "连接失败：{error}": ("Connection failed: {error}", "接続失敗：{error}", "연결 실패: {error}"),
    "正在取消连接测试，随后关闭…": ("Cancelling the connection test, then closing…", "接続テストをキャンセルしてから閉じます…", "연결 테스트를 취소한 후 닫습니다…"),

    # Data/status values that appear in the table and details pane
    "无需解压": ("Not an Archive", "解凍不要", "압축 해제 불필요"),
    "等待解压": ("Waiting", "解凍待ち", "압축 해제 대기"),
    "正在解压": ("Extracting", "解凍中", "압축 해제 중"),
    "解压成功": ("Extracted", "解凍成功", "압축 해제 성공"),
    "需要密码": ("Password Required", "パスワードが必要", "비밀번호 필요"),
    "密码错误": ("Wrong Password", "パスワードエラー", "비밀번호 오류"),
    "格式不支持": ("Unsupported Format", "未対応形式", "지원하지 않는 형식"),
    "解压失败": ("Extraction Failed", "解凍失敗", "압축 해제 실패"),
    "待处理": ("Pending", "処理待ち", "처리 대기"),
    "手动": ("Manual", "手動", "수동"),
    "关闭": ("Off", "オフ", "끄기"),
    "确定": ("OK", "OK", "확인"),
    "应用": ("Apply", "適用", "적용"),
    "重置": ("Reset", "リセット", "재설정"),
    "恢复默认": ("Restore Defaults", "既定値に戻す", "기본값 복원"),
    "打开": ("Open", "開く", "열기"),
    "放弃": ("Discard", "破棄", "버리기"),
    "重试": ("Retry", "再試行", "다시 시도"),
    "中止": ("Abort", "中止", "중단"),
    "忽略": ("Ignore", "無視", "무시"),
    "移动分类": ("Move Only", "分類のみ移動", "분류만 이동"),
}

_TRANSLATIONS: Final[dict[str, dict[str, str]]] = {
    "en": {source: values[0] for source, values in _TEXT.items()},
    "ja": {source: values[1] for source, values in _TEXT.items()},
    "ko": {source: values[2] for source, values in _TEXT.items()},
}

_lock = RLock()
_language = DEFAULT_LANGUAGE


def normalize_language(code: str | None) -> str:
    """Return a supported language code; unknown values safely use Chinese."""

    if not code:
        return DEFAULT_LANGUAGE
    candidate = str(code).strip()
    if candidate in SUPPORTED_LANGUAGES:
        return candidate
    return _ALIASES.get(candidate.lower(), DEFAULT_LANGUAGE)


def set_language(code: str | None) -> str:
    """Set the process UI language and return the normalized code."""

    global _language
    normalized = normalize_language(code)
    with _lock:
        _language = normalized
    return normalized


def get_language() -> str:
    """Return the current normalized UI language code."""

    with _lock:
        return _language


def language_name(code: str | None = None) -> str:
    """Return the native display name for a language code."""

    return LANGUAGE_NAMES[normalize_language(code if code is not None else get_language())]


def language_choices() -> tuple[tuple[str, str], ...]:
    """Return stable ``(code, native name)`` choices for a language selector."""

    return tuple(LANGUAGE_NAMES.items())


def tr(source: str, **kwargs: object) -> str:
    """Translate and optionally format a source-language UI string.

    Missing translations intentionally fall back to the Chinese source.  Bad or
    incomplete formatting data never escapes into Qt event handlers as an
    exception; the untranslated placeholders remain visible for diagnosis.
    """

    text = str(source)
    language = get_language()
    if language != DEFAULT_LANGUAGE:
        text = _TRANSLATIONS.get(language, {}).get(source, source)
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except (AttributeError, IndexError, KeyError, ValueError):
        return text


def _source_property(obj: Any, property_name: str, current: str) -> str | None:
    """Remember a known static source string on a Qt object."""

    saved = obj.property(property_name)
    if isinstance(saved, str):
        return saved
    if current in _TEXT:
        obj.setProperty(property_name, current)
        return current
    return None


def translate_widget_tree(root: Any) -> None:
    """Retranslate known static text below a Qt widget.

    PySide6 is imported lazily so non-GUI services and unit tests can use the
    translation module without loading Qt.  Only strings present in the static
    dictionary are changed.  In particular, line-edit contents, file names,
    paths, user categories, and other dynamic table/combo data are untouched.
    The first Chinese source string is retained as a Qt dynamic property, which
    makes repeated English/Japanese/Korean/Chinese switches reversible.
    """

    if root is None:
        return
    try:
        from PySide6.QtCore import QObject
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import (
            QAbstractButton,
            QComboBox,
            QDialogButtonBox,
            QGroupBox,
            QLabel,
            QLineEdit,
            QMenu,
            QTabWidget,
            QTableWidget,
            QWidget,
        )
    except ImportError:  # pragma: no cover - the desktop distribution includes Qt
        return

    objects: list[Any] = [root]
    if isinstance(root, QObject):
        objects.extend(root.findChildren(QObject))

    # Window titles, labels, buttons, checkboxes, group boxes, menus, and static
    # placeholders all have a single source property on their owning object.
    for obj in objects:
        if isinstance(obj, QWidget):
            title = obj.windowTitle()
            source = _source_property(obj, "_aifo_i18n_window_title", title)
            if source is not None:
                obj.setWindowTitle(tr(source))

        if isinstance(obj, (QLabel, QAbstractButton, QGroupBox)):
            current = obj.text() if hasattr(obj, "text") else obj.title()
            source = _source_property(obj, "_aifo_i18n_text", current)
            if source is not None:
                if hasattr(obj, "setText"):
                    obj.setText(tr(source))
                else:
                    obj.setTitle(tr(source))

        if isinstance(obj, QLineEdit):
            source = _source_property(obj, "_aifo_i18n_placeholder", obj.placeholderText())
            if source is not None:
                obj.setPlaceholderText(tr(source))

        if isinstance(obj, QMenu):
            source = _source_property(obj, "_aifo_i18n_menu_title", obj.title())
            if source is not None:
                # QMenu interprets a single ampersand as a mnemonic marker.
                # Escape translated literal ampersands while keeping ``tr``
                # suitable for labels, tests, logs and other non-menu text.
                obj.setTitle(tr(source).replace("&", "&&"))

    # Tabs and item views need one remembered source string per index.  We store
    # only known static entries; arbitrary combo-box/table values stay untouched.
    for obj in objects:
        if isinstance(obj, QTabWidget):
            saved = obj.property("_aifo_i18n_tab_sources")
            sources = dict(saved) if isinstance(saved, dict) else {}
            for index in range(obj.count()):
                source = sources.get(index)
                if not isinstance(source, str) and obj.tabText(index) in _TEXT:
                    source = obj.tabText(index)
                    sources[index] = source
                if isinstance(source, str):
                    obj.setTabText(index, tr(source))
            obj.setProperty("_aifo_i18n_tab_sources", sources)

        if isinstance(obj, QTableWidget):
            saved = obj.property("_aifo_i18n_header_sources")
            sources = dict(saved) if isinstance(saved, dict) else {}
            for column in range(obj.columnCount()):
                item = obj.horizontalHeaderItem(column)
                if item is None:
                    continue
                source = sources.get(column)
                if not isinstance(source, str) and item.text() in _TEXT:
                    source = item.text()
                    sources[column] = source
                if isinstance(source, str):
                    item.setText(tr(source))
            obj.setProperty("_aifo_i18n_header_sources", sources)

        if isinstance(obj, QComboBox):
            if obj.property("_aifo_i18n_skip_items") is True:
                continue
            saved = obj.property("_aifo_i18n_item_sources")
            sources = dict(saved) if isinstance(saved, dict) else {}
            for index in range(obj.count()):
                source = sources.get(index)
                if not isinstance(source, str) and obj.itemText(index) in _TEXT:
                    source = obj.itemText(index)
                    sources[index] = source
                if isinstance(source, str):
                    obj.setItemText(index, tr(source))
            obj.setProperty("_aifo_i18n_item_sources", sources)

    # QAction is not a QWidget and may live on a menu bar or context menu.
    for obj in objects:
        if isinstance(obj, QAction):
            if obj.property("_aifo_i18n_skip") is True:
                continue
            source = _source_property(obj, "_aifo_i18n_action_text", obj.text())
            if source is not None:
                obj.setText(tr(source))

    # Standard buttons can be localized even when Qt supplied their initial text
    # in the operating-system language rather than in Chinese.
    standard_sources = {
        QDialogButtonBox.StandardButton.Ok: "确定",
        QDialogButtonBox.StandardButton.Save: "保存",
        QDialogButtonBox.StandardButton.Cancel: "取消",
        QDialogButtonBox.StandardButton.Close: "关闭",
        QDialogButtonBox.StandardButton.Yes: "是",
        QDialogButtonBox.StandardButton.No: "否",
        QDialogButtonBox.StandardButton.Apply: "应用",
        QDialogButtonBox.StandardButton.Reset: "重置",
        QDialogButtonBox.StandardButton.RestoreDefaults: "恢复默认",
        QDialogButtonBox.StandardButton.Open: "打开",
        QDialogButtonBox.StandardButton.Help: "帮助",
        QDialogButtonBox.StandardButton.Discard: "放弃",
        QDialogButtonBox.StandardButton.Retry: "重试",
        QDialogButtonBox.StandardButton.Abort: "中止",
        QDialogButtonBox.StandardButton.Ignore: "忽略",
    }
    for obj in objects:
        if not isinstance(obj, QDialogButtonBox):
            continue
        for standard_button, source in standard_sources.items():
            button = obj.button(standard_button)
            if button is not None:
                button.setProperty("_aifo_i18n_text", source)
                button.setText(tr(source))


__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGE_NAMES",
    "SUPPORTED_LANGUAGES",
    "get_language",
    "language_choices",
    "language_name",
    "normalize_language",
    "set_language",
    "tr",
    "translate_widget_tree",
]
