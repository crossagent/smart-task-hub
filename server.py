import json
from typing import Optional, List, Any
from fastmcp import FastMCP
from . import db
from . import logic

mcp = FastMCP("Smart Task Hub")

@mcp.tool()
def get_database_schema() -> str:
    """Retrieve the structure of all tables in the database."""
    query = "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = 'public'"
    results = db.execute_query(query)
    schema = {}
    for row in (results or []):
        table = row['table_name']
        if table not in schema: schema[table] = []
        schema[table].append({"column": row['column_name'], "type": row['data_type']})
    return json.dumps(schema, indent=2)

@mcp.tool()
def upsert_activity(id: str, name: str, owner_res_id: str, status: str = "Active") -> str:
    """Create or update an activity."""
    sql = """
        INSERT INTO activities (id, name, owner_res_id, status) VALUES (%s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, status=EXCLUDED.status, updated_at=CURRENT_TIMESTAMP
    """
    db.execute_mutation(sql, (id, name, owner_res_id, status))
    return f"Activity {id} updated."

@mcp.tool()
def upsert_milestone(id: str, activity_id: str, name: str, status: str = "Pending") -> str:
    """Create or update a milestone."""
    sql = """
        INSERT INTO milestones (id, activity_id, name, status) VALUES (%s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, status=EXCLUDED.status, updated_at=CURRENT_TIMESTAMP
    """
    db.execute_mutation(sql, (id, activity_id, name, status))
    return f"Milestone {id} updated."

@mcp.tool()
def upsert_task(id: str, module_id: str, module_iteration_goal: str, activity_id: str, milestone_id: Optional[str] = None, depends_on: Optional[List[str]] = None) -> str:
    """Create or update a task."""
    sql = """
        INSERT INTO tasks (id, module_id, module_iteration_goal, activity_id, milestone_id, depends_on, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'pending')
        ON CONFLICT (id) DO UPDATE SET module_iteration_goal=EXCLUDED.module_iteration_goal, updated_at=CURRENT_TIMESTAMP
    """
    db.execute_mutation(sql, (id, module_id, module_iteration_goal, activity_id, milestone_id, depends_on or []))
    return f"Task {id} updated."

@mcp.tool()
def submit_task_deliverable(task_id: str, status: str, execution_result: str) -> str:
    """Submit task result and trigger state progression."""
    sql = "UPDATE tasks SET status = %s, execution_result = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s"
    db.execute_mutation(sql, (status, execution_result, task_id))
    
    # Trigger logic
    with db.db_transaction() as conn:
        logic.emit_event(logic.EVENT_TASK_COMPLETED, task_id=task_id, connection=conn)
        steps = logic.run_to_stable(connection=conn)
    
    return f"Task {task_id} submitted. Engine advanced {len(steps)} steps."

@mcp.tool()
def assign_task(task_id: str, resource_id: str) -> str:
    """Assign a task to a resource."""
    db.execute_mutation("UPDATE tasks SET status = 'in_progress' WHERE id = %s AND status IN ('ready', 'pending')", (task_id,))
    db.execute_mutation("INSERT INTO task_assignments (task_id, resource_id, status) VALUES (%s, %s, 'active')", (task_id, resource_id))
    return f"Task {task_id} assigned to {resource_id}."

@mcp.tool()
def get_task_context(task_id: str) -> str:
    """Retrieve full context for a task."""
    query = """
        SELECT t.id, t.module_iteration_goal, t.status, m.name as module_name, m.local_path, a.name as activity_name
        FROM tasks t JOIN modules m ON t.module_id = m.id LEFT JOIN activities a ON t.activity_id = a.id
        WHERE t.id = %s
    """
    results = db.execute_query(query, (task_id,))
    if not results: return f"Error: Task {task_id} not found."
    return json.dumps(results[0], indent=2, cls=db.CustomEncoder)

@mcp.tool()
def propose_blueprint_plan(title: str, actions: List[dict], activity_id: Optional[str] = None) -> str:
    """Propose a blueprint modification plan."""
    sql = "INSERT INTO blueprint_plans (title, activity_id, proposed_actions, status) VALUES (%s, %s, %s, 'pending') RETURNING id"
    results = db.execute_query(sql, (title, activity_id, json.dumps(actions)))
    return f"Plan '{title}' proposed (ID: {results[0]['id']})."

@mcp.tool()
def execute_approved_plan(plan_id: int) -> str:
    """Execute an approved blueprint plan."""
    plan_rows = db.execute_query("SELECT * FROM blueprint_plans WHERE id = %s", (plan_id,))
    if not plan_rows or plan_rows[0]['status'] != 'approved':
        return f"Error: Plan {plan_id} not found or not approved."
    
    actions = plan_rows[0]['proposed_actions']
    if isinstance(actions, str): actions = json.loads(actions)
    
    with db.db_transaction() as conn:
        for action in actions:
            op, table, data, where = action.get('op'), action.get('table'), action.get('data', {}), action.get('where', {})
            if op == 'update':
                cols = ", ".join([f"{k} = %s" for k in data.keys()])
                conds = " AND ".join([f"{k} = %s" for k in where.keys()])
                db.execute_mutation(f"UPDATE {table} SET {cols} WHERE {conds}", list(data.values()) + list(where.values()), connection=conn)
            elif op == 'insert':
                cols, vals = ", ".join(data.keys()), ", ".join(["%s"] * len(data))
                db.execute_mutation(f"INSERT INTO {table} ({cols}) VALUES ({vals})", list(data.values()), connection=conn)
        
        db.execute_mutation("UPDATE blueprint_plans SET status = 'executed' WHERE id = %s", (plan_id,), connection=conn)
        logic.run_to_stable(connection=conn)
    return f"Plan {plan_id} executed."

@mcp.tool()
def delete_record(table: str, id: str) -> str:
    """Delete a record from allowed tables."""
    allowed = {"resources", "activities", "milestones", "modules", "tasks", "blueprint_plans"}
    if table not in allowed: return f"Error: Invalid table."
    db.execute_mutation(f"DELETE FROM {table} WHERE id = %s", (id,))
    return f"Deleted {id} from {table}."

@mcp.tool()
def query_sql(query: str) -> str:
    """Execute a read-only SQL query."""
    if not query.strip().upper().startswith("SELECT"):
        return "Error: Only SELECT queries are allowed."
    results = db.execute_query(query)
    return json.dumps(results, indent=2, cls=db.CustomEncoder)

if __name__ == "__main__":
    mcp.run()
