import logging
import threading
import asyncio
import json
from typing import Dict, Optional
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
import db

logger = logging.getLogger("smart_task.supervisor")

class A2AAgentHandle:
    """Encapsulates a remote A2A agent proxy."""
    def __init__(self, resource_id: str, agent_card_url: str):
        from google.adk.runners import Runner
        from google.adk.sessions.in_memory_session_service import InMemorySessionService
        self.resource_id = resource_id
        self.agent_card_url = agent_card_url
        # Agent names must be valid Python identifiers (no hyphens)
        safe_name = resource_id.replace("-", "_")
        self.proxy = RemoteA2aAgent(safe_name, agent_card_url)
        self.runner = Runner(
            app_name="smart_task_hub",
            agent=self.proxy,
            session_service=InMemorySessionService()
        )
        logger.info(f"Initialized A2A Handle for {resource_id} at {agent_card_url}")

class AgentSupervisor:
    """
    Manages A2A agent proxies in a background thread to bridge 
    Sync Hub logic with Async A2A communication.
    """
    def __init__(self):
        self.pool: Dict[str, A2AAgentHandle] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    def bootstrap(self):
        """Initializes the background event loop and loads agent pool."""
        if self._thread:
            return

        # 1. Start Background Thread for AsyncIO
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()
        logger.info("AgentSupervisor: Background event loop started.")

        # 2. Initial load of agents from DB
        self.refresh_pool()

    def _run_event_loop(self):
        """Entry point for the background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def refresh_pool(self):
        """Sync interface to refresh agent proxies from database."""
        try:
            # Note: db.execute_query is sync
            rows = db.execute_query("SELECT id, agent_card_url FROM resources WHERE resource_type = 'agent' AND agent_card_url IS NOT NULL")
            new_pool = {}
            for row in (rows or []):
                rid = row['id']
                url = row['agent_card_url']
                # Reuse existing handle if URL hasn't changed to preserve state/connections
                if rid in self.pool and self.pool[rid].agent_card_url == url:
                    new_pool[rid] = self.pool[rid]
                else:
                    new_pool[rid] = A2AAgentHandle(rid, url)
            self.pool = new_pool
            logger.info(f"Agent pool refreshed. {len(self.pool)} agents active.")
        except Exception as e:
            logger.error(f"Failed to refresh agent pool: {e}")

    def get_agent(self, resource_id: str) -> Optional[A2AAgentHandle]:
        return self.pool.get(resource_id)

    def trigger_agent(self, resource_id: str, task_id: str, goal: str):
        """
        SYNC ENTRY POINT: Triggers an agent via A2A in the background.
        This is what the Hub logic calls.
        """
        if not self._loop:
            logger.error("Supervisor loop not started. Call bootstrap() first.")
            return

        handle = self.get_agent(resource_id)
        if not handle:
            logger.error(f"No agent found for resource: {resource_id}")
            return

        # Schedule the async trigger in the background thread
        asyncio.run_coroutine_threadsafe(
            self._async_trigger(handle, task_id, goal), 
            self._loop
        )
        logger.info(f"Trigger signal sent to background for {resource_id} (Task: {task_id})")

    async def _async_trigger(self, handle: A2AAgentHandle, task_id: str, goal: str):
        """Internal async method to maintain the A2A channel and stream logs."""
        try:
            logger.info(f"A2A Channel Opening: {handle.resource_id} for Task {task_id}")
            
            # Use proper ADK Content structure
            from google.genai import types as genai_types
            message = genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=f"EXECUTE_TASK: {task_id}\nGOAL: {goal}")]
            )
            
            async for event in handle.runner.run_async(
                session_id=task_id,
                user_id="hub_system",
                new_message=message
            ):
                # Here is where we "maintain the channel"
                # We can pipe these events to task_logs table later
                if event.content and event.content.parts:
                    text = "".join([p.text for p in event.content.parts if p.text])
                    if text.strip():
                        logger.debug(f"[{handle.resource_id}] {text[:50]}...")
                
            logger.info(f"A2A Channel Closed gracefully for {handle.resource_id}")
        except Exception as e:
            logger.error(f"A2A Channel Error for {handle.resource_id}: {e}")
            # Potential for auto-retry logic here

agent_supervisor = AgentSupervisor()
