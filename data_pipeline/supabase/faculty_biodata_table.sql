CREATE TABLE faculty_biodata (
    faculty_id VARCHAR(50) PRIMARY KEY,

    name VARCHAR(200),
    designation VARCHAR(100),
    department VARCHAR(200),

    email TEXT[],
    joining_date DATE,

    educational_qualifications TEXT[],
    past_experience TEXT[],
    areas_of_interest TEXT[],
    achievements TEXT[],
    subjects_taught TEXT[],

    scholar_id TEXT[],
    orcid_id TEXT[],
    linkedin_id TEXT[],

    research TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_faculty_timestamp
BEFORE UPDATE ON faculty_biodata
FOR EACH ROW
EXECUTE FUNCTION update_timestamp();
