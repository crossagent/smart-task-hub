import pytest
import psycopg2
import httpx
import os

# DB Connection Details
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "user": os.getenv("DB_USER", "smart_user"),
    "password": os.getenv("DB_PASS", "smart_pass"),
    "dbname": os.getenv("DB_NAME", "smart_task_hub")
}

@pytest.fixture(scope="session")
def agent_urls():
    """Mapping of agents to their URLs (localhost for host, service name for docker)."""
    # Check if we are inside a container by looking for a common trait
    is_docker = os.path.exists("/.dockerenv")
    
    mapping = {
        "Hub (MCP)": 45666 if not is_docker else "localhost:45666",
        "PM Agent": 9010 if not is_docker else "hub_pm:9010",
        "Task Planner": 9011 if not is_docker else "task_planner:9011",
        "Coder Expert": 9012 if not is_docker else "coder_expert:9012",
        "Trader Expert": 9013 if not is_docker else "trader_expert:9013",
        "Research Expert": 9014 if not is_docker else "research_expert:9014",
        "Risk Expert": 9015 if not is_docker else "risk_expert:9015",
        "Data Expert": 9016 if not is_docker else "data_expert:9016"
    }
    
    base_urls = {}
    for name, target in mapping.items():
        if isinstance(target, int):
            base_urls[name] = f"http://localhost:{target}"
        else:
            base_urls[name] = f"http://{target}"
            
    return base_urls

@pytest.fixture
def http_client():
    """HTTP client fixture for agent communication."""
    with httpx.Client(timeout=10.0) as client:
        yield client
