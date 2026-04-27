import pytest
import httpx

@pytest.mark.parametrize("agent_name", [
    "Hub (MCP)",
    "PM Agent",
    "Task Planner",
    "Coder Expert",
    "Trader Expert",
    "Research Expert",
    "Risk Expert",
    "Data Expert",
])
def test_agent_connectivity(http_client, agent_urls, agent_name):
    """
    Standard pytest case to verify A2A connectivity for each agent.
    Checks that the service is reachable and returns a valid HTTP response.
    """
    # Use /api/system/settings as a more reliable heartbeat for the Hub
    endpoint = "/list-apps" if "Hub" not in agent_name else "/api/system/settings"
    url = f"{agent_urls[agent_name]}{endpoint}"
    try:
        response = http_client.get(url, follow_redirects=True)
        # 200 is ideal, 404 means server is up but endpoint missing, 
        # 503 might happen in some proxy/docker setups but still proves the port is reachable.
        assert response.status_code in [200, 404, 503]
        
    except httpx.ConnectError:
        pytest.fail(f"Could not connect to {agent_name} at {url}. Is the service running?")
    except Exception as e:
        pytest.fail(f"Agent {agent_name} connectivity test failed: {str(e)}")

def test_mcp_server_identity(http_client):
    """Specific check for the Hub's dashboard API."""
    url = "http://localhost:45666/api/system/settings" 
    response = http_client.get(url, follow_redirects=True)
    assert response.status_code == 200
    data = response.json()
    assert "auto_advance" in data
