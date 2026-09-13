from pydantic import BaseModel, Field
from typing import Optional, Any, Literal
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
    os_pretty: Optional[str] = None
    system_info: Optional[Any] = None
    agent_version: Optional[str] = None
    ai_privacy: Optional[str] = "any"
    focus_mode_until: Optional[datetime] = None
    focus_mode_reason: Optional[str] = None
    network_isolated: Optional[bool] = False
    collection_interval: Optional[int] = None
    is_demo: Optional[bool] = False
    last_boot_time: Optional[float] = None
    preferred_interval: Optional[int] = None
    realtime_until: Optional[datetime] = None

    class Config:
        from_attributes = True


class MachineUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    ai_privacy: Optional[Literal["any", "local_only", "no_ai"]] = None
    # Nulo = Automática (o servidor decide entre 10s e 60s conforme o que acontece)
    preferred_interval: Optional[Literal[10, 30, 60]] = None


class FocusModeRequest(BaseModel):
    # 0 encerra o modo agora
    minutes: int = Field(default=60, ge=0, le=720)
    reason: Optional[str] = Field(default=None, max_length=80)


class RealtimeRequest(BaseModel):
    # 0 encerra o tempo real agora
    minutes: int = Field(default=30, ge=0, le=30)


class EnrollmentCodeOut(BaseModel):
    code: str
    expires_at: datetime

    class Config:
        from_attributes = True


class BulkKeyCreate(BaseModel):
    label: Optional[str] = None
    max_uses: Optional[int] = None  # None = ilimitado
    expires_days: int = 365


class BulkKeyOut(BaseModel):
    id: int
    code: str
    label: Optional[str]
    max_uses: Optional[int]
    use_count: int
    revoked: bool
    expires_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class AgentEnrollRequest(BaseModel):
    code: str
    hostname: str
    os_type: Optional[str] = None
    os_version: Optional[str] = None
    name: Optional[str] = None


class AgentEnrollResponse(BaseModel):
    machine_id: int
    machine_name: str
    agent_token: str
