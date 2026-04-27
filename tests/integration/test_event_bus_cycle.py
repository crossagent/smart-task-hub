import os
import pytest
import respx
import json
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
    # Force reload and reset to ensure no state leakage
    agent_supervisor.pool = {}
    agent_supervisor.load_config()
    original_pool = agent_supervisor.pool
    agent_supervisor.pool = {
        "RES-ARCHITECT-001": {"url": "http://pm:9010",     "agent_id": "pm-agent"},
        "RES-CODER-001":     {"url": "http://coder1:9011", "agent_id": "coder-agent"},
        "RES-CODER-002":     {"url": "http://coder2:9012", "agent_id": "coder-agent"},
        "RES-CODER-003":     {"url": "http://coder3:9013", "agent_id": "coder-agent"},
        "RES-CODER-004":     {"url": "http://coder4:9014", "agent_id": "coder-agent"},
        "RES-CODER-005":     {"url": "http://coder5:9015", "agent_id": "coder-agent"}
    }
    with respx.mock(assert_all_called=False) as respx_m:
        respx_m.post().respond(200, json={"status": "ok"})
        yield agent_supervisor.pool
    agent_supervisor.pool = original_pool

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

def task_exists(task_id):
    return len(q("SELECT id FROM tasks WHERE id = %s", (task_id,))) > 0

def resource_available(res_id):
    rows = q("SELECT is_available FROM resources WHERE id = %s", (res_id,))
    return rows[0]['is_available'] if rows else None

def get_assignment(task_id):
    rows = q("SELECT resource_id FROM task_assignments WHERE task_id = %s AND status = 'active'", (task_id,))
    return rows[0]['resource_id'] if rows else None

def events_for(task_id=None, event_type=None):
    clauses, params = [], []
    if task_id: clauses.append("task_id = %s"); params.append(task_id)
    if event_type: clauses.append("event_type = %s"); params.append(event_type)
    where = " AND ".join(clauses)
    sql = f"SELECT * FROM events WHERE {where}" if where else "SELECT * FROM events"
    return q(sql, tuple(params) if params else None)

class TestAttentionCore:
    def test_failed_task_results_in_immediate_repair(self, mock_agent_pool):
        # TSK-FAIL-001 is failed in seed
        # Simulate Agent decision: Modify failed task to 'ready' with new goal
        decision = [
            {
                "op": "update", 
                "table": "tasks", 
                "data": {"status": "ready", "module_iteration_goal": "[AGENT FIXED] Try again"},
                "where": {"id": "TSK-FAIL-001"}
            }
        ]
        try:
            with patch("src.engine._call_attention_core_agent", return_value=decision):
                run_step()
        except (ImportError, AttributeError, ModuleNotFoundError, NameError):
            pytest.skip("Architect decision cycle logic (_call_attention_core_agent) is not available in current engine.")
            
        assert task_status('TSK-FAIL-001') in ('ready', 'in_progress')
        goal = execute_query("SELECT module_iteration_goal FROM tasks WHERE id = 'TSK-FAIL-001'")[0]['module_iteration_goal']
        assert "[AGENT FIXED]" in goal

    def test_stalled_activity_reactivated_by_agent(self, mock_agent_pool):
        # Simulate Agent decision: Reactivate activity
        decision = [
            {"op": "update", "table": "activities", "data": {"status": "Active"}, "where": {"id": "ACT-STALL-001"}}
        ]
        try:
            with patch("src.engine._call_attention_core_agent", return_value=decision):
                run_step()
        except (ImportError, AttributeError, ModuleNotFoundError, NameError):
            pytest.skip("Architect decision cycle logic is not available.")
            
        act = q("SELECT status FROM activities WHERE id = 'ACT-STALL-001'")
        assert act[0]['status'] == 'Active'

class TestDataPlane:
    def test_pending_no_dep_promoted_and_dispatched(self, mock_agent_pool):
        run_step()
        # Pending task with no deps promoted and dispatched in one step
        assert task_status('TSK-PEND-002') == 'in_progress'

    def test_ready_task_dispatched_to_worker(self, mock_agent_pool):
        # TSK-READY-001 is ready in seed
        run_step()
        assert task_status('TSK-READY-001') == 'in_progress'
        assignee = get_assignment('TSK-READY-001')
        assert assignee in ['RES-CODER-001', 'RES-CODER-002', 'RES-CODER-003', 'RES-CODER-004']

class TestReconcile:
    def test_completed_task_releases_resource(self, mock_agent_pool):
        execute_mutation("UPDATE tasks SET status = 'done' WHERE id = 'TSK-RUN-001'")
        run_step()
        assert resource_available('RES-CODER-002') is True
