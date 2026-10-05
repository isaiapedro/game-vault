from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Literal
from datetime import date


class BacklogAdd(BaseModel):
    model_config = ConfigDict(extra='forbid')
    game_id: int
    target_date: Optional[date] = None
    notes: Optional[str] = None


class BacklogUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    notes: Optional[str] = None
    target_date: Optional[date] = None


class BacklogReorder(BaseModel):
    ordered_game_ids: List[int]
    expected_game_ids: Optional[List[int]] = None


class QueueSummary(BaseModel):
    total_estimated_hours: float
    known_estimate_count: int
    unknown_estimate_count: int
    available_count: int
    unavailable_count: int
    total_count: int
    coverage_pct: float
    scope: str


class QueueEntry(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: int
    game_id: int
    position: int
    title: str
    goal: Literal['completionist'] = 'completionist'
    available: bool
    estimated_hours: Optional[float]
    estimate_kind: str
    progress_pct: Optional[float] = None
    progress_source: str = 'unknown'
    is_completed: bool = False
    play_state: str = 'not_started'
    manual_play_state: str = 'not_started'
    completion_reason: Optional[Literal['manual','platinum','trophy_progress']] = None
    remaining_hours: Optional[float] = None
    hltb_main_hours: Optional[float] = None
    hltb_extra_hours: Optional[float] = None
    hltb_completionist_hours: Optional[float] = None
    platinum_hours: Optional[float] = None


class QueueResponse(QueueSummary):
    entries: List[QueueEntry]
    summary: QueueSummary
