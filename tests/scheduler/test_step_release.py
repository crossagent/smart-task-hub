from logic import step


def test_done_task_releases_resource_and_completes_assignment(
    assignment_status,
    create_active_assignment,
    create_task,
    resource_available,
):
    create_task("TSK-DONE-001", status="done")
    create_active_assignment("TSK-DONE-001")

    result = step()

    assert result["released"] == 1
    assert result["changed"] == 1
    assert resource_available("RES-OWNER-001") is True
    assert assignment_status("TSK-DONE-001") == "completed"


def test_failed_task_releases_resource_and_marks_assignment_failed(
    assignment_status,
    create_active_assignment,
    create_task,
    resource_available,
):
    create_task("TSK-FAIL-001", status="failed")
    create_active_assignment("TSK-FAIL-001")

    result = step()

    assert result["released"] == 1
    assert resource_available("RES-OWNER-001") is True
    assert assignment_status("TSK-FAIL-001") == "failed"


def test_blocked_task_releases_resource_and_marks_assignment_blocked(
    assignment_status,
    create_active_assignment,
    create_task,
    resource_available,
):
    create_task("TSK-BLOCK-001", status="blocked")
    create_active_assignment("TSK-BLOCK-001")

    result = step()

    assert result["released"] == 1
    assert resource_available("RES-OWNER-001") is True
    assert assignment_status("TSK-BLOCK-001") == "blocked"


def test_terminal_task_without_active_assignment_has_no_change(create_task):
    create_task("TSK-DONE-001", status="done")

    result = step()

    assert result["released"] == 0
    assert result["changed"] == 0


def test_release_is_idempotent(
    assignment_status,
    create_active_assignment,
    create_task,
    resource_available,
):
    create_task("TSK-DONE-001", status="done")
    create_active_assignment("TSK-DONE-001")

    first_result = step()
    second_result = step()

    assert first_result["released"] == 1
    assert second_result["released"] == 0
    assert second_result["changed"] == 0
    assert resource_available("RES-OWNER-001") is True
    assert assignment_status("TSK-DONE-001") == "completed"
