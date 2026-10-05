from datetime import datetime
from typing import Optional
from pydantic import BaseModel,ConfigDict
from src.api.models.game import GameResponse
from src.api.models.backlog import QueueSummary,QueueEntry


class LibraryCounts(BaseModel):
    owned_count:int
    available_count:int
    wishlist_count:int
    playing_count:int
    completed_count:int
    platinum_count:int
    total_count:int


class TrophyStatistics(BaseModel):
    model_config=ConfigDict(extra='allow')
    total_trophies:int
    earned_trophies:int
    loaded_game_count:int
    collection_game_count:int
    completion_rate_pct:Optional[float]
    loaded_completion_rate_pct:Optional[float]
    scope:str


class MonthActivity(BaseModel):
    earned_trophies:int


class Milestone(BaseModel):
    game_id:int
    title:str
    name:str
    earned_at:datetime


class Insights(BaseModel):
    playing:list[GameResponse]
    next_up:list[QueueEntry]
    finish_soon:list[QueueEntry]
    blocked:list[GameResponse]


class StatisticsResponse(BaseModel):
    library:LibraryCounts
    trophies:TrophyStatistics
    backlog:QueueSummary
    backlog_estimated_hours:float
    this_month:MonthActivity
    milestones:list[Milestone]
    insights:Insights
