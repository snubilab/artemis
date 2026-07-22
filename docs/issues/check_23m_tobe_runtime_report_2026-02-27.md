# check_23m.py To-Be Runtime Report

- Measured at: 2026-02-27 18:00:51 KST
- Script: `/tmp/check_23m.py` (optimized To-Be version)
- Command:
  - `/usr/bin/time -p python3 /tmp/check_23m.py`
- Database target:
  - host `localhost`, db `ohdsi`, schema `synthea23m`

## Runtime

- `real`: **76.86s**
- `user`: `0.03s`
- `sys`: `0.04s`

## Result Snapshot

- SYNTHEA23M total patients: `2,709,803`
- Drug counts and condition counts were printed successfully (no execution error).

## Notes

- This is a single-run measurement on the current machine and DB state.
- Runtime can vary depending on PostgreSQL cache/index state and concurrent DB load.
