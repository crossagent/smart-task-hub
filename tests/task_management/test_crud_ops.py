import pytest
import uuid
import json
from server import (
    query_sql, 
    get_task_context,
    upsert_resource, 
    assign_task,
    submit_task_deliverable,
    delete_record
)
from db import execute_mutation

@pytest.fixture
def resource_id():
    return f"RES-TEST-{uuid.uuid4().hex[:8]}"

@pytest.fixture
def activity_id():
    return f"ACT-TEST-{uuid.uuid4().hex[:8]}"

@pytest.fixture
def module_id():
    return f"MOD-TEST-{uuid.uuid4().hex[:8]}"

def test_db_connection():
    """Verify database connectivity."""
    results_json = query_sql("SELECT current_database();")
    results = json.loads(results_json)
    assert "smart_task" in results[0]["current_database"]

def test_module_centric_upsert(resource_id, module_id):
    """Test creating a module as a standalone physical entity."""
    upsert_resource(id=resource_id, name="Module Owner", org_role="Architect")
    
    execute_mutation(
        "INSERT INTO modules (id, name, owner_res_id, local_path, repo_url, entity_type) VALUES (%s, %s, %s, %s, %s, %s)",
        (module_id, "AuthCore Component", resource_id, "/workspaces/auth_core", "https://github.com/org/auth_core.git", "Code")
    )
    
    res = json.loads(query_sql(f"SELECT * FROM modules WHERE id = '{module_id}'"))
    assert res[0]["local_path"] == "/workspaces/auth_core"

def test_decoupled_task_flow(resource_id, activity_id, module_id):
    """Test the flow: Create Task -> Assign -> Complete (Matching SQL Schema)."""
    # Setup infrastructure
    upsert_resource(id=resource_id, name="Executor Agent", org_role="Coder")
    execute_mutation("INSERT INTO activities (id, name, owner_res_id) VALUES (%s, %s, %s)", (activity_id, "The Great Refactor", resource_id))
    execute_mutation("INSERT INTO modules (id, name, owner_res_id) VALUES (%s, %s, %s)", (module_id, "DatabaseParser", resource_id))
    
    task_id = f"TSK-FLOW-{uuid.uuid4().hex[:8]}"
    
    # 1. Create Task
    execute_mutation(
        "INSERT INTO tasks (id, module_id, activity_id, module_iteration_goal, status) VALUES (%s, %s, %s, %s, %s)",
        (task_id, module_id, activity_id, "Upgrade to PG17", "pending")
    )
    
    # 2. Assign Task to Resource
    msg_assign = assign_task(task_id=task_id, resource_id=resource_id)
    assert "assigned to resource" in msg_assign
    
    # 3. Complete Task
    msg_done = submit_task_deliverable(
        task_id=task_id,
        status="done",
        execution_result="Migration complete.",
        artifact_data="commit:abc12345"
    )
    assert "submitted" in msg_done
    
    # Verify task status moved to done
    task_res = json.loads(query_sql(f"SELECT status FROM tasks WHERE id = '{task_id}'"))
    assert task_res[0]["status"] == "done"

def test_task_context_includes_module_path(resource_id, activity_id, module_id):
    """Verify that task context brings in the module's physical path."""
    upsert_resource(id=resource_id, name="Context King", org_role="Architect")
    execute_mutation("INSERT INTO activities (id, name, owner_res_id) VALUES (%s, %s, %s)", (activity_id, "Context Activity", resource_id))
    execute_mutation("INSERT INTO modules (id, name, owner_res_id, local_path) VALUES (%s, %s, %s, %s)", (module_id, "ContextMod", resource_id, "/app/src/context"))
    
    task_id = f"TSK-CTX-{uuid.uuid4().hex[:8]}"
    execute_mutation("INSERT INTO tasks (id, module_id, activity_id, module_iteration_goal, status) VALUES (%s, %s, %s, %s, %s)", (task_id, module_id, activity_id, "Test path join", "pending"))
    
    context = json.loads(get_task_context(task_id))
    assert context["local_path"] == "/app/src/context"
    assert context["module_name"] == "ContextMod"
