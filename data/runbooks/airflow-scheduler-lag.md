# Airflow scheduler heartbeat lag

**Symptom.** DAGs start minutes later than their schedule. The scheduler is
alive but `scheduler_heartbeat_lag_s` is climbing above 30 seconds.

## Triage

1. Check the number of DAG files being parsed. Parsing time scales with file
   count, and a single slow import blocks the whole parse loop.
2. Look for top-level code in DAG files — database calls or API requests
   outside a task function run on every parse, not once per run.
3. Check `max_active_runs` and the size of the task queue. A backfill will
   starve the scheduler of slots.

## Fix

- Move any top-level I/O inside the task callable. This is the cause in the
  large majority of cases.
- Raise `min_file_process_interval` so the scheduler re-parses less often.
- Pause backfills during business hours.

## Escalate

If lag exceeds 120 seconds, or scheduled SLAs are being missed, page the on-call
engineer — a scheduler restart may be required and that needs a second pair of eyes.
