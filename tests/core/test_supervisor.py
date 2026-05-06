import pytest
import asyncio
from unittest.mock import patch, MagicMock
from supervisor import AgentSupervisor, A2AAgentHandle
from db import execute_query, execute_mutation

@pytest.fixture(autouse=True)
def clean_db(db_conn):
    cur = db_conn.cursor()
    cur.execute("TRUNCATE resources CASCADE;")
    db_conn.commit()
    cur.close()

def test_refresh_pool():
    supervisor = AgentSupervisor()
    
    # Insert an agent into resources
    execute_mutation(
        """
        INSERT INTO resources (id, name, org_role, resource_type, agent_card_url)
        VALUES ('RES-AGENT-001', 'Agent', 'AI', 'agent', 'http://localhost:8000/agent-card')
        """
    )
    
    supervisor.refresh_pool()
    assert 'RES-AGENT-001' in supervisor.pool
    handle = supervisor.get_agent('RES-AGENT-001')
    assert isinstance(handle, A2AAgentHandle)
    assert handle.agent_card_url == 'http://localhost:8000/agent-card'
    
    # Update URL and verify it creates a new handle
    execute_mutation("UPDATE resources SET agent_card_url = 'http://localhost:8001/agent-card' WHERE id = 'RES-AGENT-001'")
    supervisor.refresh_pool()
    handle_new = supervisor.get_agent('RES-AGENT-001')
    assert handle_new.agent_card_url == 'http://localhost:8001/agent-card'

def test_trigger_agent_not_found(caplog):
    supervisor = AgentSupervisor()
    supervisor._loop = asyncio.new_event_loop()  # Simulate bootstrap
    
    supervisor.trigger_agent("MISSING", "TASK-1", "Goal")
    assert "No agent found for resource: MISSING" in caplog.text

@patch("asyncio.run_coroutine_threadsafe")
def test_trigger_agent_success(mock_run_coroutine_threadsafe):
    supervisor = AgentSupervisor()
    supervisor._loop = MagicMock()
    handle = MagicMock()
    supervisor.pool = {"RES-TEST": handle}
    
    supervisor.trigger_agent("RES-TEST", "TASK-1", "Goal")
    mock_run_coroutine_threadsafe.assert_called_once()
