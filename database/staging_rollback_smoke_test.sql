-- RUN ONLY in STAGING after installing atomic_timetable_replace_v3.sql.
-- The whole test runs inside a transaction that is ROLLED BACK.
-- SQL Editor executes as its configured database role (often postgres),
-- not as a simulated authenticated user. Role permission tests need separate credentials.
BEGIN;
DO $test$
DECLARE
  cls text := '__NMIT_P2_V3_SMOKE__';
  subgroup text := '__NMIT_P2_V3_SMOKE__-A1';
  initial_rev text;
  new_rev text;
  inserted integer;
  raised boolean;
  after_count integer;
BEGIN
  IF EXISTS(SELECT 1 FROM public.timetable WHERE "class" IN (cls, subgroup)) THEN
    RAISE EXCEPTION 'Test classes already exist; aborting';
  END IF;

  -- A subgroup sentinel must survive a main-class replacement.
  INSERT INTO public.timetable ("class", day_of_week, time_slot, activity, is_lab, "Dept")
  VALUES (subgroup, 'Monday', '10:00-10:55', 'Subgroup sentinel', false, 'CSE');

  SELECT public.timetable_class_revision(cls) INTO initial_rev;
  SELECT public.replace_class_timetable_v2(
    cls,
    '[{"class":"__NMIT_P2_V3_SMOKE__","day_of_week":"Monday","time_slot":"09:00-09:55","subject_code":"TEST101","is_lab":false},
      {"class":"__NMIT_P2_V3_SMOKE__","day_of_week":"Monday","time_slot":"09:55-10:05","activity":"BREAK","is_lab":false}]'::jsonb,
    'CSE', initial_rev
  ) INTO inserted;
  IF inserted != 2 THEN RAISE EXCEPTION 'Initial insert count incorrect'; END IF;
  SELECT count(*) INTO after_count FROM public.timetable WHERE "class" = cls;
  IF after_count != 2 THEN RAISE EXCEPTION 'Initial insert failed'; END IF;

  SELECT public.timetable_class_revision(cls) INTO new_rev;
  -- A stale revision must reject without losing the initial rows.
  raised := false;
  BEGIN
    PERFORM public.replace_class_timetable_v2(
      cls,
      '[{"class":"__NMIT_P2_V3_SMOKE__","day_of_week":"Monday","time_slot":"09:00-10:00","activity":"New"}]'::jsonb,
      'CSE', initial_rev);
  EXCEPTION WHEN SQLSTATE '40001' THEN raised := true;
  END;
  IF NOT raised THEN RAISE EXCEPTION 'Stale revision was not rejected'; END IF;

  -- Overlap must reject even with a fresh revision.
  raised := false;
  BEGIN
    PERFORM public.replace_class_timetable_v2(
      cls,
      '[{"class":"__NMIT_P2_V3_SMOKE__","day_of_week":"Monday","time_slot":"09:00-09:55","activity":"A"},
        {"class":"__NMIT_P2_V3_SMOKE__","day_of_week":"Monday","time_slot":"09:30-10:30","activity":"B"}]'::jsonb,
      'CSE', new_rev);
  EXCEPTION WHEN SQLSTATE '22023' THEN raised := true;
  END;
  IF NOT raised THEN RAISE EXCEPTION 'Overlap was not rejected'; END IF;

  -- Invalid clock hours must reject.
  raised := false;
  BEGIN
    PERFORM public.replace_class_timetable_v2(
      cls,
      '[{"class":"__NMIT_P2_V3_SMOKE__","day_of_week":"Monday","time_slot":"25:00-26:00","activity":"Bad clock"}]'::jsonb,
      'CSE', new_rev);
  EXCEPTION WHEN SQLSTATE '22023' THEN raised := true;
  END;
  IF NOT raised THEN RAISE EXCEPTION 'Invalid clock was not rejected'; END IF;

  -- Unknown lab FK must roll back the replacement.
  raised := false;
  BEGIN
    PERFORM public.replace_class_timetable_v2(
      cls,
      '[{"class":"__NMIT_P2_V3_SMOKE__","day_of_week":"Monday","time_slot":"09:00-09:55","subject_code":"TEST101","is_lab":true,"lab_id":"LAB999999999"}]'::jsonb,
      'CSE', new_rev);
  EXCEPTION WHEN foreign_key_violation THEN raised := true;
  END;
  IF NOT raised THEN RAISE EXCEPTION 'Invalid lab FK did not fail'; END IF;

  SELECT count(*) INTO after_count FROM public.timetable WHERE "class" = cls;
  IF after_count != 2 THEN RAISE EXCEPTION 'Rollback lost existing rows'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.timetable WHERE "class" = subgroup) THEN
    RAISE EXCEPTION 'Subgroup was accidentally modified';
  END IF;
  RAISE NOTICE 'STAGING SMOKE PASS: insert, stale revision, overlap, invalid time, FK rollback, subgroup isolation';
END;
$test$;
ROLLBACK;
