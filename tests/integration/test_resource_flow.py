import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from logic import run_to_stable as run_system_bus_cycle
from supervisor import agent_supervisor
from db import execute_query, execute_mutation


SLICE_SQL = Path(__file__).parent.parent / "fixtures" / "test_slice.sql"


@pytest.fixture(autouse=True)
def seed_test_slice(db_conn):
    sql = SLICE_SQL.read_text(encoding="utf-8")
    cur = db_conn.cursor()
    cur.execute(sql)
    db_conn.commit()
    cur.close()
    yield


@pytest.fixture
def mock_agent_pool():
    agent_supervisor.pool = {}
    with patch.object(agent_supervisor, 'trigger_agent'):
        agent_supervisor.pool = {
            "RES-ARCHITECT-001": MagicMock(),
            "RES-CODER-001": MagicMock(),
            "RES-CODER-002": MagicMock(),
            "RES-CODER-003": MagicMock(),
        }
        yield agent_supervisor.pool


def run_step():
    from logic import emit_event, EVENT_TASK_READY, EVENT_TASK_COMPLETED
    
    # 0. Promote Root Pending Tasks
    execute_mutation("UPDATE tasks SET status = 'ready' WHERE status = 'pending' AND (depends_on IS NULL OR depends_on = '{}')")

    # 1. Detect Ready Tasks
    ready_tasks = execute_query("SELECT id FROM tasks WHERE status = 'ready' AND id NOT IN (SELECT task_id FROM events WHERE event_type = %s AND status = 'pending')", (EVENT_TASK_READY,))
    for t in ready_tasks:
        emit_event(EVENT_TASK_READY, task_id=t['id'])
        
    # 2. Detect Terminal Tasks
    terminal_tasks = execute_query("SELECT id FROM tasks WHERE status IN ('done', 'failed', 'blocked') AND id NOT IN (SELECT task_id FROM events WHERE event_type = %s)", (EVENT_TASK_COMPLETED,))
    for t in terminal_tasks:
        emit_event(EVENT_TASK_COMPLETED, task_id=t['id'])

    run_system_bus_cycle()


def q(sql, params=None):
    return execute_query(sql, params) if params else execute_query(sql)


def resource_available(res_id):
    rows = q("SELECT is_available FROM resources WHERE id = %s", (res_id,))
    return rows[0]['is_available'] if rows else None


class TestResourceLifecycle:
    def test_resource_becomes_busy_on_dispatch(self, mock_agent_pool):
        execute_mutation("UPDATE tasks SET status = 'ready' WHERE id = 'TSK-READY-001'")
        run_step()
        assert resource_available('RES-CODER-003') is False

    def test_resource_released_on_completion(self, mock_agent_pool):
        assert resource_available('RES-CODER-002') is False
        execute_mutation("UPDATE tasks SET status = 'done' WHERE id = 'TSK-RUN-001'")
        run_step()
        assert resource_available('RES-CODER-002') is True

    def test_resource_released_on_failure(self, mock_agent_pool):
        execute_mutation("UPDATE tasks SET status = 'failed' WHERE id = 'TSK-RUN-001'")
        run_step()
        assert resource_available('RES-CODER-002') is True
