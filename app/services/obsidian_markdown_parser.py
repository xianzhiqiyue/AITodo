from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ParsedObsidianTask:
    task_id: str
    title: str
    description: str | None
    status: str
    priority: int
    due_at: datetime | None
    parent_id: str | None
    tags: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    source_updated_at: datetime | None = None
    schema_version: int = 1
    raw_frontmatter: dict[str, Any] = field(default_factory=dict)


class ObsidianMarkdownParser:
    def parse_task(self, content: str) -> ParsedObsidianTask | None:
        frontmatter, body = self._split_frontmatter(content)
        if not frontmatter or frontmatter.get("source") != "ai-todo":
            return None
        task_id = str(frontmatter.get("aitodo_id") or "").strip()
        if not task_id:
            return None
        try:
            uuid.UUID(task_id)
        except ValueError:
            return None

        title = self._extract_title(body) or str(frontmatter.get("title") or task_id)
        description = self._extract_description(body)
        return ParsedObsidianTask(
            task_id=task_id,
            title=title,
            description=description,
            status=str(frontmatter.get("status") or "todo"),
            priority=self._parse_int(frontmatter.get("priority"), default=3),
            due_at=self._parse_datetime(frontmatter.get("due_at")),
            parent_id=self._normalize_optional_uuid(frontmatter.get("parent_id")),
            tags=self._parse_string_list(frontmatter.get("tags")),
            depends_on=self._parse_depends_on(frontmatter, body),
            source_updated_at=self._parse_datetime(frontmatter.get("updated_at")),
            schema_version=self._parse_int(frontmatter.get("schema_version"), default=1),
            raw_frontmatter=frontmatter,
        )

    def _split_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        normalized = content.replace("\r\n", "\n")
        if not normalized.startswith("---\n"):
            return {}, normalized
        end = normalized.find("\n---\n", 4)
        if end == -1:
            return {}, normalized
        raw = normalized[4:end]
        body = normalized[end + len("\n---\n"):]
        return self._parse_simple_yaml(raw), body

    def _parse_simple_yaml(self, raw: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        current_key: str | None = None
        for line in raw.splitlines():
            if not line.strip():
                continue
            if line.startswith("  - ") and current_key:
                result.setdefault(current_key, [])
                if isinstance(result[current_key], list):
                    result[current_key].append(line[4:].strip().strip('"\''))
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            current_key = key
            if value == "":
                result[key] = []
            elif value == "[]":
                result[key] = []
            else:
                result[key] = value.strip('"\'')
        return result

    def _extract_title(self, body: str) -> str | None:
        for line in body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return None

    def _extract_description(self, body: str) -> str | None:
        lines = body.splitlines()
        start: int | None = None
        for index, line in enumerate(lines):
            if line.startswith("# "):
                start = index + 1
                break
        if start is None:
            return None
        collected: list[str] = []
        for line in lines[start:]:
            if line.startswith("## "):
                break
            collected.append(line)
        description = "\n".join(collected).strip()
        return description or None

    def _parse_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _parse_datetime(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _normalize_optional_uuid(self, value: Any) -> str | None:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return str(uuid.UUID(text))
        except ValueError:
            return None

    def _parse_string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        if isinstance(value, str) and value:
            return [value]
        return []

    def _parse_depends_on(self, frontmatter: dict[str, Any], body: str) -> list[str]:
        values = self._parse_string_list(frontmatter.get("depends_on"))
        if values:
            return [str(uuid.UUID(value)) for value in values if self._is_uuid(value)]
        found = re.findall(r"AI-Todo/tasks/([0-9a-fA-F-]{36})\.md", body)
        return [str(uuid.UUID(value)) for value in found if self._is_uuid(value)]

    def _is_uuid(self, value: str) -> bool:
        try:
            uuid.UUID(str(value))
            return True
        except ValueError:
            return False
