CREATE TABLE lab_infrastructure (
    lab_id VARCHAR(50) PRIMARY KEY,
    lab_name TEXT NOT NULL,
    room_number TEXT NOT NULL,
    no_of_computers INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE OR REPLACE FUNCTION update_lab_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_lab_timestamp
BEFORE UPDATE ON lab_infrastructure
FOR EACH ROW
EXECUTE FUNCTION update_lab_timestamp();

ALTER TABLE lab_infrastructure
ADD COLUMN brand_computer_counts JSONB;
ALTER TABLE lab_infrastructure
ADD COLUMN configuration_summary TEXT;
