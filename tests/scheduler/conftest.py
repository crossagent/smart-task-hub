from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from db import execute_query
from db import execute_mutation
from supervisor import agent_supervisor


@pytest.fixture(autouse=True)
def seed_scheduler_state(db_conn):
    sql = """
    TRUNCATE task_assignments, events, tasks, milestones, modules, activities,
      resources, system_state CASCADE;

    INSERT INTO resources (id, name, org_role, is_available, resource_type)
    VALUES
      ('RES-OWNER-001', 'Owner One', 'Coder', TRUE, 'human'),
      ('RES-BUSY-001', 'Busy Owner', 'Coder', FALSE, 'human');

    INSERT INTO activities (id, name, owner_res_id, status)
    VALUES ('ACT-SCHED-001', 'Scheduler Tests', 'RES-OWNER-001', 'Active');

    INSERT INTO modules (id, name, owner_res_id, entity_type)
    VALUES
      ('MOD-OWNED-001', 'Owned Module', 'RES-OWNER-001', 'Code'),
      ('MOD-BUSY-001', 'Busy Module', 'RES-BUSY-001', 'Code');
    """
    cur = db_conn.cursor()
    cur.execute(sql)
    db_conn.commit()
    cur.close()
    yield


@pytest.fixture(autouse=True)
def mock_agent_dispatch():
    agent_supervisor.pool = {}
    with patch.object(agent_supervisor, "trigger_agent") as mock_trigger:
        agent_supervisor.pool = {
            "RES-OWNER-001": MagicMock(),
            "RES-BUSY-001": MagicMock(),
        }
        yield mock_trigger


@pytest.fixture
def create_task():
    def _create_task(
        task_id,
        status="pending",
        module_id="MOD-OWNED-001",
        depends_on=None,
    ):
        execute_mutation(
            """
            INSERT INTO tasks (
                id,
                activity_id,
                module_id,
                module_iteration_goal,
                status,
                depends_on
            )
            VALUES (%s, 'ACT-SCHED-001', %s, %s, %s, %s)
            """,
            (
                task_id,
                module_id,
                f"Goal for {task_id}",
                status,
                depends_on or [],
            ),
        )

    return _create_task


@pytest.fixture
def create_active_assignment():
    def _create_active_assignment(task_id, resource_id="RES-OWNER-001"):
        execute_mutation(
            """
            INSERT INTO task_assignments (task_id, resource_id, status)
            VALUES (%s, %s, 'active')
            """,
            (task_id, resource_id),
        )
        execute_mutation(
            "UPDATE resources SET is_available = FALSE WHERE id = %s",
            (resource_id,),
        )

    return _create_active_assignment


def _task_status(task_id):
    rows = execute_query("SELECT status FROM tasks WHERE id = %s", (task_id,))
    return rows[0]["status"] if rows else None


def _resource_available(resource_id):
    rows = execute_query(
        "SELECT is_available FROM resources WHERE id = %s",
        (resource_id,),
    )
    return rows[0]["is_available"] if rows else None


def _active_assignment(task_id):
    rows = execute_query(
        """
        SELECT task_id, resource_id, status
        FROM task_assignments
        WHERE task_id = %s AND status = 'active'
        """,
        (task_id,),
    )
    return rows[0] if rows else None


def _assignment_status(task_id):
    rows = execute_query(
        """
        SELECT status
        FROM task_assignments
        WHERE task_id = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (task_id,),
    )
    return rows[0]["status"] if rows else None


@pytest.fixture
def task_status():
    return _task_status


@pytest.fixture
def resource_available():
    return _resource_available


@pytest.fixture
def active_assignment():
    return _active_assignment


@pytest.fixture
def assignment_status():
    return _assignment_status
