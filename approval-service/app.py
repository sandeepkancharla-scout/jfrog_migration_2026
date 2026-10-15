import json
import os
from pathlib import Path

import requests
import streamlit as st


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "approvals.json"

FINAL_WORKFLOW = "final-deploy.yml"
GITHUB_REF = "main"


# ============================================================
# DATABASE
# ============================================================

def load_db():
    if not DB_FILE.exists():
        return {}

    try:
        with open(DB_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

    except json.JSONDecodeError:
        st.error("approvals.json contains invalid JSON.")
        st.stop()


def save_db(data):
    """
    Write through a temporary file so that approvals.json
    is not left partially written.
    """

    temp_file = DB_FILE.with_suffix(".tmp")

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)

    temp_file.replace(DB_FILE)


# ============================================================
# APPROVAL STATUS
# ============================================================

def update_overall_status(record):
    approvals = record.get("approvals", {})

    statuses = list(approvals.values())

    # One rejection blocks deployment.
    if "REJECTED" in statuses:
        record["status"] = "REJECTED"

    # Everyone must approve.
    elif statuses and all(
        status == "APPROVED"
        for status in statuses
    ):
        record["status"] = "APPROVED"

    else:
        record["status"] = "PENDING"


# ============================================================
# GITHUB CONFIGURATION
# ============================================================

def get_github_configuration():
    """
    Uses the exact variable names you created:

        GH_TOKEN
        GH_OWNER
        GH_REPO
    """

    github_token = os.getenv("GH_TOKEN")
    github_owner = os.getenv("GH_OWNER")
    github_repo = os.getenv("GH_REPO")

    missing = []

    if not github_token:
        missing.append("GH_TOKEN")

    if not github_owner:
        missing.append("GH_OWNER")

    if not github_repo:
        missing.append("GH_REPO")

    if missing:
        raise RuntimeError(
            "Missing GitHub configuration: "
            + ", ".join(missing)
        )

    return (
        github_token,
        github_owner,
        github_repo
    )


# ============================================================
# TRIGGER FINAL WORKFLOW
# ============================================================

def trigger_final_deployment(request_id, record):
    (
        github_token,
        github_owner,
        github_repo
    ) = get_github_configuration()

    url = (
        f"https://api.github.com/repos/"
        f"{github_owner}/{github_repo}/"
        f"actions/workflows/"
        f"{FINAL_WORKFLOW}/dispatches"
    )

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    payload = {
        "ref": GITHUB_REF,

        "inputs": {
            "request_id": str(request_id),

            "build_number": str(
                record.get("build_number", "")
            ),

            "staging_path": str(
                record.get("staging_path", "")
            )
        }
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30
    )

    if response.status_code != 204:
        raise RuntimeError(
            "GitHub workflow dispatch failed. "
            f"HTTP {response.status_code}: "
            f"{response.text}"
        )

    return True


# ============================================================
# DISPATCH FINAL WORKFLOW ONCE
# ============================================================

def attempt_final_deployment(db, request_id):
    record = db[request_id]

    # Not approved yet.
    if record.get("status") != "APPROVED":
        return False, None

    # Already triggered.
    if record.get(
        "final_deploy_triggered",
        False
    ):
        return False, None

    # A previous trigger attempt is active.
    if record.get(
        "final_deploy_trigger_in_progress",
        False
    ):
        return False, None

    record[
        "final_deploy_trigger_in_progress"
    ] = True

    db[request_id] = record
    save_db(db)

    try:
        trigger_final_deployment(
            request_id,
            record
        )

        record[
            "final_deploy_triggered"
        ] = True

        record[
            "final_deploy_trigger_in_progress"
        ] = False

        record[
            "final_deploy_trigger_error"
        ] = None

        db[request_id] = record
        save_db(db)

        return True, None

    except Exception as error:
        record[
            "final_deploy_triggered"
        ] = False

        record[
            "final_deploy_trigger_in_progress"
        ] = False

        record[
            "final_deploy_trigger_error"
        ] = str(error)

        db[request_id] = record
        save_db(db)

        return False, str(error)


# ============================================================
# STREAMLIT CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="JFrog Deployment Approval",
    page_icon="✅",
    layout="centered"
)

st.title("JFrog Deployment Approval")

st.caption(
    "Scout JFrog migration approval"
)


# ============================================================
# LOAD APPROVAL DATABASE
# ============================================================

db = load_db()

if not db:
    st.info(
        "There are currently no "
        "deployment approval requests."
    )
    st.stop()


# ============================================================
# URL PARAMETERS
#
# Example:
#
# http://SERVER:8501/
# ?request_id=CW35-001
# &approver=person1@company.com
# ============================================================

request_id = st.query_params.get(
    "request_id"
)

approver = st.query_params.get(
    "approver"
)


# ============================================================
# TEST / ADMIN VIEW
# ============================================================

if not request_id:
    st.subheader("Approval Requests")

    request_ids = list(db.keys())

    request_id = st.selectbox(
        "Select Approval Request",
        request_ids
    )


# ============================================================
# VALIDATE REQUEST
# ============================================================

if request_id not in db:
    st.error(
        f"Approval request "
        f"'{request_id}' was not found."
    )
    st.stop()


record = db[request_id]

approver_link_mode = (
    approver is not None
)


# ============================================================
# VALIDATE APPROVER
# ============================================================

if approver_link_mode:
    approvals = record.get(
        "approvals",
        {}
    )

    if approver not in approvals:
        st.error(
            "This user is not listed "
            "as an approver for this deployment."
        )
        st.stop()


# ============================================================
# DEPLOYMENT INFORMATION
# ============================================================

st.subheader(
    "Deployment Information"
)

col1, col2 = st.columns(2)

with col1:
    st.write("**Request ID**")
    st.code(request_id)

with col2:
    st.write("**Build Number**")

    st.code(
        record.get(
            "build_number",
            "Not provided"
        )
    )


st.write(
    "**Staging JFrog Path**"
)

st.code(
    record.get(
        "staging_path",
        "Not provided"
    )
)


# ============================================================
# OVERALL STATUS
# ============================================================

st.divider()

st.subheader(
    "Overall Approval Status"
)

status = record.get(
    "status",
    "PENDING"
)

if status == "APPROVED":
    st.success("APPROVED")

elif status == "REJECTED":
    st.error("REJECTED")

else:
    st.warning("PENDING")


# ============================================================
# APPROVAL COUNTS
# ============================================================

approvals = record.get(
    "approvals",
    {}
)

total_count = len(approvals)

approved_count = sum(
    1
    for value in approvals.values()
    if value == "APPROVED"
)

rejected_count = sum(
    1
    for value in approvals.values()
    if value == "REJECTED"
)

pending_count = sum(
    1
    for value in approvals.values()
    if value == "PENDING"
)

st.write(
    f"**Approved:** "
    f"{approved_count} / {total_count}"
)

st.write(
    f"**Rejected:** "
    f"{rejected_count}"
)

st.write(
    f"**Pending:** "
    f"{pending_count}"
)


# ============================================================
# APPROVER STATUS LIST
# ============================================================

st.divider()

st.subheader("Approvers")

for person, approval_status in approvals.items():

    col1, col2 = st.columns(
        [3, 1]
    )

    with col1:
        st.write(person)

    with col2:

        if approval_status == "APPROVED":
            st.success("APPROVED")

        elif approval_status == "REJECTED":
            st.error("REJECTED")

        else:
            st.warning("PENDING")


# ============================================================
# APPROVER ACTION
# ============================================================

st.divider()

if approver_link_mode:

    st.subheader("Your Approval")

    st.write(
        f"Approver: **{approver}**"
    )

    current_status = approvals[
        approver
    ]

    # --------------------------------------------------------
    # ALREADY APPROVED
    # --------------------------------------------------------

    if current_status == "APPROVED":

        st.success(
            "You already approved "
            "this deployment."
        )

    # --------------------------------------------------------
    # ALREADY REJECTED
    # --------------------------------------------------------

    elif current_status == "REJECTED":

        st.error(
            "You already rejected "
            "this deployment."
        )

    # --------------------------------------------------------
    # SOMEBODY ELSE REJECTED
    # --------------------------------------------------------

    elif record.get("status") == "REJECTED":

        st.error(
            "This deployment request "
            "has already been rejected."
        )

    # --------------------------------------------------------
    # ALLOW APPROVAL
    # --------------------------------------------------------

    else:

        col1, col2 = st.columns(2)

        with col1:

            approve_clicked = st.button(
                "Approve",
                type="primary",
                use_container_width=True
            )

        with col2:

            reject_clicked = st.button(
                "Reject",
                use_container_width=True
            )


        # ====================================================
        # APPROVE
        # ====================================================

        if approve_clicked:

            record[
                "approvals"
            ][approver] = "APPROVED"

            update_overall_status(
                record
            )

            db[
                request_id
            ] = record

            # Save approval BEFORE attempting
            # to dispatch Workflow 2.
            save_db(db)

            deployment_triggered = False
            deployment_error = None

            if (
                record["status"]
                == "APPROVED"
            ):

                (
                    deployment_triggered,
                    deployment_error
                ) = attempt_final_deployment(
                    db,
                    request_id
                )

            if deployment_triggered:

                st.session_state[
                    "deployment_started"
                ] = True

            if deployment_error:

                st.session_state[
                    "deployment_error"
                ] = deployment_error

            st.rerun()


        # ====================================================
        # REJECT
        # ====================================================

        if reject_clicked:

            record[
                "approvals"
            ][approver] = "REJECTED"

            update_overall_status(
                record
            )

            db[
                request_id
            ] = record

            save_db(db)

            st.rerun()


else:

    if status == "PENDING":

        st.info(
            "Open an approver-specific URL "
            "to approve or reject this deployment."
        )


# ============================================================
# FINAL DEPLOYMENT STATUS
# ============================================================

st.divider()

st.subheader(
    "Final Deployment"
)

# Get latest state.
db = load_db()
record = db[request_id]

final_triggered = record.get(
    "final_deploy_triggered",
    False
)

trigger_in_progress = record.get(
    "final_deploy_trigger_in_progress",
    False
)

trigger_error = record.get(
    "final_deploy_trigger_error"
)


# ============================================================
# REJECTED
# ============================================================

if record.get("status") == "REJECTED":

    st.error(
        "Final deployment blocked."
    )

    st.write(
        "At least one required approver "
        "rejected this deployment."
    )


# ============================================================
# PENDING
# ============================================================

elif record.get("status") == "PENDING":

    st.warning(
        "Final deployment is waiting "
        "for approval."
    )

    pending_people = [
        person
        for person, approval_status
        in record["approvals"].items()
        if approval_status == "PENDING"
    ]

    for person in pending_people:

        st.write(
            f"Waiting for: {person}"
        )


# ============================================================
# APPROVED
# ============================================================

elif record.get("status") == "APPROVED":

    st.success(
        "All required approvers "
        "approved the deployment."
    )

    if final_triggered:

        st.success(
            "Final deployment workflow "
            "was triggered."
        )

    elif trigger_in_progress:

        st.info(
            "Final deployment trigger "
            "is being processed."
        )

    elif trigger_error:

        st.error(
            "Final deployment could not "
            "be triggered."
        )

        st.code(
            trigger_error
        )


# ============================================================
# SESSION MESSAGES
# ============================================================

if st.session_state.pop(
    "deployment_started",
    False
):

    st.success(
        "Final JFrog deployment workflow "
        "started successfully."
    )


deployment_error = (
    st.session_state.pop(
        "deployment_error",
        None
    )
)

if deployment_error:

    st.error(
        "Approval succeeded, but Workflow 2 "
        "could not be started."
    )

    st.code(
        deployment_error
    )