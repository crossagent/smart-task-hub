-- ==============================================================================
--  SMART TASK HUB - REFINED SCHEMA (Module-Centric & Decoupled Execution)
-- ==============================================================================

-- 0. CLEANUP
DROP TABLE IF EXISTS task_assignments CASCADE;
DROP TABLE IF EXISTS events CASCADE;
DROP TABLE IF EXISTS tasks CASCADE;
DROP TABLE IF EXISTS milestones CASCADE;
DROP TABLE IF EXISTS modules CASCADE;
DROP TABLE IF EXISTS activities CASCADE;
DROP TABLE IF EXISTS projects CASCADE;
DROP TABLE IF EXISTS resources CASCADE;
DROP TABLE IF EXISTS system_state CASCADE;
DROP TABLE IF EXISTS blueprint_plans CASCADE;

-- 1. UTILITIES
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 2. RESOURCES (Compute Slots / Agent Identities)
-- Represents WHO can do work.
CREATE TABLE IF NOT EXISTS resources (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50) DEFAULT 'human', -- human | agent
    org_role VARCHAR(255) NOT NULL,            -- e.g., Senior Architect, Coder
    is_available BOOLEAN DEFAULT TRUE,
    status VARCHAR(50) DEFAULT 'Available',    -- Available | Busy | Away
    dingtalk_id VARCHAR(100),
    professional_skill VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. ACTIVITIES (Execution Strategies)
-- Represents the "How" (The roadmap for engineering).
CREATE TABLE IF NOT EXISTS activities (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    owner_res_id VARCHAR(50) NOT NULL REFERENCES resources(id),
    status VARCHAR(50) DEFAULT 'Active',
    priority VARCHAR(10) DEFAULT 'P1',
    benefit TEXT,
    deadline DATE,
    artifact TEXT,                             -- Final deliverable for the activity
    user_instruction TEXT,
    instruction_version INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 4. MILESTONES (Key Timeline Nodes)
-- Represents major goals within an activity.
CREATE TABLE IF NOT EXISTS milestones (
    id VARCHAR(50) PRIMARY KEY,
    activity_id VARCHAR(50) NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    target_date DATE,
    status VARCHAR(50) DEFAULT 'Pending',      -- Pending | Achieved | Missed
    reached_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 5. MODULES (Physical Entities)
-- Represents the "What" (The actual code/docs/assets).
-- Independent of specific projects.
CREATE TABLE IF NOT EXISTS modules (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    owner_res_id VARCHAR(50) NOT NULL REFERENCES resources(id),
    parent_module_id VARCHAR(50) REFERENCES modules(id) ON DELETE SET NULL,
    local_path TEXT,                           -- The "work_slot" / Folder path
    repo_url TEXT,                             -- Repository link
    knowledge_base TEXT,
    layer_type VARCHAR(100),                   -- L1-Domain | L2-Service | L3-Component
    entity_type VARCHAR(100) DEFAULT 'Code',   -- Code | Document | Asset
    status VARCHAR(50) DEFAULT 'Active',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 6. TASKS (Actionable State Mutations)
-- Represents the "Step" (Moving a module to a new state).
CREATE TABLE IF NOT EXISTS tasks (
    id VARCHAR(50) PRIMARY KEY,
    activity_id VARCHAR(50) REFERENCES activities(id) ON DELETE CASCADE,
    milestone_id VARCHAR(50) REFERENCES milestones(id) ON DELETE SET NULL,
    module_id VARCHAR(50) NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    module_iteration_goal TEXT NOT NULL,       -- The "Soul" of the task
    status VARCHAR(50) DEFAULT 'pending',      -- pending | ready | in_progress | done | failed | blocked
    depends_on VARCHAR(50)[] DEFAULT '{}',     -- DAG dependencies
    estimated_hours DECIMAL(10,2),
    execution_result TEXT,
    artifact TEXT,                             -- The specific output of this task
    blocker_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 7. TASK_ASSIGNMENTS (Execution Records / Man-hour tracking)
-- Represents the "Execution" (Linking a task to a resource over time).
CREATE TABLE IF NOT EXISTS task_assignments (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(50) NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    resource_id VARCHAR(50) NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    status VARCHAR(50) DEFAULT 'active',       -- active | completed | failed | abandoned
    man_hours DECIMAL(10,2) DEFAULT 0,
    memo TEXT                                  -- Notes from the execution session
);

-- 8. SYSTEM STATE (Control Flags)
CREATE TABLE IF NOT EXISTS system_state (
    key VARCHAR(255) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 9. EVENTS (System Event Bus)
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    source VARCHAR(100) NOT NULL,
    severity VARCHAR(10) DEFAULT 'normal',
    activity_id VARCHAR(50) REFERENCES activities(id),
    task_id VARCHAR(50),
    resource_id VARCHAR(50) REFERENCES resources(id),
    payload JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'pending',
    resolved_by VARCHAR(50),                   -- Task ID that resolved this event
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ
);

-- 10. BLUEPRINT MODIFICATION PLANS
CREATE TABLE IF NOT EXISTS blueprint_plans (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    activity_id VARCHAR(50) REFERENCES activities(id) ON DELETE CASCADE,
    status VARCHAR(50) DEFAULT 'pending',      -- pending | approved | rejected | executed | failed_execution
    proposed_actions JSONB NOT NULL,           -- List of {op, table, data, where}
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 11. TRIGGERS
DROP TRIGGER IF EXISTS update_resources_modtime ON resources;
CREATE TRIGGER update_resources_modtime BEFORE UPDATE ON resources FOR EACH ROW EXECUTE FUNCTION update_modified_column();

DROP TRIGGER IF EXISTS update_activities_modtime ON activities;
CREATE TRIGGER update_activities_modtime BEFORE UPDATE ON activities FOR EACH ROW EXECUTE FUNCTION update_modified_column();

DROP TRIGGER IF EXISTS update_milestones_modtime ON milestones;
CREATE TRIGGER update_milestones_modtime BEFORE UPDATE ON milestones FOR EACH ROW EXECUTE FUNCTION update_modified_column();

DROP TRIGGER IF EXISTS update_modules_modtime ON modules;
CREATE TRIGGER update_modules_modtime BEFORE UPDATE ON modules FOR EACH ROW EXECUTE FUNCTION update_modified_column();

DROP TRIGGER IF EXISTS update_tasks_modtime ON tasks;
CREATE TRIGGER update_tasks_modtime BEFORE UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION update_modified_column();

DROP TRIGGER IF EXISTS update_blueprint_plans_modtime ON blueprint_plans;
CREATE TRIGGER update_blueprint_plans_modtime BEFORE UPDATE ON blueprint_plans FOR EACH ROW EXECUTE FUNCTION update_modified_column();

-- DEFAULT DATA
INSERT INTO resources (id, name, org_role, is_available, resource_type) 
VALUES ('RES-ARCHITECT-001', 'System Architect', 'Control Plane', TRUE, 'agent') ON CONFLICT (id) DO NOTHING;

INSERT INTO system_state (key, value) VALUES ('run_mode', '"auto"') ON CONFLICT (key) DO NOTHING;
INSERT INTO system_state (key, value) VALUES ('step_count', '0') ON CONFLICT (key) DO NOTHING;
