import logging
import json
import db
from supervisor import agent_supervisor

logger = logging.getLogger("smart_task.logic")

# Event Constants
EVENT_TASK_READY = "task_ready"
EVENT_TASK_ASSIGNED = "task_assigned"
EVENT_TASK_COMPLETED = "task_completed"
EVENT_TASK_FAILED = "task_failed"
EVENT_HUMAN_INTERRUPT = "human_interrupt"

def emit_event(
    event_type: str,
    task_id: str = None,
    payload: dict = None,
    source: str = "system",
    activity_id: str = None,
    resource_id: str = None,
    connection=None,
):
    """Sync: Records an event in the system log."""
    sql = """
        INSERT INTO events (
            event_type, source, activity_id, task_id, resource_id, payload, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'pending')
    """
    db.execute_mutation(
        sql,
        (
            event_type,
            source,
            activity_id,
            task_id,
            resource_id,
            json.dumps(payload or {}),
        ),
        connection=connection,
    )
    logger.info(f"Event emitted: {event_type} (Task: {task_id})")

def run_to_stable(connection=None):
    """
    Main Sync Loop: Processes all pending events until the system reaches a stable state.
    Now completely synchronous.
    """
    processed_count = 0
    while True:
        # Get next pending event using FOR UPDATE SKIP LOCKED for basic concurrency safety
        event = db.execute_query("""
            SELECT id, event_type, task_id, payload 
            FROM events 
            WHERE status = 'pending' 
            ORDER BY created_at ASC 
            LIMIT 1 
            FOR UPDATE SKIP LOCKED
        """, connection=connection)
        
        if not event:
            break
            
        event = event[0]
        event_id = event['id']
        etype = event['event_type']
        tid = event['task_id']
        payload = event['payload']
        if isinstance(payload, str):
            payload = json.loads(payload)
        elif payload is None:
            payload = {}
        
        try:
            logger.info(f"Processing Event {event_id}: {etype}")
            
            if etype == EVENT_TASK_READY:
                _handle_task_ready(tid, connection=connection)
            elif etype == EVENT_TASK_COMPLETED:
                _handle_task_completed(tid, connection=connection)
            elif etype == EVENT_HUMAN_INTERRUPT:
                _handle_human_interrupt(payload, connection=connection)
                
            # Mark as processed
            db.execute_mutation(
                "UPDATE events SET status = 'processed' WHERE id = %s",
                (event_id,),
                connection=connection,
            )
            processed_count += 1
            
        except Exception as e:
            logger.error(f"Error processing event {event_id}: {e}")
            db.execute_mutation(
                "UPDATE events SET status = 'failed' WHERE id = %s",
                (event_id,),
                connection=connection,
            )

    return processed_count

def _handle_task_ready(task_id: str, connection=None):
    """Sync: Logic for when a task is ready to be executed."""
    task = db.execute_query(
        "SELECT module_id, module_iteration_goal FROM tasks WHERE id = %s",
        (task_id,),
        connection=connection,
    )
    if not task: return
    task = task[0]
    
    module = db.execute_query(
        "SELECT owner_res_id FROM modules WHERE id = %s",
        (task['module_id'],),
        connection=connection,
    )
    if not module: return
    owner_id = module[0]['owner_res_id']
    
    # 1. Update task status and record assignment
    db.execute_mutation(
        "UPDATE tasks SET status = 'in_progress' WHERE id = %s",
        (task_id,),
        connection=connection,
    )
    db.execute_mutation(
        "UPDATE resources SET is_available = FALSE WHERE id = %s",
        (owner_id,),
        connection=connection,
    )
    db.execute_mutation(
        "INSERT INTO task_assignments (task_id, resource_id, status) VALUES (%s, %s, 'active')",
        (task_id, owner_id),
        connection=connection,
    )
    
    emit_event(
        EVENT_TASK_ASSIGNED,
        task_id=task_id,
        resource_id=owner_id,
        payload={"resource_id": owner_id},
        connection=connection,
    )
    
    # 2. Trigger A2A Agent (Sync Bridge)
    _send_agent_request(owner_id, task_id, task['module_iteration_goal'])

def _handle_task_completed(task_id: str, connection=None):
    """Sync: Cleanup logic when a task finishes."""
    assignment = db.execute_query(
        "SELECT resource_id FROM task_assignments WHERE task_id = %s AND status = 'active'",
        (task_id,),
        connection=connection,
    )
    if assignment:
        res_id = assignment[0]['resource_id']
        db.execute_mutation(
            "UPDATE resources SET is_available = TRUE WHERE id = %s",
            (res_id,),
            connection=connection,
        )
        db.execute_mutation(
            "UPDATE task_assignments SET status = 'completed' WHERE task_id = %s",
            (task_id,),
            connection=connection,
        )
    
    # Check for dependent tasks
    dependents = db.execute_query(
        "SELECT id FROM tasks WHERE depends_on @> ARRAY[%s]::varchar[] AND status = 'pending'",
        (task_id,),
        connection=connection,
    )
    for dep in (dependents or []):
        # Check if all dependencies are satisfied
        # Simplified: if this one was the last one needed
        emit_event(EVENT_TASK_READY, task_id=dep['id'], connection=connection)

def _handle_human_interrupt(payload: dict, connection=None):
    """Sync: Handle manual instructions from user via Dashboard."""
    act_id = payload.get("activity_id")
    instruction = payload.get("text")
    
    # Find Architect/PM for this activity
    act = db.execute_query(
        "SELECT owner_res_id FROM activities WHERE id = %s",
        (act_id,),
        connection=connection,
    )
    if not act: return
    pm_id = act[0]['owner_res_id']
    
    # Trigger Architect via A2A
    _send_agent_request(pm_id, f"instruction_{act_id}", instruction)

def _send_agent_request(resource_id: str, task_id: str, text: str):
    """Sync: Dispatches task to AgentSupervisor's background loop."""
    logger.info(f"Dispatching task {task_id} to resource {resource_id}...")
    agent_supervisor.trigger_agent(resource_id, task_id, text)
