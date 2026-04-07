import pytest

from app.schemas import ParseTaskResponse
from app.services.task_parsing_service import TaskParsingService


pytestmark = pytest.mark.asyncio


async def test_heuristic_parse_extracts_due_priority_and_tags(
    task_parsing_service: TaskParsingService,
):
    result = await task_parsing_service.parse_text("明天提交前端测试报告，尽快处理")

    assert isinstance(result, ParseTaskResponse)
    assert result.source == "heuristic"
    assert result.draft.priority == 1
    assert "frontend" in result.draft.tags
    assert "testing" in result.draft.tags
    assert "report" in result.draft.tags
    assert result.draft.due_at is not None
    assert result.draft.meta_data["parsed_by"] == "heuristic"
    assert result.candidates
    assert result.candidates[0].title == result.draft.title


async def test_heuristic_parse_handles_next_week_date(
    task_parsing_service: TaskParsingService,
):
    result = await task_parsing_service.parse_text("下周给客户发部署文档")

    assert result.draft.due_at is not None
    assert "deployment" in result.draft.tags
    assert "docs" in result.draft.tags


async def test_heuristic_parse_handles_this_weekday(
    task_parsing_service: TaskParsingService,
):
    result = await task_parsing_service.parse_text("本周五下午给客户发报告")

    assert result.draft.due_at is not None
    assert result.draft.due_at.weekday() == 4
    assert result.draft.due_at.hour == 15


async def test_heuristic_parse_handles_end_of_month(
    task_parsing_service: TaskParsingService,
):
    result = await task_parsing_service.parse_text("月底前整理项目文档")

    assert result.draft.due_at is not None
    assert result.draft.due_at.day in {28, 29, 30, 31}


async def test_heuristic_parse_records_confidence_signals(
    task_parsing_service: TaskParsingService,
):
    result = await task_parsing_service.parse_text("明天补后端测试并提交报告，给团队同步")

    signals = result.draft.meta_data["confidence_signals"]
    assert "due_at" in signals
    assert "tags" in signals
    assert result.confidence > 0.5


async def test_heuristic_parse_handles_relative_days(
    task_parsing_service: TaskParsingService,
):
    result = await task_parsing_service.parse_text("3天后上午10点给客户发文档")

    assert result.draft.due_at is not None
    assert result.draft.due_at.hour == 10
    assert result.draft.due_at.minute == 0


async def test_heuristic_parse_handles_tonight(
    task_parsing_service: TaskParsingService,
):
    result = await task_parsing_service.parse_text("今晚修复后端 bug")

    assert result.draft.due_at is not None
    assert result.draft.due_at.hour == 20


async def test_heuristic_parse_handles_next_next_weekday_with_explicit_time(
    task_parsing_service: TaskParsingService,
):
    result = await task_parsing_service.parse_text("下下周一下午3点同步项目进度")

    assert result.draft.due_at is not None
    assert result.draft.due_at.weekday() == 0
    assert result.draft.due_at.hour == 15


async def test_heuristic_parse_keeps_raw_text(
    task_parsing_service: TaskParsingService,
):
    text = "整理一下 backlog"
    result = await task_parsing_service.parse_text(text)

    assert result.raw_text == text
    assert result.draft.title


async def test_heuristic_parse_returns_alternative_candidates(
    task_parsing_service: TaskParsingService,
):
    result = await task_parsing_service.parse_text("明天补后端测试并提交报告，给团队同步")

    assert len(result.candidates) >= 2
