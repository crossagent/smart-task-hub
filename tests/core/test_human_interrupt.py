import pytest
from unittest.mock import patch
from logic import _handle_human_interrupt
from db import execute_mutation

@pytest.fixture(autouse=True)
def clean_db(db_conn):
    cur = db_conn.cursor()
    cur.execute("TRUNCATE activities, resources CASCADE;")
    db_conn.commit()
    cur.close()

@patch("logic._send_agent_request")
def test_handle_human_interrupt(mock_send):
    # Setup Data
    execute_mutation("INSERT INTO resources (id, name, org_role) VALUES ('RES-PM', 'PM', 'PM')")
    execute_mutation("INSERT INTO activities (id, name, owner_res_id) VALUES ('ACT-1', 'Act', 'RES-PM')")
    
    payload = {
        "activity_id": "ACT-1",
        "text": "Stop the task and retry."
    }
    
    _handle_human_interrupt(payload)
    
    mock_send.assert_called_once_with('RES-PM', 'instruction_ACT-1', 'Stop the task and retry.')

@patch("logic._send_agent_request")
def test_handle_human_interrupt_no_activity(mock_send):
    payload = {
        "activity_id": "MISSING",
        "text": "Stop the task and retry."
    }
    
    _handle_human_interrupt(payload)
    mock_send.assert_not_called()
