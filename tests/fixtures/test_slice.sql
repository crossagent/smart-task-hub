-- ==============================================================================
--  TEST SLICE - REFINED (Module-Centric Schema)
--  Idempotent seed data for Integration Tests
-- ==============================================================================

-- 1. CLEANUP
TRUNCATE task_assignments, events, tasks, milestones, modules, activities, resources, system_state CASCADE;

-- 2. RESOURCES
INSERT INTO resources (id, name, org_role, is_available, resource_type) VALUES
('RES-ARCHITECT-001', 'System Architect', 'Control Plane', TRUE,  'agent'),
('RES-CODER-001',     'Coder One',        'Coder',         TRUE,  'human'),
('RES-CODER-002',     'Bob Coder',        'Coder',         FALSE, 'human'),
('RES-CODER-003',     'Coder Three',      'Coder',         TRUE,  'human'),
('RES-CODER-004',     'Dave Coder',       'Coder',         TRUE,  'human'),
('RES-CODER-005',     'Eve Coder',        'Coder',         TRUE,  'human');

-- 3. MODULES (Physical Entities)
INSERT INTO modules (id, name, owner_res_id, local_path, repo_url, entity_type) VALUES
('MOD-ROOT',      'System Root',   'RES-ARCHITECT-001', '/app',           'git://hub.local/root',    'Code'),
('MOD-AUTH',      'Auth Service',  'RES-CODER-001',     '/app/src/auth',  'git://hub.local/auth',    'Code'),
('MOD-DB',        'DB Layer',      'RES-CODER-002',     '/app/src/db',    'git://hub.local/db',      'Code'),
('MOD-UI',        'Frontend UI',   'RES-CODER-003',     '/app/src/ui',    'git://hub.local/ui',      'Code'),
('MOD-DOCS',      'System Docs',   'RES-ARCHITECT-001', '/app/docs',      'git://hub.local/docs',    'Document');

-- 4. ACTIVITIES
INSERT INTO activities (id, name, owner_res_id, status) VALUES
('ACT-LIVE-001',  'Production Migration', 'RES-ARCHITECT-001', 'Active'),
('ACT-STALL-001', 'Integration Testing',  'RES-ARCHITECT-001', 'Active');

-- 5. MILESTONES
INSERT INTO milestones (id, activity_id, name, target_date, status) VALUES
('MS-LIVE-1', 'ACT-LIVE-001', 'Auth Service Ready', '2026-05-01', 'Pending'),
('MS-LIVE-2', 'ACT-LIVE-001', 'UI Redesign Complete', '2026-05-15', 'Pending');

-- 6. TASKS
INSERT INTO tasks (id, activity_id, milestone_id, module_id, module_iteration_goal, status) VALUES
-- Terminal States
('TSK-DONE-001',  'ACT-STALL-001', NULL, 'MOD-DB',   'Setup DB Schema',   'done'),
('TSK-FAIL-001',  'ACT-STALL-001', NULL, 'MOD-AUTH', 'Init Auth Config',  'failed'),
('TSK-BLOCK-001', 'ACT-STALL-001', NULL, 'MOD-UI',   'Design Login UI',   'blocked'),

-- Pending / Ready States
('TSK-PEND-001',  'ACT-LIVE-001', 'MS-LIVE-1',  'MOD-AUTH', 'Implement OAuth2',  'pending'),
('TSK-PEND-002',  'ACT-LIVE-001', 'MS-LIVE-2',  'MOD-DOCS', 'Write API Docs',    'pending'),
('TSK-AWAIT-001', 'ACT-LIVE-001', 'MS-LIVE-2',  'MOD-UI',   'Build Dashboard',   'pending'),
('TSK-READY-001', 'ACT-LIVE-001', NULL,         'MOD-UI',   'Fix CSS Bugs',      'ready'),

-- In-Progress (Running)
('TSK-RUN-001',   'ACT-LIVE-001', 'MS-LIVE-1',  'MOD-DB',   'Optimize Queries',  'in_progress');

-- Set dependencies
UPDATE tasks SET depends_on = '{TSK-DONE-001}' WHERE id = 'TSK-PEND-001';

-- 7. ASSIGNMENTS
INSERT INTO task_assignments (task_id, resource_id, status) VALUES
('TSK-RUN-001', 'RES-CODER-002', 'active');

-- 8. SYSTEM STATE
INSERT INTO system_state (key, value) VALUES 
('run_mode', '"auto"'),
('step_count', '0');
