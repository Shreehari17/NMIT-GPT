-- Person 2 v2: review this SQL before installing. NO DATA MODIFIED BY INSTALLATION.
-- Both RPCs are restricted to server-side service_role. Never expose that key.
-- Run on a staging Supabase project first. Existing public.replace_class_timetable
-- is not used by the v2 backend; review/revoke it separately if installed.

CREATE OR REPLACE FUNCTION public.timetable_class_revision(p_class text)
RETURNS text
LANGUAGE sql SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
  SELECT md5(COALESCE(
    (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)::text
       FROM public.timetable AS t WHERE t."class" = p_class),
    '[]'
  ));
$$;
REVOKE ALL ON FUNCTION public.timetable_class_revision(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.timetable_class_revision(text) TO service_role;

CREATE OR REPLACE FUNCTION public.replace_class_timetable_v2(
    p_class text, p_rows jsonb, p_department text, p_expected_revision text
) RETURNS integer
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_count integer;
    v_revision text;
BEGIN
    IF p_class IS NULL OR btrim(p_class) = '' OR length(p_class) > 80 THEN
        RAISE EXCEPTION 'Invalid class';
    END IF;
    IF p_department IS NULL OR btrim(p_department) = ''
       OR length(p_department) > 50 THEN
        RAISE EXCEPTION 'Department is required';
    END IF;
    IF p_expected_revision IS NULL OR p_expected_revision !~ '^[0-9a-f]{32}$' THEN
        RAISE EXCEPTION 'Class revision is required';
    END IF;
    IF p_rows IS NULL OR jsonb_typeof(p_rows) <> 'array' THEN
        RAISE EXCEPTION 'Rows must be an array';
    END IF;
    v_count := jsonb_array_length(p_rows);
    IF v_count < 1 OR v_count > 500 THEN
        RAISE EXCEPTION 'Invalid row count';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_rows) AS j(row_data)
        WHERE jsonb_typeof(row_data) <> 'object'
           OR row_data->>'class' IS DISTINCT FROM p_class
           OR NULLIF(btrim(row_data->>'day_of_week'), '') IS NULL
           OR NULLIF(btrim(row_data->>'time_slot'), '') IS NULL
           OR (NULLIF(btrim(row_data->>'subject_code'), '') IS NULL
               AND NULLIF(btrim(row_data->>'activity'), '') IS NULL)
           OR coalesce(row_data->>'subject_code','') ~* 'REVIEW[[:space:]]+REQUIRED'
           OR coalesce(row_data->>'activity','') ~* 'REVIEW[[:space:]]+REQUIRED'
    ) THEN
        RAISE EXCEPTION 'Incomplete or mixed-class rows';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_to_recordset(p_rows) AS x(
            class text, day_of_week text, time_slot text,
            subject_code text, activity text, is_lab boolean, lab_id text
        )
        GROUP BY x.class, x.day_of_week, x.time_slot HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate class/day/time slot';
    END IF;

    -- Lock only this exact class; this does not match 6A-A1 when p_class='6A'.
    PERFORM pg_advisory_xact_lock(hashtextextended('timetable:' || p_class, 0));
    SELECT md5(COALESCE(
      (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)::text
         FROM public.timetable AS t WHERE t."class" = p_class), '[]'
    )) INTO v_revision;
    IF v_revision IS DISTINCT FROM p_expected_revision THEN
        RAISE EXCEPTION 'Timetable changed since preview; save cancelled';
    END IF;

    DELETE FROM public.timetable WHERE "class" = p_class;
    INSERT INTO public.timetable (
        "class", day_of_week, time_slot, subject_code,
        activity, is_lab, lab_id, "Dept"
    )
    SELECT p_class, x.day_of_week, x.time_slot,
           NULLIF(x.subject_code, ''), NULLIF(x.activity, ''),
           coalesce(x.is_lab, false), NULLIF(x.lab_id, ''), p_department
    FROM jsonb_to_recordset(p_rows) AS x(
        class text, day_of_week text, time_slot text,
        subject_code text, activity text, is_lab boolean, lab_id text
    );
    RETURN v_count;
END;
$$;
REVOKE ALL ON FUNCTION public.replace_class_timetable_v2(text, jsonb, text, text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.replace_class_timetable_v2(text, jsonb, text, text)
    TO service_role;
