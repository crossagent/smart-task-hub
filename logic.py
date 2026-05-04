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
MAX_STABLE_STEPS = 100

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

def step(connection=None):
    """Advance task scheduling from the current database state."""
    result = {
        "released": 0,
        "promoted": 0,
        "dispatched": 0,
    }
    result["released"] = _release_terminal_assignments(connection=connection)
    result["promoted"] = _promote_unblocked_tasks(connection=connection)
    result["dispatched"] = _dispatch_ready_tasks(connection=connection)
    result["changed"] = sum(result.values())
    logger.info("Scheduler step result: %s", result)
    return result

def run_to_stable(connection=None, max_steps=MAX_STABLE_STEPS):
    """Run scheduler steps until no database state can be advanced."""
    total = {
        "released": 0,
        "promoted": 0,
        "dispatched": 0,
        "steps": 0,
        "stable": False,
    }
    for _ in range(max_steps):
        current = step(connection=connection)
        total["steps"] += 1
        total["released"] += current["released"]
        total["promoted"] += current["promoted"]
        total["dispatched"] += current["dispatched"]
        if current["changed"] == 0:
            total["stable"] = True
            break
    return total

def _release_terminal_assignments(connection=None):
    """Release resources for tasks already marked terminal in the database."""
    assignments = db.execute_query(
        """
        SELECT ta.task_id, ta.resource_id, t.status
        FROM task_assignments ta
        JOIN tasks t ON t.id = ta.task_id
        WHERE ta.status = 'active'
          AND t.status IN ('done', 'failed', 'blocked')
        ORDER BY ta.assigned_at ASC
        """,
        connection=connection,
    )
    released_count = 0
    for assignment in assignments or []:
        task_id = assignment["task_id"]
        resource_id = assignment["resource_id"]
        terminal_status = assignment["status"]
        assignment_status = (
            "completed" if terminal_status == "done" else terminal_status
        )
        db.execute_mutation(
            """
            UPDATE task_assignments
            SET status = %s, completed_at = CURRENT_TIMESTAMP
            WHERE task_id = %s AND resource_id = %s AND status = 'active'
            """,
            (assignment_status, task_id, resource_id),
            connection=connection,
        )
        db.execute_mutation(
            "UPDATE resources SET is_available = TRUE WHERE id = %s",
            (resource_id,),
            connection=connection,
        )
        released_count += 1
    return released_count

def _promote_unblocked_tasks(connection=None):
    """Promote pending tasks when all declared dependencies are done."""
    return db.execute_mutation(
        """
        UPDATE tasks t
        SET status = 'ready'
        WHERE t.status = 'pending'
          AND NOT EXISTS (
              SELECT 1
              FROM unnest(COALESCE(t.depends_on, '{}')) dep_id
              LEFT JOIN tasks dep ON dep.id = dep_id
              WHERE dep.id IS NULL OR dep.status <> 'done'
          )
        """,
        connection=connection,
    )

def _dispatch_ready_tasks(connection=None):
    """Dispatch ready tasks to their module owner when that resource is free."""
    ready_tasks = db.execute_query(
        """
        SELECT t.id, t.module_iteration_goal, m.owner_res_id
        FROM tasks t
        JOIN modules m ON m.id = t.module_id
        JOIN resources r ON r.id = m.owner_res_id
        WHERE t.status = 'ready'
          AND r.is_available = TRUE
        ORDER BY t.created_at ASC
        """,
        connection=connection,
    )
    dispatched_count = 0
    for task in ready_tasks or []:
        task_id = task["id"]
        resource_id = task["owner_res_id"]
        locked = db.execute_query(
            """
            UPDATE resources
            SET is_available = FALSE
            WHERE id = %s AND is_available = TRUE
            RETURNING id
            """,
            (resource_id,),
            connection=connection,
        )
        if not locked:
            continue
        updated = db.execute_mutation(
            "UPDATE tasks SET status = 'in_progress' WHERE id = %s AND status = 'ready'",
            (task_id,),
            connection=connection,
        )
        if not updated:
            db.execute_mutation(
                "UPDATE resources SET is_available = TRUE WHERE id = %s",
                (resource_id,),
                connection=connection,
            )
            continue
        db.execute_mutation(
            """
            INSERT INTO task_assignments (task_id, resource_id, status)
            VALUES (%s, %s, 'active')
            """,
            (task_id, resource_id),
            connection=connection,
        )
        emit_event(
            EVENT_TASK_ASSIGNED,
            task_id=task_id,
            resource_id=resource_id,
            payload={"resource_id": resource_id},
            connection=connection,
        )
        _send_agent_request(resource_id, task_id, task["module_iteration_goal"])
        dispatched_count += 1
    return dispatched_count

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
