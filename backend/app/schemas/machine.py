from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MachineCreate(BaseModel):
    name: str
    hostname: str
    os_type: Optional[str] = None
    os_version: Optional[str] = None


class MachineOut(BaseModel):
    id: int
    name: str
    hostname: str
    os_type: Optional[str]
    os_version: Optional[str]
    agent_token: str
    is_active: bool
    last_seen: Optional[datetime]
    owner_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class MachineUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
