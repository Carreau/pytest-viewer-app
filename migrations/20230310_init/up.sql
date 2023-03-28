CREATE TABLE action_run (
	id TEXT PRIMARY KEY DEFAULT gen_random_uuid(),
	organization TEXT NOT NULL,
	repo TEXT NOT NULL,
	run_id INTEGER NOT NULL,
	pull_number INTEGER NOT NULL,
	
	CONSTRAINT action_run_unique UNIQUE(organization, repo, run_id, pull_number)
);
