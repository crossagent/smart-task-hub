from logic import step


def test_pending_task_with_unmet_dependency_stays_pending(
    create_task,
    task_status,
):
    create_task("TSK-UPSTREAM-001", status="in_progress")
    create_task("TSK-TARGET-001", depends_on=["TSK-UPSTREAM-001"])

    result = step()

    assert result["promoted"] == 0
    assert result["dispatched"] == 0
    assert task_status("TSK-TARGET-001") == "pending"


def test_pending_task_with_all_dependencies_done_is_promoted_and_dispatched(
    create_task,
    task_status,
):
    create_task("TSK-UPSTREAM-001", status="done")
    create_task("TSK-TARGET-001", depends_on=["TSK-UPSTREAM-001"])

    result = step()

    assert result["promoted"] == 1
    assert result["dispatched"] == 1
    assert task_status("TSK-TARGET-001") == "in_progress"


def test_pending_task_with_missing_dependency_stays_pending(
    create_task,
    task_status,
):
    create_task("TSK-TARGET-001", depends_on=["TSK-MISSING-001"])

    result = step()

    assert result["promoted"] == 0
    assert result["dispatched"] == 0
    assert task_status("TSK-TARGET-001") == "pending"


def test_pending_task_with_failed_dependency_stays_pending(
    create_task,
    task_status,
):
    create_task("TSK-UPSTREAM-001", status="failed")
    create_task("TSK-TARGET-001", depends_on=["TSK-UPSTREAM-001"])

    result = step()

    assert result["promoted"] == 0
    assert result["dispatched"] == 0
    assert task_status("TSK-TARGET-001") == "pending"
