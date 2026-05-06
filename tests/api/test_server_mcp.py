import pytest
import json
from unittest.mock import patch
from server import (
    query_sql,
    get_database_schema,
    step,
    run_to_stable,
    upsert_resource,
    assign_task,
    submit_task_deliverable,
    get_task_context,
    propose_blueprint_plan,
    execute_approved_plan,
    delete_record
)
from db import execute_query, execute_mutation

@pytest.fixture(autouse=True)
def clean_db(db_conn):
    """Clean the DB before each test."""
    cur = db_conn.cursor()
    cur.execute("TRUNCATE events, task_assignments, tasks, milestones, modules, activities, blueprint_plans, resources CASCADE;")
    db_conn.commit()
    cur.close()

def test_query_sql_read_only():
    """query_sql should reject non-SELECT operations."""
    result = query_sql("INSERT INTO resources (id) VALUES ('1')")
    assert "Error: Only read-only queries (SELECT) are allowed" in result
    
    # Valid SELECT
    result_select = query_sql("SELECT 1 as test")
    assert "test" in result_select
    assert "1" in result_select

def test_get_database_schema():
    """get_database_schema should return JSON structure."""
    result = get_database_schema()
    schema = json.loads(result)
    assert "resources" in schema
    assert "tasks" in schema

def test_upsert_resource():
    """Test upserting a resource."""
    result = upsert_resource(
        id="RES-TEST-001",
        name="Test Coder",
        org_role="Coder"
    )
    assert "Successfully" in result
    rows = execute_query("SELECT * FROM resources WHERE id = 'RES-TEST-001'")
    assert len(rows) == 1
    assert rows[0]['name'] == "Test Coder"

def test_blueprint_lifecycle():
    """Test the end-to-end blueprint lifecycle (propose -> execute)."""
    # 1. Setup Resource
    upsert_resource(id="RES-OWNER-001", name="Owner", org_role="PM")
    upsert_resource(id="RES-CODER-001", name="Coder", org_role="Coder")
    
    # 2. Propose a blueprint containing an Activity, Module, and Task
    actions = [
        {
            "op": "insert",
            "table": "activities",
            "data": {
                "id": "ACT-BP-001",
                "name": "Blueprint Activity",
                "owner_res_id": "RES-OWNER-001",
                "status": "Active"
            }
        },
        {
            "op": "insert",
            "table": "modules",
            "data": {
                "id": "MOD-BP-001",
                "name": "Blueprint Module",
                "owner_res_id": "RES-CODER-001",
                "entity_type": "Code"
            }
        },
        {
            "op": "insert",
            "table": "tasks",
            "data": {
                "id": "TSK-BP-001",
                "activity_id": "ACT-BP-001",
                "module_id": "MOD-BP-001",
                "module_iteration_goal": "Write code",
                "status": "pending"
            }
        }
    ]
    
    result_propose = propose_blueprint_plan(
        title="Init Project",
        actions=actions,
        activity_id=None
    )
    assert "proposed" in result_propose
    
    # Extract Plan ID
    # The return format is: "Plan '{title}' proposed (ID: {id})."
    plan_id_str = result_propose.split("(ID: ")[1].split(")")[0]
    plan_id = int(plan_id_str)
    
    # 3. Simulate Approval
    execute_mutation("UPDATE blueprint_plans SET status = 'approved' WHERE id = %s", (plan_id,))
    
    # 4. Execute Approved Plan
    result_execute = execute_approved_plan(plan_id)
    assert "executed" in result_execute
    
    # 5. Verify records
    tasks = execute_query("SELECT * FROM tasks WHERE id = 'TSK-BP-001'")
    assert len(tasks) == 1
    
    # 6. Delete Record testing
    result_delete = delete_record("tasks", "TSK-BP-001")
    assert "Deleted record" in result_delete
    assert len(execute_query("SELECT * FROM tasks WHERE id = 'TSK-BP-001'")) == 0

def test_assign_and_submit_task():
    # Setup dependencies
    upsert_resource(id="RES-1", name="Res 1", org_role="Dev")
    execute_mutation("INSERT INTO modules (id, name, owner_res_id) VALUES ('MOD-1', 'Mod', 'RES-1')")
    execute_mutation("INSERT INTO tasks (id, module_id, module_iteration_goal, status) VALUES ('TSK-1', 'MOD-1', 'Goal', 'pending')")
    
    # Test assignment
    result_assign = assign_task("TSK-1", "RES-1")
    assert "assigned" in result_assign
    status = execute_query("SELECT status FROM tasks WHERE id = 'TSK-1'")[0]['status']
    assert status == 'in_progress'
    
    # Test submission
    result_submit = submit_task_deliverable("TSK-1", "done", "Great success", "artifact.txt")
    assert "submitted" in result_submit
    task_row = execute_query("SELECT status, execution_result, artifact FROM tasks WHERE id = 'TSK-1'")[0]
    assert task_row['status'] == 'done'
    assert task_row['execution_result'] == 'Great success'
    assert task_row['artifact'] == 'artifact.txt'

def test_get_task_context():
    execute_mutation("INSERT INTO resources (id, name, org_role) VALUES ('RES-1', 'Res', 'Dev')")
    execute_mutation("INSERT INTO modules (id, name, owner_res_id) VALUES ('MOD-1', 'Mod', 'RES-1')")
    execute_mutation("INSERT INTO activities (id, name, owner_res_id) VALUES ('ACT-1', 'Act', 'RES-1')")
    execute_mutation("INSERT INTO tasks (id, module_id, activity_id, module_iteration_goal, status) VALUES ('TSK-1', 'MOD-1', 'ACT-1', 'Goal', 'pending')")
    
    result = get_task_context("TSK-1")
    data = json.loads(result)
    assert data['id'] == 'TSK-1'
    assert data['module_name'] == 'Mod'
    assert data['activity_name'] == 'Act'

def test_step_and_run_to_stable():
    # Just verify they execute without error and return valid JSON
    res_step = step()
    data_step = json.loads(res_step)
    assert "dispatched" in data_step
    
    res_run = run_to_stable(1)
    data_run = json.loads(res_run)
    assert "stable" in data_run
