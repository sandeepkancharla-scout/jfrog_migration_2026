import json
import os
import threading
from pathlib import Path

import requests
import streamlit as st


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "approvals.json"

FINAL_WORKFLOW = "final-deploy.yml"
DEFAULT_GITHUB_REF = "main"

DB_LOCK = threading.Lock()


# ============================================================
# DATABASE FUNCTIONS
# ============================================================

def load_db():
    if not DB_FILE.exists():
        return {}

    try:
        with DB_LOCK:
            with open(DB_FILE, "r", encoding="utf-8") as file:
                return json.load(file)

    except json.JSONDecodeError:
        st.error("approvals.json contains invalid JSON.")
        st.stop()


def save_db(data):
    temp_file = DB_FILE.with_suffix(".tmp")

    with DB_LOCK:
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                indent=2
            )

        temp_file.replace(DB_FILE)


# ============================================================
# STATUS LOGIC
# ============================================================

def update_overall_status(record):
    approvals = record.get("approvals", {})

    statuses = list(approvals.values())

    # If anybody rejects, deployment is rejected.
    if "REJECTED" in statuses:
        record["status"] = "REJECTED"
        return

    # Everyone must approve.
    if (
        statuses
        and all(
            status == "APPROVED"
            for status in statuses
        )
    ):
        record["status"] = "APPROVED"
        return

    record["status"] = "PENDING"


# ============================================================
# GITHUB CONFIGURATION
# ============================================================

def get_github_configuration():

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
# TRIGGER WORKFLOW 2
# ============================================================

def trigger_final_deployment(request_id, record):

    (
        github_token,
        github_owner,
        github_repo
    ) = get_github_configuration()

    github_ref = os.getenv(
        "GH_REF",
        DEFAULT_GITHUB_REF
    )

    url = (
        f"https://api.github.com/repos/"
        f"{github_owner}/{github_repo}/"
        f"actions/workflows/"
        f"{FINAL_WORKFLOW}/dispatches"
    )

    headers = {
        "Accept":
            "application/vnd.github+json",

        "Authorization":
            f"Bearer {github_token}",

        "X-GitHub-Api-Version":
            "2022-11-28"
    }

    payload = {
        "ref": github_ref,

        "inputs": {

            "request_id":
                str(request_id),

            "build_number":
                str(
                    record.get(
                        "build_number",
                        ""
                    )
                ),

            "staging_path":
                str(
                    record.get(
                        "staging_path",
                        ""
                    )
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
            "Workflow dispatch failed. "
            f"HTTP {response.status_code}: "
            f"{response.text}"
        )

    return True


# ============================================================
# TRIGGER ONLY ONCE
# ============================================================

def attempt_final_deployment(db, request_id):

    record = db[request_id]

    # Must be fully approved.
    if record.get("status") != "APPROVED":
        return False, None

    # Already dispatched.
    if record.get(
        "final_deploy_triggered",
        False
    ):
        return False, None

    # Don't dispatch twice while a call is already happening.
    if record.get(
        "final_deploy_trigger_in_progress",
        False
    ):
        return False, None

    # Mark as dispatching.
    record[
        "final_deploy_trigger_in_progress"
    ] = True

    record[
        "final_deploy_trigger_error"
    ] = None

    db[request_id] = record

    save_db(db)

    try:

        trigger_final_deployment(
            request_id,
            record
        )

        # GitHub accepted Workflow 2.
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
# STREAMLIT PAGE
# ============================================================

st.set_page_config(
    page_title="JFrog Deployment Approval",
    page_icon="✅",
    layout="centered"
)

st.title("JFrog Deployment Approval")

st.caption(
    "Scout JFrog Migration Approval"
)


# ============================================================
# LOAD DATABASE
# ============================================================

db = load_db()

if not db:

    st.info(
        "No deployment approval requests exist."
    )

    st.stop()


# ============================================================
# URL PARAMETERS
#
# Example:
#
# http://server:8501/
# ?request_id=CW35-001
# &approver=user@company.com
# ============================================================

request_id = st.query_params.get(
    "request_id"
)

approver = st.query_params.get(
    "approver"
)


# ============================================================
# ADMIN / TEST VIEW
# ============================================================

if not request_id:

    st.subheader(
        "Approval Requests"
    )

    request_id = st.selectbox(
        "Select Approval Request",
        list(db.keys())
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

approvals = record.get(
    "approvals",
    {}
)

approver_link_mode = (
    approver is not None
)


# ============================================================
# VALIDATE APPROVER
# ============================================================

if approver_link_mode:

    if approver not in approvals:

        st.error(
            "This approval link is not valid "
            "for this deployment."
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

    st.write(
        "**Request ID**"
    )

    st.code(
        request_id
    )


with col2:

    st.write(
        "**Build Number**"
    )

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
# APPROVAL STATUS
# ============================================================

st.divider()

st.subheader(
    "Approval Status"
)

status = record.get(
    "status",
    "PENDING"
)


if status == "APPROVED":

    st.success(
        "ALL APPROVALS RECEIVED"
    )


elif status == "REJECTED":

    st.error(
        "DEPLOYMENT REJECTED"
    )


else:

    st.warning(
        "WAITING FOR APPROVALS"
    )


# ============================================================
# COUNTS
# ============================================================

total_count = len(
    approvals
)

approved_count = sum(
    value == "APPROVED"
    for value in approvals.values()
)

rejected_count = sum(
    value == "REJECTED"
    for value in approvals.values()
)

pending_count = sum(
    value == "PENDING"
    for value in approvals.values()
)


col1, col2, col3 = st.columns(3)

with col1:

    st.metric(
        "Approved",
        f"{approved_count}/{total_count}"
    )


with col2:

    st.metric(
        "Pending",
        pending_count
    )


with col3:

    st.metric(
        "Rejected",
        rejected_count
    )


# ============================================================
# APPROVERS
# ============================================================

st.divider()

st.subheader(
    "Approvers"
)


for person, approval_status in approvals.items():

    col1, col2 = st.columns(
        [3, 1]
    )

    with col1:

        st.write(
            person
        )


    with col2:

        if approval_status == "APPROVED":

            st.success(
                "APPROVED"
            )

        elif approval_status == "REJECTED":

            st.error(
                "REJECTED"
            )

        else:

            st.warning(
                "PENDING"
            )


# ============================================================
# APPROVER-SPECIFIC PAGE
# ============================================================

st.divider()


if approver_link_mode:

    st.subheader(
        "Your Decision"
    )

    st.write(
        f"Approver: **{approver}**"
    )

    current_status = approvals[
        approver
    ]


    # ========================================================
    # ALREADY APPROVED
    # ========================================================

    if current_status == "APPROVED":

        st.success(
            "You have already approved "
            "this deployment."
        )


    # ========================================================
    # ALREADY REJECTED
    # ========================================================

    elif current_status == "REJECTED":

        st.error(
            "You have already rejected "
            "this deployment."
        )


    # ========================================================
    # DEPLOYMENT ALREADY REJECTED
    # ========================================================

    elif record["status"] == "REJECTED":

        st.error(
            "This deployment has already "
            "been rejected."
        )


    # ========================================================
    # APPROVE / REJECT
    # ========================================================

    else:

        approve_column, reject_column = (
            st.columns(2)
        )


        with approve_column:

            approve_clicked = st.button(
                "Approve",
                type="primary",
                use_container_width=True
            )


        with reject_column:

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

            # First save approval.
            save_db(db)

            deployment_triggered = False
            deployment_error = None


            # ================================================
            # LAST APPROVAL?
            #
            # If yes, trigger Workflow 2 IMMEDIATELY.
            # ================================================

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

    st.info(
        "This is the administrative view. "
        "Approvers use their individual "
        "approval links."
    )


# ============================================================
# FINAL DEPLOYMENT STATUS
# ============================================================

st.divider()

st.subheader(
    "Final Deployment"
)

# Load latest status again.
db = load_db()

record = db[
    request_id
]


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

if record["status"] == "REJECTED":

    st.error(
        "Final deployment blocked."
    )

    st.write(
        "At least one required approval "
        "was rejected."
    )


# ============================================================
# PENDING
# ============================================================

elif record["status"] == "PENDING":

    st.warning(
        "Waiting for remaining approvals."
    )

    pending_people = [

        person

        for person, person_status

        in record[
            "approvals"
        ].items()

        if person_status == "PENDING"
    ]

    for person in pending_people:

        st.write(
            f"Waiting for: {person}"
        )


# ============================================================
# APPROVED
# ============================================================

elif record["status"] == "APPROVED":

    st.success(
        "All approvers approved."
    )


    if final_triggered:

        st.success(
            "Workflow 2 has been triggered."
        )


    elif trigger_in_progress:

        st.info(
            "Workflow 2 is being triggered."
        )


    elif trigger_error:

        st.error(
            "All approvals were received, "
            "but Workflow 2 failed to start."
        )

        st.code(
            trigger_error
        )


# ============================================================
# SUCCESS MESSAGE
# ============================================================

if st.session_state.pop(
    "deployment_started",
    False
):

    st.success(
        "All approvals received. "
        "Final deployment workflow started."
    )


# ============================================================
# ERROR MESSAGE
# ============================================================

deployment_error = (
    st.session_state.pop(
        "deployment_error",
        None
    )
)

if deployment_error:

    st.error(
        "Approval was recorded, "
        "but Workflow 2 could not be started."
    )

    st.code(
        deployment_error
    )
