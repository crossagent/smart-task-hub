import json
import logging
import httpx
from typing import Optional, List, Dict, Any
from db import execute_query, execute_mutation, CustomEncoder, db_transaction
from supervisor import agent_supervisor

logger = logging.getLogger("smart_task.logic")

# Event Types
EVENT_TASK_COMPLETED = "task_completed"
EVENT_TASK_READY = "task_ready"
EVENT_TASK_ASSIGNED = "task_assigned"
EVENT_TASK_FAILED = "task_failed"

def emit_event(
    event_type: str,
    source: str = "system",
    payload: Dict[str, Any] = None,
    activity_id: str = None,
    task_id: str = None,
    resource_id: str = None,
    connection=None
) -> int:
    query = """
        INSERT INTO events (event_type, source, payload, activity_id, task_id, resource_id, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'pending')
        RETURNING id
    """
    params = (
        event_type,
        source,
        json.dumps(payload or {}),
        activity_id,
        task_id,
        resource_id
    )
    res = execute_query(query, params, connection=connection)
    return res[0]['id']

def run_to_stable(connection=None):
    """Processes pending events until stable (Causality Flush)."""
    results = []
    while True:
        query = "SELECT * FROM events WHERE status = 'pending' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
        events = execute_query(query, connection=connection)
        if not events: break
        
        event = events[0]
        try:
            summary = _handle_event(event, connection=connection)
            execute_mutation(
                "UPDATE events SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP WHERE id = %s",
                (event['id'],),
                connection=connection
            )
            results.append({"id": event['id'], "summary": summary})
        except Exception as e:
            logger.error(f"Event {event['id']} failed: {e}")
            execute_mutation(
                "UPDATE events SET status = 'failed', payload = payload || %s::jsonb WHERE id = %s",
                (json.dumps({"error": str(e)}), event['id']),
                connection=connection
            )
            break
    return results

def _handle_event(event, connection):
    etype = event['event_type']
    if etype == EVENT_TASK_COMPLETED:
        return _handle_task_completed(event, connection)
    elif etype == EVENT_TASK_READY:
        return _handle_task_ready(event, connection)
    return f"Acknowledged {etype}."

def _handle_task_completed(event, connection):
    task_id = event['task_id']
    # 1. Recover resource
    assignments = execute_query(
        "SELECT resource_id FROM task_assignments WHERE task_id = %s AND status = 'active'",
        (task_id,), connection=connection
    )
    res_id = None
    if assignments:
        res_id = assignments[0]['resource_id']
        execute_mutation("UPDATE resources SET is_available = True WHERE id = %s", (res_id,), connection=connection)
        execute_mutation("UPDATE task_assignments SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE task_id = %s AND status = 'active'", (task_id,), connection=connection)
    
    # 2. DAG progression: Check dependents
    dependents = execute_query(
        "SELECT id, activity_id, depends_on FROM tasks WHERE %s = ANY(depends_on) AND status = 'pending'",
        (task_id,), connection=connection
    )
    unlocked = 0
    for dep in dependents:
        unfinished = execute_query(
            "SELECT count(*) as count FROM tasks WHERE id = ANY(%s) AND status != 'done'",
            (dep['depends_on'],), connection=connection
        )[0]['count']
        if unfinished == 0:
            execute_mutation("UPDATE tasks SET status = 'ready' WHERE id = %s", (dep['id'],), connection=connection)
            emit_event(EVENT_TASK_READY, task_id=dep['id'], activity_id=dep['activity_id'], connection=connection)
            unlocked += 1
    return f"Recovered {res_id}. Unlocked {unlocked} tasks."

def _handle_task_ready(event, connection):
    """Automatic Dispatch: Ready -> In Progress."""
    task_id = event['task_id']
    task_data = execute_query(
        "SELECT t.id, t.module_id, t.module_iteration_goal, m.owner_res_id, t.activity_id "
        "FROM tasks t JOIN modules m ON t.module_id = m.id "
        "WHERE t.id = %s AND t.status = 'ready'",
        (task_id,), connection=connection
    )
    if not task_data: return f"Task {task_id} not found/ready."
    
    task = task_data[0]
    owner_id = task['owner_res_id']
    
    # Check if resource is available
    res_data = execute_query("SELECT id FROM resources WHERE id = %s AND is_available = True", (owner_id,), connection=connection)
    if not res_data: return f"Resource {owner_id} busy. Task {task_id} queued."

    # Dispatch
    execute_mutation("UPDATE tasks SET status = 'in_progress' WHERE id = %s", (task_id,), connection=connection)
    execute_mutation("UPDATE resources SET is_available = False WHERE id = %s", (owner_id,), connection=connection)
    execute_mutation("INSERT INTO task_assignments (task_id, resource_id, status) VALUES (%s, %s, 'active')", (task_id, owner_id), connection=connection)
    
    # Trigger Agent via Supervisor
    handle = agent_supervisor.pool.get(owner_id)
    if handle:
        url = getattr(handle, 'url', None) or (handle['url'] if isinstance(handle, dict) else None)
        aid = getattr(handle, 'agent_id', None) or (handle['agent_id'] if isinstance(handle, dict) else None)
        if url and aid:
            _send_agent_request(url, aid, task_id, task['module_iteration_goal'])

    emit_event(EVENT_TASK_ASSIGNED, task_id=task_id, resource_id=owner_id, activity_id=task['activity_id'], connection=connection)
    return f"Dispatched {task_id} to {owner_id}."

def _send_agent_request(url: str, agent_id: str, session_id: str, text: str):
    """Sends async trigger to Agent API."""
    try:
        # Note: In production this would be truly async. In tests we mock it.
        with httpx.Client(timeout=2.0) as client:
            client.post(f"{url}/run", json={"app_name": agent_id, "session_id": session_id, "new_message": {"parts": [{"text": text}]}})
    except Exception as e:
        logger.error(f"Agent trigger failed: {e}")
