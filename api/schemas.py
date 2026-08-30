from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

class BranchCreate(BaseModel):
    name: str = Field(..., description="Name of the new branch")
    source_branch: str = Field("main", description="Name of the source branch")

class BranchCheckout(BaseModel):
    name: str = Field(..., description="Name of the branch to checkout")

class CommitCreate(BaseModel):
    branch_name: str = Field(..., description="Branch to commit to")
    message: str = Field(..., description="Commit message")
    author: str = Field(..., description="Author of the commit")
    changes: Optional[List[Dict[str, Any]]] = Field(None, description="Changes to commit")

class QueryRequest(BaseModel):
    query: str = Field(..., description="Query string")
    as_of_commit: Optional[str] = None
    as_of_timestamp: Optional[str] = None
    branch_name: Optional[str] = "main"

class RollbackRequest(BaseModel):
    branch_name: str = Field(..., description="Branch to rollback")
    target_commit_hash: str = Field(..., description="Commit hash to rollback to")
    author: str = Field(..., description="Author of the rollback commit")

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None

class ErrorResponse(BaseModel):
    error: ErrorDetail

class MergeResolution(BaseModel):
    key: str = Field(..., description="Resolution key in format 'table_name:row_id'")
    data: Optional[Dict[str, Any]] = Field(None, description="Resolved data (null = delete)")

class MergeRequest(BaseModel):
    target_branch: str = Field(..., description="Branch to merge INTO")
    source_branch: str = Field(..., description="Branch to merge FROM")
    author: str = Field(..., description="Author performing the merge")
    resolutions: Optional[List[MergeResolution]] = Field(None, description="Conflict resolutions")

