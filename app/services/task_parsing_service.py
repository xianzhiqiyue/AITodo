from __future__ import annotations

import json
import re
from datetime import datetime, time, timedelta
from calendar import monthrange
from zoneinfo import ZoneInfo

import httpx
import structlog

from app.config import Settings
from app.schemas import ParseTaskResponse, TaskDraft

logger = structlog.get_logger()


class TaskParsingService:
    def __init__(self, settings: Settings):
        self._api_key = settings.parsing_api_key
        self._base_url = settings.parsing_base_url.rstrip("/")
        self._model = settings.parsing_model
        self._timezone = ZoneInfo(settings.parsing_timezone)

    async def parse_text(self, text: str) -> ParseTaskResponse:
        if self._api_key:
            llm_result = await self._parse_with_llm(text)
            if llm_result is not None:
                return llm_result

        return self._parse_with_heuristics(text)

    async def _parse_with_llm(self, text: str) -> ParseTaskResponse | None:
        prompt = (
            "Extract a task draft from the user text. "
            "Return strict JSON with keys: title, description, status, priority, due_at, tags, meta_data, confidence. "
            "Rules: status must be todo/in_progress/done/blocked. "
            "priority must be 1-5. due_at must be ISO 8601 or null. "
            "tags must be an array of strings. meta_data must be an object. "
            "Do not include markdown or extra text."
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": text[:4000]},
                        ],
                    },
                )
                response.raise_for_status()
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                draft = TaskDraft(
                    title=parsed["title"],
                    description=parsed.get("description"),
                    status=parsed.get("status") or "todo",
                    priority=parsed.get("priority") or 3,
                    due_at=parsed.get("due_at"),
                    tags=parsed.get("tags") or [],
                    meta_data=parsed.get("meta_data") or {},
                )
                return ParseTaskResponse(
                    draft=draft,
                    candidates=[draft],
                    selected_index=0,
                    confidence=float(parsed.get("confidence", 0.8)),
                    source="llm",
                    raw_text=text,
                )
        except Exception:
            logger.warning("task_parsing_failed", text_length=len(text), exc_info=True)
            return None

    def _parse_with_heuristics(self, text: str) -> ParseTaskResponse:
        now = datetime.now(self._timezone)
        cleaned = re.sub(r"\s+", " ", text).strip()
        tags = self._infer_tags(cleaned)
        due_at = self._infer_due_at(cleaned, now)
        priority = self._infer_priority(cleaned)
        confidence, confidence_signals = self._score_confidence(
            cleaned=cleaned,
            due_at=due_at,
            priority=priority,
            tags=tags,
        )

        meta_data = {
            "parsed_by": "heuristic",
            "original_text": text,
            "confidence_signals": confidence_signals,
        }
        if due_at is not None:
            meta_data["due_detected"] = True

        candidates = self._build_heuristic_candidates(
            cleaned=cleaned,
            due_at=due_at,
            priority=priority,
            tags=tags,
            meta_data=meta_data,
        )
        draft = candidates[0]
        return ParseTaskResponse(
            draft=draft,
            candidates=candidates,
            selected_index=0,
            confidence=confidence,
            source="heuristic",
            raw_text=text,
        )

    def _build_heuristic_candidates(
        self,
        *,
        cleaned: str,
        due_at: datetime | None,
        priority: int,
        tags: list[str],
        meta_data: dict,
    ) -> list[TaskDraft]:
        title = cleaned[:255]

        if "，" in cleaned:
            title = cleaned.split("，", 1)[0][:255]
        elif "," in cleaned:
            title = cleaned.split(",", 1)[0][:255]

        primary = TaskDraft(
            title=title or cleaned[:255] or "Untitled task",
            description=cleaned if cleaned != title else None,
            priority=priority,
            due_at=due_at,
            tags=tags,
            meta_data=meta_data,
        )

        candidates = [primary]

        if primary.description is not None:
            candidates.append(
                TaskDraft(
                    title=cleaned[:255] or primary.title,
                    description=None,
                    priority=priority,
                    due_at=due_at,
                    tags=tags,
                    meta_data={**meta_data, "candidate_variant": "full_text_title"},
                )
            )

        if due_at is not None:
            candidates.append(
                TaskDraft(
                    title=primary.title,
                    description=primary.description,
                    priority=max(priority, 2),
                    due_at=None,
                    tags=tags,
                    meta_data={**meta_data, "candidate_variant": "without_due_date"},
                )
            )

        deduped: list[TaskDraft] = []
        seen: set[tuple] = set()
        for candidate in candidates:
            key = (
                candidate.title,
                candidate.description,
                candidate.priority,
                candidate.due_at.isoformat() if candidate.due_at else None,
                tuple(candidate.tags),
            )
            if key not in seen:
                deduped.append(candidate)
                seen.add(key)
        return deduped

    def _infer_tags(self, text: str) -> list[str]:
        mapping = {
            "报告": "report",
            "report": "report",
            "文档": "docs",
            "docs": "docs",
            "修复": "bugfix",
            "bug": "bugfix",
            "测试": "testing",
            "test": "testing",
            "部署": "deployment",
            "deploy": "deployment",
            "前端": "frontend",
            "frontend": "frontend",
            "后端": "backend",
            "backend": "backend",
        }
        lowered = text.lower()
        tags: list[str] = []
        for keyword, tag in mapping.items():
            if keyword in lowered or keyword in text:
                if tag not in tags:
                    tags.append(tag)
        return tags

    def _infer_priority(self, text: str) -> int:
        lowered = text.lower()
        high_keywords = ["紧急", "尽快", "asap", "urgent", "马上", "今天", "明天", "tomorrow", "本周", "deadline"]
        low_keywords = ["有空", "之后", "later"]
        if any(keyword in lowered or keyword in text for keyword in high_keywords):
            return 1
        if any(keyword in lowered or keyword in text for keyword in low_keywords):
            return 4
        return 3

    def _infer_due_at(self, text: str, now: datetime) -> datetime | None:
        lowered = text.lower()

        iso_match = re.search(r"\d{4}-\d{2}-\d{2}", text)
        if iso_match:
            parsed_date = datetime.strptime(iso_match.group(0), "%Y-%m-%d").date()
            return datetime.combine(parsed_date, self._infer_time_of_day(text), tzinfo=self._timezone)

        if "今天" in text or "today" in lowered:
            return datetime.combine(now.date(), self._infer_time_of_day(text), tzinfo=self._timezone)

        if "明天" in text or "tomorrow" in lowered:
            return datetime.combine(now.date() + timedelta(days=1), self._infer_time_of_day(text), tzinfo=self._timezone)

        if "今晚" in text or "tonight" in lowered:
            return datetime.combine(now.date(), self._infer_time_of_day(text, default=time(20, 0)), tzinfo=self._timezone)

        relative_days = self._match_relative_days(text, now)
        if relative_days is not None:
            return relative_days

        end_of_month = self._match_end_of_month(text, now)
        if end_of_month is not None:
            return end_of_month

        weekday_date = self._match_weekday_phrase(text, now)
        if weekday_date is not None:
            return weekday_date

        if "下周" in text or "next week" in lowered:
            days_until_monday = (7 - now.weekday()) or 7
            next_monday = now.date() + timedelta(days=days_until_monday)
            return datetime.combine(next_monday, self._infer_time_of_day(text, default=time(9, 0)), tzinfo=self._timezone)

        return None

    def _match_relative_days(self, text: str, now: datetime) -> datetime | None:
        match = re.search(r"(\d+)\s*天后", text)
        if match is None:
            return None
        days = int(match.group(1))
        target_date = now.date() + timedelta(days=days)
        return datetime.combine(target_date, self._infer_time_of_day(text), tzinfo=self._timezone)

    def _match_end_of_month(self, text: str, now: datetime) -> datetime | None:
        if "月底" not in text and "月末" not in text:
            return None

        year = now.year
        month = now.month
        if "下个月" in text:
            month += 1
            if month == 13:
                year += 1
                month = 1

        last_day = monthrange(year, month)[1]
        due_time = self._infer_time_of_day(text, default=time(18, 0))
        if "前" in text and "上午" not in text and "中午" not in text and "下午" not in text and "晚上" not in text:
            due_time = time(12, 0)
        return datetime(year, month, last_day, due_time.hour, due_time.minute, tzinfo=self._timezone)

    def _match_weekday_phrase(self, text: str, now: datetime) -> datetime | None:
        weekday_map = {
            "一": 0,
            "二": 1,
            "三": 2,
            "四": 3,
            "五": 4,
            "六": 5,
            "日": 6,
            "天": 6,
        }
        match = re.search(r"(本周|这周|下周|下下周)?周([一二三四五六日天])", text)
        if match is None:
            return None

        prefix = match.group(1) or ""
        target_weekday = weekday_map[match.group(2)]
        current_weekday = now.weekday()

        if prefix in {"本周", "这周"}:
            delta_days = target_weekday - current_weekday
            if delta_days < 0:
                delta_days += 7
        elif prefix == "下周":
            delta_days = (7 - current_weekday) + target_weekday
        elif prefix == "下下周":
            delta_days = (14 - current_weekday) + target_weekday
        else:
            delta_days = target_weekday - current_weekday
            if delta_days < 0:
                delta_days += 7

        target_date = now.date() + timedelta(days=delta_days)
        due_time = self._infer_time_of_day(text)
        return datetime.combine(target_date, due_time, tzinfo=self._timezone)

    def _infer_time_of_day(self, text: str, default: time = time(18, 0)) -> time:
        explicit_time = self._match_explicit_time(text)
        if explicit_time is not None:
            return explicit_time

        if "上午" in text:
            return time(10, 0)
        if "中午" in text:
            return time(12, 0)
        if "下午" in text:
            return time(15, 0)
        if "晚上" in text or "今晚" in text:
            return time(20, 0)
        if "凌晨" in text:
            return time(1, 0)
        return default

    def _match_explicit_time(self, text: str) -> time | None:
        hour_minute_match = re.search(r"(?:(上午|中午|下午|晚上|凌晨))?\s*(\d{1,2})[:点时](\d{1,2})?", text)
        if hour_minute_match is None:
            return None

        period = hour_minute_match.group(1)
        hour = int(hour_minute_match.group(2))
        minute = int(hour_minute_match.group(3) or 0)

        if period in {"下午", "晚上"} and hour < 12:
            hour += 12
        if period == "凌晨" and hour == 12:
            hour = 0
        if period == "中午" and hour < 11:
            hour += 12

        hour = min(max(hour, 0), 23)
        minute = min(max(minute, 0), 59)
        return time(hour, minute)

    def _score_confidence(
        self,
        *,
        cleaned: str,
        due_at: datetime | None,
        priority: int,
        tags: list[str],
    ) -> tuple[float, list[str]]:
        signals: list[str] = []
        score = 0.25

        if due_at is not None:
            score += 0.2
            signals.append("due_at")

        if tags:
            score += min(len(tags), 3) * 0.08
            signals.append("tags")

        if priority in {1, 4}:
            score += 0.1
            signals.append("priority_signal")

        if len(cleaned) >= 8:
            score += 0.08
            signals.append("sufficient_length")

        if any(token in cleaned for token in ["给", "提交", "发送", "整理", "补", "修复", "编写", "同步"]):
            score += 0.08
            signals.append("action_verb")

        if "，" in cleaned or "," in cleaned:
            score += 0.04
            signals.append("structured_clause")

        if re.search(r"(\d+)\s*天后|今晚|周[一二三四五六日天]|上午|下午|晚上|\d{1,2}[:点时]", cleaned):
            score += 0.06
            signals.append("time_expression")

        return min(score, 0.95), signals
