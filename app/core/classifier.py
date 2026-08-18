from __future__ import annotations

from pathlib import Path

from app.models.schemas import ClassificationRule, FileRecord, RuleType


class RuleClassifier:
    def __init__(self, rules: list[ClassificationRule]):
        self.rules = sorted((r for r in rules if r.enabled), key=lambda r: (r.priority, r.id or 0))

    def classify(self, record: FileRecord) -> FileRecord:
        for kind in (RuleType.MANUAL, RuleType.PREFIX, RuleType.EXTENSION):
            for rule in (r for r in self.rules if r.rule_type == kind):
                if self.matches(rule, record.name):
                    record.category = rule.category
                    record.confidence = 1.0 if kind == RuleType.MANUAL else (0.98 if kind == RuleType.PREFIX else 0.9)
                    record.reason = f"命中{kind.value}规则：{rule.pattern}"
                    record.source = {RuleType.MANUAL: "手动规则", RuleType.PREFIX: "前缀规则", RuleType.EXTENSION: "扩展名规则"}[kind]
                    return record
        record.category, record.confidence, record.source = "待确认", 0.0, "待确认"
        return record

    @staticmethod
    def matches(rule: ClassificationRule, filename: str) -> bool:
        candidate = filename if rule.case_sensitive else filename.lower()
        patterns = [p.strip() for p in rule.pattern.split(",") if p.strip()]
        if not rule.case_sensitive:
            patterns = [p.lower() for p in patterns]
        if rule.rule_type in (RuleType.MANUAL, RuleType.PREFIX):
            return any(candidate.startswith(p) for p in patterns)
        return any(candidate.endswith(p if p.startswith(".") else "." + p) for p in patterns)

    def classify_all(self, records: list[FileRecord]) -> list[FileRecord]:
        return [self.classify(r) for r in records]


def category_target(root: Path, record: FileRecord) -> Path:
    category = record.category if record.category and record.category != "待确认" else "待确认"
    return root / category / (record.suggested_name or record.name)
