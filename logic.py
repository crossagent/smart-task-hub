import json
import logging
from typing import Optional, List, Dict, Any
from .db import execute_query, execute_mutation, CustomEncoder, db_transaction

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
    """Processes pending events until stable."""
    results = []
    # Simplified causality flush
    while True:
        query = "SELECT * FROM events WHERE status = 'pending' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
        events = execute_query(query, connection=connection)
        if not events: break
        
        event = events[0]
        summary = _handle_event(event, connection=connection)
        execute_mutation(
            "UPDATE events SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP WHERE id = %s",
            (event['id'],),
            connection=connection
        )
        results.append({"id": event['id'], "summary": summary})
    return results

def _handle_event(event, connection):
    etype = event['event_type']
    if etype == EVENT_TASK_COMPLETED:
        return _handle_task_completed(event, connection)
    elif etype == EVENT_TASK_READY:
        return f"Task {event['task_id']} is ready for assignment."
    return f"Acknowledged {etype}."

def _handle_task_completed(event, connection):
    task_id = event['task_id']
    # Recover resource
    assignments = execute_query(
        "SELECT resource_id FROM task_assignments WHERE task_id = %s AND status = 'active'",
        (task_id,), connection=connection
    )
    if assignments:
        res_id = assignments[0]['resource_id']
        execute_mutation("UPDATE resources SET is_available = True WHERE id = %s", (res_id,), connection=connection)
        execute_mutation("UPDATE task_assignments SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE task_id = %s AND status = 'active'", (task_id,), connection=connection)
    
    # Check dependents
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
    return f"Unlocked {unlocked} tasks."
