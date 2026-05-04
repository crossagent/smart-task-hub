import os
import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from logic import run_to_stable as run_system_bus_cycle
from supervisor import agent_supervisor, A2AAgentHandle
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
    # Force reload and reset
    agent_supervisor.pool = {}
    
    # Mock trigger_agent to avoid starting real threads/A2A in unit tests
    with patch.object(agent_supervisor, 'trigger_agent') as mock_trigger:
        agent_supervisor.pool = {
            "RES-PM-001": MagicMock(),
            "RES-CODER-001": MagicMock(),
            "RES-CODER-002": MagicMock(),
            "RES-CODER-003": MagicMock(),
        }
        yield mock_trigger

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

def task_status(task_id):
    rows = q("SELECT status FROM tasks WHERE id = %s", (task_id,))
    return rows[0]['status'] if rows else None

def get_assignment(task_id):
    rows = q("SELECT resource_id FROM task_assignments WHERE task_id = %s AND status = 'active'", (task_id,))
    return rows[0]['resource_id'] if rows else None

def resource_available(res_id):
    rows = q("SELECT is_available FROM resources WHERE id = %s", (res_id,))
    return rows[0]['is_available'] if rows else None

class TestDataPlane:
    def test_pending_no_dep_promoted_and_dispatched(self, mock_agent_pool):
        run_step()
        assert task_status('TSK-PEND-002') == 'in_progress'

    def test_pending_task_waits_for_all_dependencies(self, mock_agent_pool):
        execute_mutation(
            """
            UPDATE tasks
            SET depends_on = ARRAY['TSK-DONE-001', 'TSK-RUN-001']::varchar[]
            WHERE id = 'TSK-AWAIT-001'
            """
        )
        run_system_bus_cycle()
        assert task_status('TSK-AWAIT-001') == 'pending'

    def test_ready_task_dispatched_to_worker(self, mock_agent_pool):
        run_step()
        assert task_status('TSK-READY-001') == 'in_progress'
        assignee = get_assignment('TSK-READY-001')
        assert assignee in ['RES-CODER-001', 'RES-CODER-002', 'RES-CODER-003']
        # Verify that the supervisor's trigger was called
        assert mock_agent_pool.called

class TestReconcile:
    def test_completed_task_releases_resource(self, mock_agent_pool):
        execute_mutation("UPDATE tasks SET status = 'done' WHERE id = 'TSK-RUN-001'")
        run_step()
        assert resource_available('RES-CODER-002') is True
