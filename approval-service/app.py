import os

import requests
import streamlit as st

from storage import load_database, save_database


FINAL_WORKFLOW = os.getenv(
    "FINAL_WORKFLOW",
    "final-deploy.yml"
)

GITHUB_REF = os.getenv(
    "GH_REF",
    "main"
)


def calculate_overall_status(
    record: dict
) -> str:

    approvals = record.get(
        "approvals",
        {}
    )

    statuses = list(
        approvals.values()
    )

    if "REJECTED" in statuses:
        return "REJECTED"

    if (
        statuses
        and all(
            status == "APPROVED"
            for status in statuses
        )
    ):
        return "APPROVED"

    return "PENDING"


def get_github_configuration() -> tuple[
    str,
    str,
    str
]:

    github_token = os.getenv(
        "GH_TOKEN"
    )

    github_owner = os.getenv(
        "GH_OWNER"
    )

    github_repo = os.getenv(
        "GH_REPO"
    )

    missing_values = []

    if not github_token:
        missing_values.append(
            "GH_TOKEN"
        )

    if not github_owner:
        missing_values.append(
            "GH_OWNER"
        )

    if not github_repo:
        missing_values.append(
            "GH_REPO"
        )

    if missing_values:

        raise RuntimeError(
            "Missing GitHub configuration: "
            + ", ".join(missing_values)
        )

    return (
        github_token,
        github_owner,
        github_repo
    )


def dispatch_final_workflow(
    request_id: str,
    record: dict
) -> None:

    (
        github_token,
        github_owner,
        github_repo
    ) = get_github_configuration()

    workflow_url = (
        "https://api.github.com/repos/"
        f"{github_owner}/{github_repo}/"
        "actions/workflows/"
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

        "ref":
            GITHUB_REF,

        "inputs": {

            "request_id":
                request_id,

            "source_artifactory":
                record[
                    "source_artifactory"
                ],

            "build_number":
                record[
                    "build_number"
                ],

            "staging_path":
                record[
                    "staging_path"
                ],

            "target_artifactory":
                record[
                    "target_artifactory"
                ]
        }
    }

    response = requests.post(
        workflow_url,
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


def attempt_final_deployment(
    database: dict,
    request_id: str
) -> tuple[bool, str | None]:

    record = database[
        request_id
    ]

    if (
        record.get("status")
        != "APPROVED"
    ):
        return False, None

    if record.get(
        "final_deploy_triggered",
        False
    ):
        return False, None

    if record.get(
        "final_deploy_trigger_in_progress",
        False
    ):
        return False, None

    record[
        "final_deploy_trigger_in_progress"
    ] = True

    record[
        "final_deploy_trigger_error"
    ] = None

    database[
        request_id
    ] = record

    save_database(
        database
    )

    try:

        dispatch_final_workflow(
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

        database[
            request_id
        ] = record

        save_database(
            database
        )

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

        database[
            request_id
        ] = record

        save_database(
            database
        )

        return False, str(error)


st.set_page_config(
    page_title="JFrog Deployment Approval",
    page_icon="✅",
    layout="centered"
)

st.title(
    "JFrog Deployment Approval"
)

st.caption(
    "Scout JFrog Migration Approval"
)


database = load_database()

if not database:

    st.info(
        "No approval requests are available."
    )

    st.stop()


request_id = st.query_params.get(
    "request_id"
)

approver = st.query_params.get(
    "approver"
)


if not request_id:

    st.subheader(
        "Approval Requests"
    )

    request_id = st.selectbox(
        "Select Approval Request",
        list(database.keys())
    )


if request_id not in database:

    st.error(
        "Approval request was not found."
    )

    st.stop()


record = database[
    request_id
]

approvals = record.get(
    "approvals",
    {}
)


if approver:

    if approver not in approvals:

        st.error(
            "This approval link is invalid."
        )

        st.stop()


st.subheader(
    "Deployment Information"
)

st.write(
    "**Build Number**"
)

st.code(
    record.get(
        "build_number",
        ""
    )
)

st.write(
    "**Source Artifactory**"
)

st.code(
    record.get(
        "source_artifactory",
        ""
    )
)

st.write(
    "**Staging Path**"
)

st.code(
    record.get(
        "staging_path",
        ""
    )
)

st.write(
    "**Final Target Artifactory**"
)

st.code(
    record.get(
        "target_artifactory",
        ""
    )
)


record["status"] = (
    calculate_overall_status(
        record
    )
)

database[
    request_id
] = record

save_database(
    database
)


st.divider()

st.subheader(
    "Approval Status"
)


if record["status"] == "APPROVED":

    st.success(
        "ALL APPROVALS RECEIVED"
    )

elif record["status"] == "REJECTED":

    st.error(
        "DEPLOYMENT REJECTED"
    )

else:

    st.warning(
        "WAITING FOR APPROVALS"
    )


approved_count = sum(
    status == "APPROVED"
    for status in approvals.values()
)

pending_count = sum(
    status == "PENDING"
    for status in approvals.values()
)

rejected_count = sum(
    status == "REJECTED"
    for status in approvals.values()
)

total_count = len(
    approvals
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


st.divider()

st.subheader(
    "Approvers"
)


for person, approval_status in approvals.items():

    status_col1, status_col2 = st.columns(
        [3, 1]
    )

    with status_col1:

        st.write(
            person
        )

    with status_col2:

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


if approver:

    st.divider()

    st.subheader(
        "Your Decision"
    )

    st.write(
        f"Approver: **{approver}**"
    )

    current_status = approvals[
        approver
    ]

    if current_status == "APPROVED":

        st.success(
            "You have already approved."
        )

    elif current_status == "REJECTED":

        st.error(
            "You have already rejected."
        )

    elif record["status"] == "REJECTED":

        st.error(
            "This deployment was already rejected."
        )

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


        if approve_clicked:

            record[
                "approvals"
            ][approver] = "APPROVED"

            record["status"] = (
                calculate_overall_status(
                    record
                )
            )

            database[
                request_id
            ] = record

            save_database(
                database
            )

            if (
                record["status"]
                == "APPROVED"
            ):

                (
                    deployment_started,
                    deployment_error
                ) = attempt_final_deployment(
                    database,
                    request_id
                )

                if deployment_started:

                    st.session_state[
                        "workflow_started"
                    ] = True

                if deployment_error:

                    st.session_state[
                        "workflow_error"
                    ] = deployment_error

            st.rerun()


        if reject_clicked:

            record[
                "approvals"
            ][approver] = "REJECTED"

            record["status"] = (
                calculate_overall_status(
                    record
                )
            )

            database[
                request_id
            ] = record

            save_database(
                database
            )

            st.rerun()


st.divider()

st.subheader(
    "Final Deployment"
)


database = load_database()

record = database[
    request_id
]


if record["status"] == "REJECTED":

    st.error(
        "Final deployment is blocked."
    )


elif record["status"] == "PENDING":

    st.warning(
        "Final deployment is waiting "
        "for all required approvals."
    )


elif record["status"] == "APPROVED":

    if record.get(
        "final_deploy_triggered",
        False
    ):

        st.success(
            "Workflow 2 was triggered successfully."
        )

    elif record.get(
        "final_deploy_trigger_in_progress",
        False
    ):

        st.info(
            "Starting Workflow 2..."
        )

    elif record.get(
        "final_deploy_trigger_error"
    ):

        st.error(
            "All approvals were received, "
            "but Workflow 2 failed to start."
        )

        st.code(
            record[
                "final_deploy_trigger_error"
            ]
        )


if st.session_state.pop(
    "workflow_started",
    False
):

    st.success(
        "All approvals received. "
        "Final deployment started."
    )


workflow_error = st.session_state.pop(
    "workflow_error",
    None
)

if workflow_error:

    st.error(
        "Workflow 2 could not be started."
    )

    st.code(
        workflow_error
    )
