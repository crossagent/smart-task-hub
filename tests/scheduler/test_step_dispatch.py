from logic import step


def test_ready_task_dispatches_to_available_owner(
    active_assignment,
    create_task,
    mock_agent_dispatch,
    resource_available,
    task_status,
):
    create_task("TSK-READY-001", status="ready")

    result = step()

    assert result["promoted"] == 0
    assert result["dispatched"] == 1
    assert task_status("TSK-READY-001") == "in_progress"
    assert resource_available("RES-OWNER-001") is False
    assignment = active_assignment("TSK-READY-001")
    assert assignment["resource_id"] == "RES-OWNER-001"
    assert mock_agent_dispatch.called


def test_ready_task_waits_when_owner_resource_is_busy(
    active_assignment,
    create_task,
    resource_available,
    task_status,
):
    create_task(
        "TSK-READY-001",
        status="ready",
        module_id="MOD-BUSY-001",
    )

    result = step()

    assert result["promoted"] == 0
    assert result["dispatched"] == 0
    assert task_status("TSK-READY-001") == "ready"
    assert resource_available("RES-BUSY-001") is False
    assert active_assignment("TSK-READY-001") is None


def test_same_resource_dispatches_only_one_ready_task_per_step(
    active_assignment,
    create_task,
    resource_available,
    task_status,
):
    create_task("TSK-READY-001", status="ready")
    create_task("TSK-READY-002", status="ready")

    result = step()

    assert result["promoted"] == 0
    assert result["dispatched"] == 1
    dispatched_count = sum(
        1
        for task_id in ("TSK-READY-001", "TSK-READY-002")
        if task_status(task_id) == "in_progress"
    )
    assert dispatched_count == 1
    assert resource_available("RES-OWNER-001") is False
    assert (
        active_assignment("TSK-READY-001")
        or active_assignment("TSK-READY-002")
    )
