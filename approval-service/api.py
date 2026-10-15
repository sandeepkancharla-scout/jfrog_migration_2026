import os
import uuid
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from storage import load_database, save_database


app = FastAPI(
    title="JFrog Approval API",
    version="1.0.0"
)


DEFAULT_APPROVAL_APP_URL = (
    "http://localhost:8501"
)


class ApprovalRequest(BaseModel):

    source_artifactory: str = Field(
        min_length=1
    )

    build_number: str = Field(
        min_length=1
    )

    staging_path: str = Field(
        min_length=1
    )

    target_artifactory: str = Field(
        min_length=1
    )


def get_approvers() -> listraw_approvers = os.getenv(
        "APPROVERS",
        ""
    )

    approvers = [
        value.strip()
        for value in raw_approvers.split(",")
        if value.strip()
    ]

    if not approvers:

        raise HTTPException(
            status_code=500,
            detail=(
                "APPROVERS environment variable "
                "is not configured."
            )
        )

    return approvers


def get_approval_app_url() -> str:

    return os.getenv(
        "APPROVAL_APP_URL",
        DEFAULT_APPROVAL_APP_URL
    ).rstrip("/")


@app.get("/health")
def health() -> dict:

    return {
        "status": "healthy"
    }


@app.post("/approval/create")
def create_approval_request(
    request: ApprovalRequest
) -> dict:

    approvers = get_approvers()

    request_id = str(
        uuid.uuid4()
    )

    approval_statuses = {
        approver: "PENDING"
        for approver in approvers
    }

    record = {

        "request_id":
            request_id,

        "source_artifactory":
            request.source_artifactory,

        "build_number":
            request.build_number,

        "staging_path":
            request.staging_path,

        "target_artifactory":
            request.target_artifactory,

        "status":
            "PENDING",

        "final_deploy_triggered":
            False,

        "final_deploy_trigger_in_progress":
            False,

        "final_deploy_trigger_error":
            None,

        "approvals":
            approval_statuses
    }

    database = load_database()

    database[
        request_id
    ] = record

    save_database(
        database
    )

    app_url = get_approval_app_url()

    approval_links = []

    for approver in approvers:

        approval_url = (
            f"{app_url}/"
            f"?request_id={quote(request_id)}"
            f"&approver={quote(approver)}"
        )

        approval_links.append(
            {
                "approver": approver,
                "url": approval_url
            }
        )

    return {

        "request_id":
            request_id,

        "status":
            "PENDING",

        "build_number":
            request.build_number,

        "staging_path":
            request.staging_path,

        "target_artifactory":
            request.target_artifactory,

        "approval_links":
            approval_links
    }


@app.get("/approval/{request_id}")
def get_approval_request(
    request_id: str
) -> dict:

    database = load_database()

    record = database.get(
        request_id
    )

    if record is None:

        raise HTTPException(
            status_code=404,
            detail="Approval request was not found."
        )

    return record
