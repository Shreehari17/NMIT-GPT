CREATE TABLE academic_calendar (
  id SERIAL PRIMARY KEY,
  event_date DATE NOT NULL,
  event_name TEXT NOT NULL,
  event_type TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
