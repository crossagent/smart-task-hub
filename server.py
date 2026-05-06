import json
import logging
from typing import Optional, List, Any, Dict
from fastmcp import FastMCP
import db
import logic

# Setup logging
logger = logging.getLogger("smart_task_hub")
logging.basicConfig(level=logging.INFO)

mcp = FastMCP("Smart Task Hub")

@mcp.tool()
def query_sql(query: str) -> str:
    """Execute a raw read-only SQL query against the database."""
    upper_query = query.strip().upper()
    if any(upper_query.startswith(verb) for verb in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]):
        return "Error: Only read-only queries (SELECT) are allowed via query_sql."
    try:
        results = db.execute_query(query)
        if not results: return "No rows returned."
        return json.dumps(results, indent=2, cls=db.CustomEncoder, ensure_ascii=False)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def get_database_schema() -> str:
    """Retrieve the structure of all tables in the database (Source of Truth)."""
    query = """
    SELECT table_name, column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_schema = 'public'
    ORDER BY table_name, ordinal_position;
    """
    try:
        results = db.execute_query(query)
        schema = {}
        for row in (results or []):
            table = row['table_name']
            if table not in schema: schema[table] = []
            schema[table].append({"column": row['column_name'], "type": row['data_type']})
        return json.dumps(schema, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def step() -> str:
    """Advance the scheduler once from the current database state."""
    try:
        with db.db_transaction() as conn:
            result = logic.step(connection=conn)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def run_to_stable(max_steps: int = 100) -> str:
    """Run scheduler steps until the database state has no more progress."""
    try:
        with db.db_transaction() as conn:
            result = logic.run_to_stable(
                connection=conn,
                max_steps=max_steps,
            )
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def upsert_resource(
    id: str,
    name: str,
    org_role: str,
    resource_type: str = "agent",
    agent_card_url: Optional[str] = None,
    is_available: bool = True,
    status: str = "Available",
    dingtalk_id: Optional[str] = None,
    professional_skill: Optional[str] = None
) -> str:
    """Create or update a record in the resources (compute slots) table."""
    sql = """
        INSERT INTO resources (id, name, org_role, resource_type, agent_card_url, is_available, status, dingtalk_id, professional_skill)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            org_role = EXCLUDED.org_role,
            resource_type = EXCLUDED.resource_type,
            agent_card_url = EXCLUDED.agent_card_url,
            is_available = EXCLUDED.is_available,
            status = EXCLUDED.status,
            dingtalk_id = EXCLUDED.dingtalk_id,
            professional_skill = EXCLUDED.professional_skill,
            updated_at = CURRENT_TIMESTAMP
    """
    try:
        db.execute_mutation(sql, (id, name, org_role, resource_type, agent_card_url, is_available, status, dingtalk_id, professional_skill))
        return f"Successfully processed resource '{name}' (ID: {id})."
    except Exception as e:
        return f"Error: {str(e)}"



@mcp.tool()
def assign_task(task_id: str, resource_id: str) -> str:
    """Assign a task to a resource."""
    try:
        db.execute_mutation("UPDATE tasks SET status = 'in_progress' WHERE id = %s AND status IN ('ready', 'pending')", (task_id,))
        db.execute_mutation("INSERT INTO task_assignments (task_id, resource_id, status) VALUES (%s, %s, 'active')", (task_id, resource_id))
        return f"Task '{task_id}' assigned to resource '{resource_id}'."
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def submit_task_deliverable(task_id: str, status: str, execution_result: str, artifact_data: Optional[str] = None) -> str:
    """Submit the final result and artifact of a task."""
    sql = "UPDATE tasks SET status = %s, execution_result = %s, artifact = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s"
    try:
        with db.db_transaction() as conn:
            db.execute_mutation(sql, (status, execution_result, artifact_data, task_id), connection=conn)
            task_info = db.execute_query("SELECT activity_id FROM tasks WHERE id = %s", (task_id,), connection=conn)
            a_id = task_info[0]['activity_id'] if task_info else None
            
            logic.emit_event(logic.EVENT_TASK_COMPLETED, task_id=task_id, payload={"status": status, "result": execution_result}, activity_id=a_id, connection=conn)
            logic.run_to_stable(connection=conn)
            return f"Task '{task_id}' submitted."
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def get_task_context(task_id: str) -> str:
    """Retrieve full context for a task."""
    query = """
        SELECT t.id, t.module_iteration_goal, t.status, m.name as module_name, m.local_path, a.name as activity_name
        FROM tasks t JOIN modules m ON t.module_id = m.id LEFT JOIN activities a ON t.activity_id = a.id
        WHERE t.id = %s
    """
    try:
        results = db.execute_query(query, (task_id,))
        if not results: return f"Error: Task {task_id} not found."
        return json.dumps(results[0], indent=2, cls=db.CustomEncoder)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def propose_blueprint_plan(title: str, actions: List[dict], activity_id: Optional[str] = None) -> str:
    """Propose a set of blueprint modifications."""
    sql = "INSERT INTO blueprint_plans (title, activity_id, proposed_actions, status) VALUES (%s, %s, %s, 'pending') RETURNING id"
    try:
        results = db.execute_query(sql, (title, activity_id, json.dumps(actions)))
        return f"Plan '{title}' proposed (ID: {results[0]['id']})."
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def execute_approved_plan(plan_id: int) -> str:
    """Execute an approved blueprint modification plan."""
    try:
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
                elif op == 'delete':
                    conds = " AND ".join([f"{k} = %s" for k in where.keys()])
                    db.execute_mutation(f"DELETE FROM {table} WHERE {conds}", list(where.values()), connection=conn)
            
            db.execute_mutation("UPDATE blueprint_plans SET status = 'executed' WHERE id = %s", (plan_id,), connection=conn)
            logic.run_to_stable(connection=conn)
            return f"Plan {plan_id} executed."
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def delete_record(table: str, id: str) -> str:
    """Delete a record from allowed tables."""
    allowed = {"resources", "activities", "milestones", "modules", "tasks", "task_assignments", "blueprint_plans"}
    if table not in allowed: return f"Error: Invalid table '{table}'."
    try:
        db.execute_mutation(f"DELETE FROM {table} WHERE id = %s", (id,))
        return f"Deleted record from '{table}'."
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    import os
    from supervisor import agent_supervisor
    agent_supervisor.bootstrap()
    
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    port = int(os.getenv("PORT", "45666"))
    
    if transport == "streamable-http":
        logger.info(f"Starting MCP server with streamable-http transport on port {port}")
        mcp.run(transport="streamable-http", port=port)
    elif transport == "sse":
        logger.info(f"Starting MCP server with SSE transport on port {port}")
        mcp.run(transport="sse", port=port)
    else:
        logger.info("Starting MCP server with stdio transport")
        mcp.run(transport="stdio")
