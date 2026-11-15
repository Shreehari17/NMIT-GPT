CREATE TABLE subjects (
    subject_code VARCHAR NOT NULL,
    class VARCHAR NOT NULL,
    subject_name TEXT NOT NULL,
    subject_initials VARCHAR NOT NULL,
    faculty_id VARCHAR NOT NULL,
    lab_id VARCHAR,
    classroom VARCHAR,
    PRIMARY KEY (subject_code, class, faculty_id),
    CONSTRAINT subjects_faculty_fk
        FOREIGN KEY (faculty_id)
        REFERENCES faculty_biodata(faculty_id)
        ON DELETE CASCADE,
    CONSTRAINT subjects_lab_fk
        FOREIGN KEY (lab_id)
        REFERENCES lab_infrastructure(lab_id)
        ON DELETE SET NULL
);
