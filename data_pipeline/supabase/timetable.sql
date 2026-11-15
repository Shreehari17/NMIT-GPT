CREATE TABLE timetable (
    id BIGSERIAL PRIMARY KEY,
    class VARCHAR NOT NULL,
    day_of_week VARCHAR NOT NULL,
    time_slot VARCHAR NOT NULL,
    subject_code VARCHAR,
    activity TEXT,
    is_lab BOOLEAN DEFAULT FALSE,
    lab_id VARCHAR,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT timetable_lab_fk
        FOREIGN KEY (lab_id)
        REFERENCES lab_infrastructure(lab_id)
        ON DELETE SET NULL
);
