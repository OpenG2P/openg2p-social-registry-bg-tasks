from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class G2PQueBackgroundTask(BaseModel):
    id: Optional[int]
    task_type: str
    worker_payload: dict
    task_status: TaskStatus
    queued_datetime: datetime
    number_of_attempts: int
    last_attempt_datetime: Optional[datetime]
    last_attempt_error_code: Optional[str]


class ResPartnerModel(BaseModel):
    registrant_id: int
    unique_id: Optional[str]
