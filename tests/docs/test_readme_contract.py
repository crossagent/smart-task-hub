from pathlib import Path


README_PATH = Path(__file__).resolve().parents[3] / "README.md"


def test_readme_states_milestone_activity_task_time_axis():
  """README should describe the current governance hierarchy."""
  readme = README_PATH.read_text(encoding="utf-8")

  assert "Milestone → Activity → Task" in readme
  assert "Project" not in readme
  assert "项目池" not in readme


def test_readme_only_advertises_current_mcp_tools():
  """README should not advertise planned MCP tools as implemented."""
  readme = README_PATH.read_text(encoding="utf-8")

  planned_or_removed_tools = (
      "upsert_project",
      "upsert_task",
      "get_task_logs",
      "get_activity_schedule_report",
      "list_tasks_for_review",
      "approve_task",
      "reject_task",
      "is_approved",
      "awaiting_approval",
  )

  for tool_name in planned_or_removed_tools:
    assert tool_name not in readme
