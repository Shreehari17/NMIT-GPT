-- Apply in Supabase SQL editor only after reviewing and backing up existing data.
-- Requires backend Supabase SERVICE_ROLE key; never expose that key to browser.
-- RPC uses caller permissions (SECURITY INVOKER) and performs delete + insert
-- in one PostgreSQL transaction. Failure rolls back both steps.
CREATE OR REPLACE FUNCTION public.replace_class_timetable(
    p_class text,
    p_rows jsonb
) RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_count integer;
BEGIN
    IF p_class IS NULL OR btrim(p_class) = '' OR length(p_class) > 80 THEN
        RAISE EXCEPTION 'Invalid class';
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
    ) THEN
        RAISE EXCEPTION 'Incomplete or mixed-class records';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_to_recordset(p_rows) AS x(
            class text, day_of_week text, time_slot text,
            subject_code text, activity text, is_lab boolean, lab_id text
        )
        GROUP BY x.class, x.day_of_week, x.time_slot
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate class/day/time slot';
    END IF;

    -- Serialize concurrent replaces of the same class.
    PERFORM pg_advisory_xact_lock(hashtextextended('timetable:' || p_class, 0));

    DELETE FROM public.timetable WHERE "class" = p_class;
    INSERT INTO public.timetable (
        "class", day_of_week, time_slot, subject_code, activity, is_lab, lab_id
    )
    SELECT p_class, x.day_of_week, x.time_slot,
           NULLIF(x.subject_code, ''), NULLIF(x.activity, ''),
           coalesce(x.is_lab, false), NULLIF(x.lab_id, '')
    FROM jsonb_to_recordset(p_rows) AS x(
        class text, day_of_week text, time_slot text,
        subject_code text, activity text, is_lab boolean, lab_id text
    );
    RETURN v_count;
END;
$$;

-- Only server-side service-role requests can execute the replacement RPC.
REVOKE ALL ON FUNCTION public.replace_class_timetable(text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.replace_class_timetable(text, jsonb) FROM anon;
REVOKE ALL ON FUNCTION public.replace_class_timetable(text, jsonb) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.replace_class_timetable(text, jsonb) TO service_role;
