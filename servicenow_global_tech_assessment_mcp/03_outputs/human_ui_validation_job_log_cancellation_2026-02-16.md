# Human UI Validation — Job Log Cancellation (2026-02-16)

## Goal
Verify the unified Job Log supports:
- per-row **Cancel** for active jobs (`running` / `pending`)
- top-level **Cancel All Active Jobs**
- action button disappears after cancellation

## Preconditions
- App is running.
- At least one active job exists (preflight pull, CSDM ingestion, assessment scan, dictionary pull, or postflight pull).

## Steps
1. Open `Job Log` from top navigation.
2. Confirm active rows show a `Cancel` button in the new `Actions` column.
3. Click `Cancel` on one active row and confirm.
4. Verify that row status changes to `cancelled` (or no longer `running`/`pending`) after refresh.
5. Verify that row's `Cancel` button is no longer shown.
6. Start or keep multiple active jobs, then click `Cancel All Active Jobs`.
7. Verify active rows are cancelled and `Cancel` buttons disappear from those rows.
8. Optional filter test: apply a condition (for example, one instance/module), run `Cancel All Active Jobs`, and verify only filtered active jobs were cancelled.

## Notes
- Error/failed/completed/cancelled rows should not show per-row cancel actions.
- `Cancel All Active Jobs` targets active jobs in the current filtered view.
