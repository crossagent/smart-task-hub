import pytest
import uuid
import json
from src.tools import (
    query_sql, 
    get_task_context,
    upsert_resource, 
    upsert_project, 
    upsert_activity, 
    upsert_module, 
    upsert_task,
    assign_task,
    submit_task_deliverable,
    delete_record
)

@pytest.fixture
def resource_id():
    return f"RES-TEST-{uuid.uuid4().hex[:8]}"

@pytest.fixture
def project_id():
    return f"PRJ-TEST-{uuid.uuid4().hex[:8]}"

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
    # 1. Setup owner
    upsert_resource(id=resource_id, name="Module Owner", org_role="Architect")
    
    # 2. Upsert Module (No project_id)
    msg = upsert_module(
        id=module_id,
        name="AuthCore Component",
        owner_res_id=resource_id,
        local_path="/workspaces/auth_core",
        repo_url="https://github.com/org/auth_core.git",
        entity_type="Code"
    )
    assert "Successfully processed" in msg
    
    # 3. Verify
    res = json.loads(query_sql(f"SELECT * FROM modules WHERE id = '{module_id}'"))
    assert res[0]["local_path"] == "/workspaces/auth_core"
    assert res[0]["repo_url"] == "https://github.com/org/auth_core.git"

def test_decoupled_task_flow(resource_id, project_id, module_id):
    """Test the new flow: Create Task (no resource) -> Assign -> Complete."""
    # Setup infrastructure
    upsert_resource(id=resource_id, name="Executor Agent", org_role="Coder")
    upsert_project(id=project_id, name="Big Migration", initiator_res_id=resource_id)
    upsert_module(id=module_id, name="DatabaseParser", owner_res_id=resource_id)
    
    task_id = f"TSK-FLOW-{uuid.uuid4().hex[:8]}"
    
    # 1. Create Task (No resource_id)
    msg_tsk = upsert_task(
        id=task_id,
        module_id=module_id,
        project_id=project_id,
        module_iteration_goal="Upgrade to PG17",
        status="pending"
    )
    assert "Successfully processed" in msg_tsk
    
    # 2. Assign Task to Resource
    msg_assign = assign_task(task_id=task_id, resource_id=resource_id)
    assert "assigned to resource" in msg_assign
    
    # Verify assignment record
    assign_res = json.loads(query_sql(f"SELECT * FROM task_assignments WHERE task_id = '{task_id}'"))
    assert len(assign_res) == 1
    assert assign_res[0]["resource_id"] == resource_id
    
    # Verify task status moved to in_progress
    task_res = json.loads(query_sql(f"SELECT status FROM tasks WHERE id = '{task_id}'"))
    assert task_res[0]["status"] == "in_progress"
    
    # 3. Complete Task
    msg_done = submit_task_deliverable(
        task_id=task_id,
        status="done",
        execution_result="Migration complete.",
        artifact_data="commit:abc12345"
    )
    assert "submitted with status 'done'" in msg_done
    
    # Verify assignment closed
    assign_final = json.loads(query_sql(f"SELECT status, completed_at FROM task_assignments WHERE task_id = '{task_id}'"))
    assert assign_final[0]["status"] == "completed"
    assert assign_final[0]["completed_at"] is not None

def test_task_context_includes_module_path(resource_id, project_id, module_id):
    """Verify that task context now brings in the module's physical path."""
    upsert_resource(id=resource_id, name="Context King", org_role="Architect")
    upsert_module(id=module_id, name="ContextMod", owner_res_id=resource_id, local_path="/app/src/context")
    
    task_id = f"TSK-CTX-{uuid.uuid4().hex[:8]}"
    upsert_task(id=task_id, module_id=module_id, module_iteration_goal="Test path join")
    
    context = json.loads(get_task_context(task_id))
    assert context["local_path"] == "/app/src/context"
    assert context["module_name"] == "ContextMod"
