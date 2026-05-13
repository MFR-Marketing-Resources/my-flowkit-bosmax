from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


PlanningStatus = Literal["PASS", "WARN", "FAIL"]
SourceRoute = Literal["PRODUCT_DRIVEN_AUTO", "REGISTRY_DRIVEN_MANUAL_ASSISTED"]
DestinationMode = Literal["TEXT_TO_VIDEO", "FRAMES", "INGREDIENTS", "IMAGE"]
OutputType = Literal["IMAGE_PROMPT", "VIDEO_9_SECTION_PROMPT", "PROMPT_BLOCK_PLAN"]
AssetRole = Literal["SUBJECT_CHARACTER", "PRODUCT", "SCENE", "STYLE", "START_FRAME", "END_FRAME"]
AssetSource = Literal["FASTMOSS", "REGISTERED_PRODUCT", "GENERATED_ASSET", "UPLOADED_IMAGE", "REGISTRY"]
ExtensionStrategy = Literal["NONE", "EXTEND_CONTINUITY", "INSERT_JUMP_TO", "MIXED"]
ExecutionStatus = Literal["PLANNED"]


class PromptAssetBinding(BaseModel):
    asset_role: str
    asset_source: str
    asset_id: Optional[str] = None
    source_url: Optional[str] = None


class PromptAssetRequirement(BaseModel):
    asset_role: str
    required: bool
    satisfied: bool
    reason: str


class PromptPlanBlock(BaseModel):
    block_index: int
    flow_action: str
    depends_on_block_index: Optional[int] = None
    prompt_role: str
    transition_intent: str
    continuation_prefix: Optional[str] = None
    execution_status: ExecutionStatus = "PLANNED"


class PromptPlanningRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_route: Optional[str] = None
    destination_mode: Optional[str] = None
    output_type: Optional[str] = None
    product_id: Optional[str] = None
    asset_bindings: list[PromptAssetBinding] = Field(default_factory=list)
    target_duration_seconds: int = 8
    block_duration_seconds: int = 8
    extension_strategy: Optional[str] = "NONE"


class PromptPlanningResult(BaseModel):
    planning_status: PlanningStatus
    source_route: Optional[str] = None
    destination_mode: Optional[str] = None
    output_type: Optional[str] = None
    target_duration_seconds: Optional[int] = None
    block_duration_seconds: Optional[int] = None
    block_count: int = 0
    extension_strategy: Optional[str] = None
    asset_requirements: list[PromptAssetRequirement] = Field(default_factory=list)
    asset_bindings: list[PromptAssetBinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    blocks: list[PromptPlanBlock] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
