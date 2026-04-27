import pytest
import uuid

@pytest.fixture
def test_data_ids():
    """Generator for unique test IDs to ensure isolation."""
    uid = uuid.uuid4().hex[:8].upper()
    return {
        "res": f"RES-T-{uid}",
        "prj": f"PRJ-T-{uid}",
        "act": f"ACT-T-{uid}",
        "mod": f"MOD-T-{uid}",
        "tsk": f"TSK-T-{uid}"
    }

def test_full_database_crud_cycle(db_conn, test_data_ids):
    """
    Standard pytest case for the 5-table CRUD cycle:
    Resources -> Projects -> Activities -> Modules -> Tasks
    """
    cur = db_conn.cursor()
    ids = test_data_ids

    try:
        # 1. CREATE
        # Resource
        cur.execute(
            "INSERT INTO resources (id, name, org_role) VALUES (%s, %s, %s)",
            (ids["res"], "Pytest Agent", "Automation")
        )
        # Project
        cur.execute(
            "INSERT INTO projects (id, name, initiator_res_id, memo_content) VALUES (%s, %s, %s, %s)",
            (ids["prj"], "Pytest Project", ids["res"], "Integration testing with pytest")
        )
        # Activity
        cur.execute(
            "INSERT INTO activities (id, name, project_id, owner_res_id) VALUES (%s, %s, %s, %s)",
            (ids["act"], "Pytest Activity", ids["prj"], ids["res"])
        )
        # Module
        cur.execute(
            "INSERT INTO modules (id, name, owner_res_id) VALUES (%s, %s, %s)",
            (ids["mod"], "Pytest Module", ids["res"])
        )
        # Task
        cur.execute(
            "INSERT INTO tasks (id, module_id, project_id, activity_id, module_iteration_goal) VALUES (%s, %s, %s, %s, %s)",
            (ids["tsk"], ids["mod"], ids["prj"], ids["act"], "Verify CRUD")
        )
        db_conn.commit()

        # 2. READ & VERIFY
        cur.execute("SELECT name FROM projects WHERE id = %s", (ids["prj"],))
        assert cur.fetchone()[0] == "Pytest Project"

        cur.execute("SELECT status FROM tasks WHERE id = %s", (ids["tsk"],))
        assert cur.fetchone()[0] == "pending"

        # 3. UPDATE
        cur.execute("UPDATE tasks SET status = 'done' WHERE id = %s", (ids["tsk"],))
        db_conn.commit()
        
        cur.execute("SELECT status FROM tasks WHERE id = %s", (ids["tsk"],))
        assert cur.fetchone()[0] == "done"

        # 4. DELETE (Cleanup in reverse FK order)
        cur.execute("DELETE FROM tasks WHERE id = %s", (ids["tsk"],))
        cur.execute("DELETE FROM modules WHERE id = %s", (ids["mod"],))
        cur.execute("DELETE FROM activities WHERE id = %s", (ids["act"],))
        cur.execute("DELETE FROM projects WHERE id = %s", (ids["prj"],))
        cur.execute("DELETE FROM resources WHERE id = %s", (ids["res"],))
        db_conn.commit()

        # Verify deletion
        cur.execute("SELECT COUNT(*) FROM resources WHERE id = %s", (ids["res"],))
        assert cur.fetchone()[0] == 0

    except Exception as e:
        db_conn.rollback()
        raise e
    finally:
        cur.close()
