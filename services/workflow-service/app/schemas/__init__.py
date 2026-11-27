from datetime import datetime
from typing import Optional, Any, List
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, ConfigDict


class WorkflowBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class WorkflowCreate(WorkflowBase):
    definition: dict = Field(default_factory=dict)


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    definition: Optional[dict] = None
    status: Optional[str] = Field(None, pattern="^(draft|published|archived)$")


class WorkflowRead(WorkflowBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    status: str
    version: int
    definition: dict
    meta: dict = Field(validation_alias=AliasChoices("meta", "metadata"), serialization_alias="metadata")
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime]


class WorkflowVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID
    tenant_id: UUID
    version: int
    definition: dict
    changelog: Optional[str]
    created_by: Optional[UUID]
    created_at: datetime


class WorkflowExecutionBase(BaseModel):
    input_data: dict = Field(default_factory=dict)


class WorkflowExecutionCreate(WorkflowExecutionBase):
    workflow_id: UUID


class WorkflowExecutionRead(WorkflowExecutionBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID
    workflow_version: int
    tenant_id: UUID
    status: str
    output_data: Optional[dict]
    error_message: Optional[str]
    current_node_id: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime


class WorkflowExecutionLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    execution_id: UUID
    tenant_id: UUID
    node_id: str
    node_type: str
    level: str
    message: str
    input_data: Optional[dict]
    output_data: Optional[dict]
    error_message: Optional[str]
    duration_ms: int
    created_at: datetime


class NodeTemplateBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    node_type: str = Field(..., pattern="^(start|end|llm|rag|condition|transform|http|delay|parallel|merge)$")
    description: Optional[str] = None
    config_schema: dict = Field(default_factory=dict)
    default_config: dict = Field(default_factory=dict)
    icon: Optional[str] = None
    category: str = Field(default="general")


class NodeTemplateCreate(NodeTemplateBase):
    pass


class NodeTemplateRead(NodeTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    is_system: bool
    created_at: datetime
    updated_at: datetime


class WorkflowPublishRequest(BaseModel):
    changelog: Optional[str] = None


class WorkflowExecuteRequest(BaseModel):
    input_data: dict = Field(default_factory=dict)
    async_mode: bool = False


class WorkflowCancelRequest(BaseModel):
    reason: Optional[str] = None


class NodeDefinition(BaseModel):
    id: str
    type: str
    position: dict  # {x: number, y: number}
    config: dict
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)


class EdgeDefinition(BaseModel):
    id: str
    source: str
    target: str
    source_handle: Optional[str] = None
    target_handle: Optional[str] = None


class WorkflowDefinition(BaseModel):
    nodes: List[NodeDefinition] = Field(default_factory=list)
    edges: List[EdgeDefinition] = Field(default_factory=list)
    viewport: Optional[dict] = None  # {x, y, zoom}


class ExecutionResult(BaseModel):
    execution_id: UUID
    status: str
    output_data: Optional[dict] = None
    error_message: Optional[str] = None
    logs: List[WorkflowExecutionLogRead] = Field(default_factory=list)
    duration_ms: int = 0