from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class TrophyEarn(BaseModel):
    notes: Optional[str] = None
