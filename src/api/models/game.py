from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator
from typing import Optional, Literal
from datetime import date, datetime
from src.api.utils.queue import estimate_entry


class GameCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=500)
    platform: str = Field(default="PS5", min_length=1, max_length=50)
    ownership: Literal['owned', 'wanted', 'available'] = 'owned'
    igdb_id: Optional[int] = None
    psn_id: Optional[str] = None
    psnprofiles_slug: Optional[str] = None

    @field_validator('title', 'platform')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('Value must not be blank')
        return value.strip()


class UserGameCreate(BaseModel):
    game_id: int
    status: str = "owned"
    purchase_date: Optional[date] = None
    purchase_price: Optional[float] = None
    notes: Optional[str] = None


class UserGameStatusUpdate(BaseModel):
    status: str


class CollectionUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ownership: Optional[Literal['owned', 'wanted', 'available']] = None
    play_state: Optional[Literal['not_started', 'playing', 'paused', 'finished', 'dropped']] = None
    notes: Optional[str] = None
    next_action: Optional[str] = None
    platinum_feasibility: Optional[Literal['attainable', 'blocked', 'unknown', 'not_applicable']] = None
    platinum_blocker_reason: Optional[str] = None
    platinum_evidence_url: Optional[str] = None

    @model_validator(mode='after')
    def no_null_states(self):
        for key in ('ownership', 'play_state', 'platinum_feasibility'):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f'{key} cannot be null')
        return self


class GameResponse(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: int
    title: str
    platform: str
    ownership: Optional[str] = None
    play_state: Optional[str] = None
    manual_play_state: str = 'not_started'
    completion_reason: Optional[Literal['manual','platinum','trophy_progress']] = None
    goal: Literal['completionist'] = 'completionist'
    platinum_earned: bool = False
    progress_pct: Optional[float] = None
    progress_source: str = 'unknown'
    is_completed: bool = False
    remaining_hours: Optional[float] = None
    estimated_hours: Optional[float] = None
    estimate_kind: str = 'unknown'
    purchase_price: Optional[float] = None
    hltb_main_hours: Optional[float] = None
    hltb_complete_hours: Optional[float] = None
    hltb_platinum_hours: Optional[float] = None
    hltb_extra_hours: Optional[float] = None
    hltb_completionist_hours: Optional[float] = None
    platinum_hours: Optional[float] = None
    psn_progress: Optional[int] = None
    psn_earned_trophies: Optional[int] = None
    psn_earned_platinum: Optional[int] = None
    psn_total_trophies: Optional[int] = None
    psn_summary_at: Optional[datetime] = None

    @model_validator(mode='before')
    @classmethod
    def derive_completionist_progress(cls,value):
        return estimate_entry(value) if isinstance(value,dict) else value
