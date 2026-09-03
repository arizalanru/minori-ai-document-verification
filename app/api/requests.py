from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Create(Payload):
    rule_version_id: Literal["demo-core-v1", "demo-full-v1"] = "demo-core-v1"


class Revision(Payload):
    expected_revision: int = Field(ge=0)


class Review(Revision):
    document_version_id: str
    action: Literal["verify", "request_reupload"]
    corrections: dict[str, str | None] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=2000)
    reviewed_page: Literal[1] = 1


class Confirm(Revision):
    evaluation_id: str
    reason: str = Field(min_length=1, max_length=2000)


class ProfileChange(Revision):
    rule_version_id: Literal["demo-core-v1", "demo-full-v1"]
    reason: str = Field(min_length=1, max_length=2000)
