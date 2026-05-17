from pathlib import Path


SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "init_smart_task.sql"
)


def _schema_sql() -> str:
  return SCHEMA_PATH.read_text(encoding="utf-8")


def test_activity_belongs_to_milestone():
  """Milestone is the temporal parent of execution activities."""
  schema = _schema_sql()

  assert "milestone_id VARCHAR(50) REFERENCES milestones(id)" in schema


def test_milestone_does_not_belong_to_activity():
  """Milestone should not be modeled as a child of activity."""
  schema = _schema_sql()

  milestone_table = schema.split(
      "CREATE TABLE IF NOT EXISTS milestones", maxsplit=1
  )[1].split("CREATE TABLE IF NOT EXISTS modules", maxsplit=1)[0]

  assert "activity_id" not in milestone_table
