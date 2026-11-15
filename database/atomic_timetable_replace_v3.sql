-- NMIT GPT Person 2 v3. INSTALL ON STAGING FIRST.
-- This replaces only the two RPC definitions; it does NOT modify timetable data.
-- Backend continues to call replace_class_timetable_v2 with the same arguments.
-- SECURITY INVOKER; intended for trusted backend service_role only.

CREATE OR REPLACE FUNCTION public.timetable_class_revision(p_class text)
RETURNS text
LANGUAGE sql
SECURITY INVOKER
SET search_path = pg_catalog, public, pg_temp
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
)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_count integer;
    v_revision text;
    v_rec record;
    v_start integer;
    v_end integer;
    v_prev_end integer;
    v_prev_slot text;
    v_prev_day text;
BEGIN
    IF p_class IS NULL OR btrim(p_class) = '' OR length(p_class) > 80 THEN
        RAISE EXCEPTION 'Invalid class' USING ERRCODE = '22023';
    END IF;
    IF p_department IS NULL OR btrim(p_department) = ''
       OR length(p_department) > 50 THEN
        RAISE EXCEPTION 'Department is required' USING ERRCODE = '22023';
    END IF;
    IF p_expected_revision IS NULL OR p_expected_revision !~ '^[0-9a-f]{32}$' THEN
        RAISE EXCEPTION 'Class revision is required' USING ERRCODE = '22023';
    END IF;
    IF p_rows IS NULL OR jsonb_typeof(p_rows) <> 'array' THEN
        RAISE EXCEPTION 'Rows must be an array' USING ERRCODE = '22023';
    END IF;
    v_count := jsonb_array_length(p_rows);
    IF v_count NOT BETWEEN 1 AND 500 THEN
        RAISE EXCEPTION 'Invalid row count' USING ERRCODE = '22023';
    END IF;

    -- Check raw JSON types before casting jsonb_to_recordset, avoiding silent coercion.
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_rows) AS j(row_data)
        WHERE jsonb_typeof(j.row_data) IS DISTINCT FROM 'object'
           OR j.row_data->>'class' IS DISTINCT FROM p_class
           OR jsonb_typeof(j.row_data->'class') IS DISTINCT FROM 'string'
           OR jsonb_typeof(j.row_data->'day_of_week') IS DISTINCT FROM 'string'
           OR jsonb_typeof(j.row_data->'time_slot') IS DISTINCT FROM 'string'
           OR (j.row_data ? 'subject_code' AND jsonb_typeof(j.row_data->'subject_code') NOT IN ('string','null'))
           OR (j.row_data ? 'activity' AND jsonb_typeof(j.row_data->'activity') NOT IN ('string','null'))
           OR (j.row_data ? 'lab_id' AND jsonb_typeof(j.row_data->'lab_id') NOT IN ('string','null'))
           OR (j.row_data ? 'is_lab' AND jsonb_typeof(j.row_data->'is_lab') NOT IN ('boolean','null'))
           OR NULLIF(btrim(j.row_data->>'subject_code'), '') IS NULL
              AND NULLIF(btrim(j.row_data->>'activity'), '') IS NULL
           OR coalesce(j.row_data->>'subject_code','') ~* 'REVIEW[[:space:]]+REQUIRED'
           OR coalesce(j.row_data->>'activity','') ~* 'REVIEW[[:space:]]+REQUIRED'
           OR coalesce(j.row_data->>'lab_id','') ~* 'REVIEW[[:space:]]+REQUIRED'
           OR length(coalesce(j.row_data->>'subject_code','')) > 200
           OR length(coalesce(j.row_data->>'activity','')) > 500
           OR length(coalesce(j.row_data->>'lab_id','')) > 120
           OR (NULLIF(j.row_data->>'lab_id', '') IS NOT NULL
               AND (coalesce(j.row_data->>'lab_id','') !~ '^LAB[1-9][0-9]*$'
                    OR j.row_data->>'is_lab' IS DISTINCT FROM 'true'))
    ) THEN
        RAISE EXCEPTION 'Malformed, mixed-class, or unresolved timetable rows'
          USING ERRCODE = '22023';
    END IF;

    -- Validate normalized weekday names and 24-hour HH:MM-HH:MM format.
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_rows) AS j(row_data)
        WHERE j.row_data->>'day_of_week' NOT IN (
            'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'
        )
        OR j.row_data->>'time_slot' !~
            '^([01][0-9]|2[0-3]):[0-5][0-9]-([01][0-9]|2[0-3]):[0-5][0-9]$'
    ) THEN
        RAISE EXCEPTION 'Invalid weekday or 24-hour time slot'
          USING ERRCODE = '22023';
    END IF;

    -- Iterate ordered intervals per day; reject zero duration, inverted or overlapping slots.
    v_prev_end := NULL;
    v_prev_day := NULL;
    FOR v_rec IN
        SELECT j.row_data->>'day_of_week' AS day_name,
               j.row_data->>'time_slot' AS slot_name
        FROM jsonb_array_elements(p_rows) AS j(row_data)
        ORDER BY j.row_data->>'day_of_week',
                 substring(j.row_data->>'time_slot' FROM 1 FOR 5)
    LOOP
        v_start := substring(v_rec.slot_name FROM 1 FOR 2)::integer * 60
                   + substring(v_rec.slot_name FROM 4 FOR 2)::integer;
        v_end := substring(v_rec.slot_name FROM 7 FOR 2)::integer * 60
                 + substring(v_rec.slot_name FROM 10 FOR 2)::integer;
        IF v_end <= v_start THEN
            RAISE EXCEPTION 'Invalid time interval: %', v_rec.slot_name
              USING ERRCODE = '22023';
        END IF;
        IF v_rec.day_name = v_prev_day AND v_start < v_prev_end THEN
            RAISE EXCEPTION 'Overlapping timetable slots: % and %',
                v_prev_slot, v_rec.slot_name USING ERRCODE = '22023';
        END IF;
        v_prev_day := v_rec.day_name;
        v_prev_end := v_end;
        v_prev_slot := v_rec.slot_name;
    END LOOP;

    -- Cooperating saves of the same class serialize here.
    PERFORM pg_advisory_xact_lock(hashtextextended('timetable:' || p_class, 0));
    SELECT md5(COALESCE(
      (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)::text
       FROM public.timetable AS t WHERE t."class" = p_class), '[]'
    )) INTO v_revision;
    IF v_revision IS DISTINCT FROM p_expected_revision THEN
        RAISE EXCEPTION 'Timetable changed since preview; save cancelled'
          USING ERRCODE = '40001';
    END IF;

    -- DELETE and INSERT share one transaction: errors roll the entire RPC back.
    -- Exact class match does not touch subgroup classes.
    DELETE FROM public.timetable WHERE "class" = p_class;
    INSERT INTO public.timetable (
        "class", day_of_week, time_slot, subject_code,
        activity, is_lab, lab_id, "Dept"
    )
    SELECT p_class,
           x.day_of_week, x.time_slot,
           NULLIF(btrim(x.subject_code), ''), NULLIF(btrim(x.activity), ''),
           coalesce(x.is_lab, false), NULLIF(btrim(x.lab_id), ''),
           p_department
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
