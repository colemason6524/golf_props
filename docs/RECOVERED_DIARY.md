# Golf Props: recovered diary

Recovered from the live Azure working tree. Historical claims below are the authors' records; local test results are in `../../_recovery/evidence/`. The original journal is preserved, including legacy entries that the dashboard cannot parse.

Current valid entry: 2026-11-03T12:34:14+00:00 — **observing**.

Deployed reviewed 12-file display/price-readiness patch 2026-11-03 (~12:58Z): real-price display, coverage/unpriced reasons, settlement disclosure. Live suite 365 passed + 5 pre-existing environment failures (proven identical on baseline: durable activation state holds legacy grades by design). Cold-start rejected/disabled. Next observation WWT board due 11-04.

Watch: WWT board 11-04; recap fingerprint reconciliation before any re-post
Next action: Observe WWT board; reconcile recap fingerprint before re-posting corrected disclosure

Check-back rule: `{"kind": "calendar", "label": "Display patch deployed; watch WWT board", "target": 3, "baseline": "2026-11-03T12:34:14+00:00", "events": [], "target_date": null, "monitoring": false}`

Journal: 24 original entries; 24 readable by the dashboard. All entries parse.

## Full recovered timeline

### Entry 24 — 2026-11-03T12:34:14+00:00

Deployed reviewed 12-file display/price-readiness patch 2026-11-03 (~12:58Z): real-price display, coverage/unpriced reasons, settlement disclosure. Live suite 365 passed + 5 pre-existing environment failures (proven identical on baseline: durable activation state holds legacy grades by design). Cold-start rejected/disabled. Next observation WWT board due 11-04.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-11-03T12:34:14+00:00",
  "status": "observing",
  "summary": "Deployed reviewed 12-file display/price-readiness patch 2026-11-03 (~12:58Z): real-price display, coverage/unpriced reasons, settlement disclosure. Live suite 365 passed + 5 pre-existing environment failures (proven identical on baseline: durable activation state holds legacy grades by design). Cold-start rejected/disabled. Next observation WWT board due 11-04.",
  "experiment": null,
  "watching_for": "WWT board 11-04; recap fingerprint reconciliation before any re-post",
  "next_action": "Observe WWT board; reconcile recap fingerprint before re-posting corrected disclosure",
  "deployed": true,
  "git_commit": "7cbe7bb0f2c0b6417e331740b21e7b8d65b209ae",
  "check_back": {
    "kind": "calendar",
    "label": "Display patch deployed; watch WWT board",
    "target": 3,
    "baseline": "2026-11-03T12:34:14+00:00",
    "events": [],
    "target_date": null,
    "monitoring": false
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 23 — 2026-11-03T03:35:54+00:00

Cross-event model review remains planned. Mexico grade manifest covers 111 players with input hashes; that is not 111 independent events or evidence of priced ROI. No new recovery model changes deployed.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-11-03T03:35:54+00:00",
  "status": "observing",
  "summary": "Cross-event model review remains planned. Mexico grade manifest covers 111 players with input hashes; that is not 111 independent events or evidence of priced ROI. No new recovery model changes deployed.",
  "experiment": null,
  "watching_for": "Genuinely prospective event cohorts, event-level loss/calibration comparison, cold-start/uncertainty candidate and pre-start quote coverage.",
  "next_action": "Plan J: reuse archived manifests and existing challenger, deliver cross-event keep/change verdict or frozen paired future test, and stage a justified price-readiness improvement. No one-event retune or optional receipt reopening.",
  "deployed": false,
  "git_commit": "",
  "check_back": {
    "kind": "calendar",
    "label": "Mexico prospective grade verified; recap sent; research waits Nov4",
    "target": 2,
    "baseline": "2026-11-02T20:17:45+00:00",
    "events": [],
    "target_date": null,
    "monitoring": false
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 22 — 2026-11-02T20:17:45+00:00

Mexico Open prospective grade (read-only): manifest 2026-11-02T01:17Z, 111 players/target, top20 Brier improvement +0.0051 vs structural; recap receipt status sent HTTP204 (no message ID, established pattern). Single-event, no retune. Parked receipt branch untouched.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-11-02T20:17:45+00:00",
  "status": "observing",
  "summary": "Mexico Open prospective grade (read-only): manifest 2026-11-02T01:17Z, 111 players/target, top20 Brier improvement +0.0051 vs structural; recap receipt status sent HTTP204 (no message ID, established pattern). Single-event, no retune. Parked receipt branch untouched.",
  "experiment": null,
  "watching_for": "Nov4 cold-start revisit AND verified completed event",
  "next_action": "Nov4 revisit; frozen 365/8/20 unchanged",
  "deployed": false,
  "git_commit": "",
  "check_back": {
    "kind": "calendar",
    "label": "Mexico prospective grade verified; recap sent; research waits Nov4",
    "target": 2,
    "baseline": "2026-11-02T20:17:45+00:00",
    "events": [],
    "target_date": null,
    "monitoring": false
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 21 — 2026-10-28T20:43:48.404040+00:00

Cole decision Oct28: cold-start uncertainty challenger deferred roughly one week; no urgency to implement now. Natural Mexico board already checked, final recap remains pending verified event completion. Frozen365/8/20 and parked34ec0c5 stay unchanged.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-28T20:43:48.404040+00:00",
  "status": "observing",
  "summary": "Cole decision Oct28: cold-start uncertainty challenger deferred roughly one week; no urgency to implement now. Natural Mexico board already checked, final recap remains pending verified event completion. Frozen365/8/20 and parked34ec0c5 stay unchanged.",
  "experiment": null,
  "watching_for": "Current event's verified final grade/recap first; revisit research after one week.",
  "next_action": "Revisit the cold-start uncertainty paired prospective experiment on/after 2026-11-04 and after the current event grade is available. Preserve pre-start inputs and separate accuracy from optional market references. No challenger, repair, resend or schedule change now.",
  "deployed": true,
  "git_commit": "7cbe7bb0f2c0b6417e331740b21e7b8d65b209ae",
  "check_back": {
    "kind": "calendar",
    "label": "Golf research revisit 2026-11-04",
    "target": 7,
    "baseline": "2026-10-28T20:43:48.404040+00:00",
    "events": [],
    "target_date": null,
    "monitoring": false
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 20 — 2026-10-28T20:11:29.972272+00:00

Oct28 OpenCode/GLM natural-board check passed: VidantaWorld Mexico Open archive and saved payload produced06:17-06:22Z pre-start; receipt records sent, no message ID/readback. Winner quote disclosure105/120 priced and15 explicit unpriced; source/capture time and no placement prices disclosed. Frozen365/8/20 unchanged. Final recap is pending EVENT COMPLETION, not a failure. Bermuda demo remains human-confirmed. Correction: optional34ec0c5 receipt repair failed installed suite, rolled back to59c88b2 and PARKED; do NOT follow old instruction to finish it. Evidence: desktop operations/checkins-20261028/golf/RESULT.md.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-28T20:11:29.972272+00:00",
  "status": "observing",
  "summary": "Oct28 OpenCode/GLM natural-board check passed: VidantaWorld Mexico Open archive and saved payload produced06:17-06:22Z pre-start; receipt records sent, no message ID/readback. Winner quote disclosure105/120 priced and15 explicit unpriced; source/capture time and no placement prices disclosed. Frozen365/8/20 unchanged. Final recap is pending EVENT COMPLETION, not a failure. Bermuda demo remains human-confirmed. Correction: optional34ec0c5 receipt repair failed installed suite, rolled back to59c88b2 and PARKED; do NOT follow old instruction to finish it. Evidence: desktop operations/checkins-20261028/golf/RESULT.md.",
  "experiment": null,
  "watching_for": "Natural event-key final grade and final-recap receipt after verified tournament completion; no invented filename-date gate.",
  "next_action": "At event completion inspect the natural auto-grade and recap receipt, no rerun/resend. Proposed research only: paired prospective cold-start uncertainty challenger on identical pre-start inputs, prices external; identity fallback and Data-through disclosure are hypotheses for later review, not automatic repair work. Keep34ec0c5 parked. No new monitor created.",
  "deployed": true,
  "git_commit": "7cbe7bb0f2c0b6417e331740b21e7b8d65b209ae",
  "check_back": {
    "kind": "grade_event",
    "label": "Mexico Open final grade/receipt after event completion",
    "target": null,
    "baseline": "2026-10-28T20:11:29.972272+00:00",
    "events": [],
    "target_date": null,
    "monitoring": false
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 19 — 2026-10-28T03:30:47+00:00

Bermuda archived demo human-confirmed from complete Discord paste: October22-25 final, Austin Smotherman,117/120 graded. One HTTP204 accepted submission; sent receipt attempts1,no message ID; no-send repeat deduped. Reviewed source overlay59c88b2 on live GitHEAD7cbe7bb,349 installed tests. Historical priced ROI unavailable; no hindsight odds or selections. Future board price/source/capture-time disclosure enabled, natural publication unobserved.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-28T03:30:47+00:00",
  "status": "observing",
  "summary": "Bermuda archived demo human-confirmed from complete Discord paste: October22-25 final, Austin Smotherman,117/120 graded. One HTTP204 accepted submission; sent receipt attempts1,no message ID; no-send repeat deduped. Reviewed source overlay59c88b2 on live GitHEAD7cbe7bb,349 installed tests. Historical priced ROI unavailable; no hindsight odds or selections. Future board price/source/capture-time disclosure enabled, natural publication unobserved.",
  "experiment": "One authorized archived demo reached Discord and was human-confirmed; API message readback remains unavailable. Original frozen forecasts/grades preserved. Activation initialized; other history held.",
  "watching_for": "Next natural VidantaWorld Mexico Open board and final recap. Private one-shot observation a3f4eeff729a scheduled2026-10-28T06:35Z, after forecast due06:00Z and tick06:17Z. Receipt URL repair34ec0c5 staged with357 tests; independent review pending.",
  "next_action": "Inspect real saved/publication artifacts at scheduled observation without bypassing dedupe. Finish independent receipt-URL review before supervisor rollout; never resend confirmed demo for an ID. Watch event-key grading artifacts after next event finishes; no invented filename date gate.",
  "deployed": true,
  "git_commit": "7cbe7bb0f2c0b6417e331740b21e7b8d65b209ae",
  "check_back": {
    "kind": "grade_event",
    "label": "Next tournament final grade and delivery receipt",
    "target": null,
    "baseline": "2026-10-28T03:30:47+00:00",
    "events": [],
    "target_date": null,
    "monitoring": false
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 18 — 2026-10-27T22:19:37+00:00

Bermuda Championship prospective grade completed 2026-10-26: the original forecast was genuinely pre-event, all three manifest output hashes were verified, winner Austin Smotherman; report top20 gap +0.0037 (the earlier +0.011 claim is withdrawn). Private dashboard now maps tournament grades; no regrade and no retune.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-27T22:19:37+00:00",
  "status": "observing",
  "summary": "Bermuda Championship prospective grade completed 2026-10-26: the original forecast was genuinely pre-event, all three manifest output hashes were verified, winner Austin Smotherman; report top20 gap +0.0037 (the earlier +0.011 claim is withdrawn). Private dashboard now maps tournament grades; no regrade and no retune.",
  "experiment": null,
  "watching_for": "Next graded tournament report under data/interim/reports/forecast_grading/",
  "next_action": "When the next event grades, read the report and manifest hashes; do not retune the model from one grade.",
  "deployed": false,
  "git_commit": "",
  "check_back": {
    "kind": "grade_event",
    "label": "Next tournament forecast grade",
    "target": null,
    "baseline": "2026-10-27T22:19:37.368654+00:00",
    "events": [],
    "target_date": null,
    "monitoring": false
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 17 — 2026-10-23T15:31:41+00:00

Frozen-manifest dual-source resolution landed. The live path data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json (SHA-256 8ee96b9f..., hard-coded at pipelines/weekly_forecast.py WeeklyPaths.manifest) is now the documented single source of truth: docs/INTEGRITY_AUDIT_2026-10-22.md section 6 records section 2.5.4 as RESOLVED. The tracked copy data/frozen_model_manifest.json (byte-identical) and the 2026-10-07 recompute manifest (SHA-256 2614f042..., differs only in created_at_utc and prospective_holdout_after) are labelled LEGACY and DERIVED via adjacent notes and are read by nothing in src/. Production code, the live path and forecast output are unchanged; nothing was deleted. Commits dedc74a (docs), 5910051 (labels), 95cca61 (guard test). Tests: 5 new, 269 total passing.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-23T15:31:41+00:00",
  "status": "observing",
  "summary": "Frozen-manifest dual-source resolution landed. The live path data/interim/reports/rolling_round_simulation_validation/frozen_model_manifest.json (SHA-256 8ee96b9f..., hard-coded at pipelines/weekly_forecast.py WeeklyPaths.manifest) is now the documented single source of truth: docs/INTEGRITY_AUDIT_2026-10-22.md section 6 records section 2.5.4 as RESOLVED. The tracked copy data/frozen_model_manifest.json (byte-identical) and the 2026-10-07 recompute manifest (SHA-256 2614f042..., differs only in created_at_utc and prospective_holdout_after) are labelled LEGACY and DERIVED via adjacent notes and are read by nothing in src/. Production code, the live path and forecast output are unchanged; nothing was deleted. Commits dedc74a (docs), 5910051 (labels), 95cca61 (guard test). Tests: 5 new, 269 total passing.",
  "watching_for": "Any module or doc that starts naming data/frozen_model_manifest.json or the rolling_recompute_20261007 manifest as truth, and any drift between the live manifest and the labelled LEGACY copy.",
  "next_action": "On refreeze, update the live manifest, the LEGACY note sha256 and audit section 6 in one commit.",
  "deployed": false,
  "git_commit": "95cca61",
  "check_back": {
    "kind": "grade_event",
    "label": "frozen-manifest resolution shipped",
    "baseline": "2026-10-23T15:31:41+00:00",
    "events": [],
    "target_date": null
  },
  "docs": [
    {
      "label": "Integrity audit (section 6)",
      "path": "docs/INTEGRITY_AUDIT_2026-10-22.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Frozen manifest guard test",
      "path": "tests/test_frozen_manifest_source_of_truth.py"
    },
    {
      "label": "Legacy copy label",
      "path": "data/frozen_model_manifest.LEGACY.md"
    }
  ]
}
```

### Entry 16 — 2026-10-13T14:35:57+00:00

Built fail-open ESPN withdrawal pipeline for golf: free ESPN leaderboard WD/DQ detection plus filtering of PGA TOUR collector entry_status=withdrawn rows (collected but never filtered before). Wired into weekly_forecast._run_forecast before the frozen simulation; removals logged and in run status. Live-verified fetch; 13 new tests pass; 251 existing tests pass. Committed 9c6bec3, pushed.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-13T14:35:57+00:00",
  "status": "observing",
  "summary": "Built fail-open ESPN withdrawal pipeline for golf: free ESPN leaderboard WD/DQ detection plus filtering of PGA TOUR collector entry_status=withdrawn rows (collected but never filtered before). Wired into weekly_forecast._run_forecast before the frozen simulation; removals logged and in run status. Live-verified fetch; 13 new tests pass; 251 existing tests pass. Committed 9c6bec3, pushed.",
  "experiment": null,
  "watching_for": null,
  "next_action": null,
  "deployed": false,
  "git_commit": "",
  "check_back": {
    "kind": "grade_event",
    "label": "ESPN withdrawal pipeline shipped",
    "target": null,
    "baseline": "2026-10-13T14:35:57+00:00",
    "events": [],
    "target_date": null,
    "monitoring": false
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 15 — 2026-10-13T01:04:56+00:00

Collection phase: fixes shipped, monitoring live impact. Will flag when recalibration or selection review needed.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-13T01:04:56+00:00",
  "status": "observing",
  "summary": "Collection phase: fixes shipped, monitoring live impact. Will flag when recalibration or selection review needed.",
  "experiment": null,
  "watching_for": null,
  "next_action": null,
  "deployed": false,
  "git_commit": "",
  "check_back": {
    "kind": "grade_event",
    "label": "after a week of games",
    "target": null,
    "baseline": "2026-10-13T01:04:56+00:00",
    "events": [],
    "target_date": null,
    "monitoring": false
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 14 — 2026-10-13T00:48:42+00:00

Selection-layer audit complete: rank gates validated (log_rank coef -0.2 to -0.4, adds signal beyond model_prob). Calibration-map approach tested on temporal holdout, NO-GO (Brier worse, overfit). No backwards gates or toxic cohorts found. Selection layer sound.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-13T00:48:42+00:00",
  "status": "observing",
  "summary": "Selection-layer audit complete: rank gates validated (log_rank coef -0.2 to -0.4, adds signal beyond model_prob). Calibration-map approach tested on temporal holdout, NO-GO (Brier worse, overfit). No backwards gates or toxic cohorts found. Selection layer sound.",
  "experiment": null,
  "watching_for": null,
  "next_action": null,
  "deployed": false,
  "git_commit": "",
  "check_back": {
    "kind": "grade_event",
    "label": "after a week of games",
    "target": null,
    "baseline": "2026-10-13T00:48:42+00:00",
    "events": [],
    "target_date": null,
    "monitoring": false
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 13 — 2026-10-12T16:30:21+00:00

Archive manifest hash fixed; Baycurrent Classic grading completed successfully. Pipeline healthy.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-12T16:30:21+00:00",
  "status": "observing",
  "summary": "Archive manifest hash fixed; Baycurrent Classic grading completed successfully. Pipeline healthy.",
  "experiment": null,
  "watching_for": null,
  "next_action": null,
  "deployed": false,
  "git_commit": "",
  "check_back": {
    "kind": "grade_event",
    "label": "Baycurrent grading complete",
    "target": null,
    "baseline": "2026-10-12T16:30:21+00:00",
    "events": [],
    "target_date": null
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 12 — 2026-10-11T03:59:06+00:00

Bot now stays completely silent when tournament in progress. Fixed Baycurrent end date to 2026-10-11. 251 tests pass.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-11T03:59:06+00:00",
  "status": "observing",
  "summary": "Bot now stays completely silent when tournament in progress. Fixed Baycurrent end date to 2026-10-11. 251 tests pass.",
  "experiment": null,
  "watching_for": null,
  "next_action": null,
  "deployed": false,
  "git_commit": "",
  "check_back": {
    "kind": "grade_event",
    "label": "mid-tournament silence fix",
    "target": null,
    "baseline": "2026-10-11T03:59:06+00:00",
    "events": [],
    "target_date": null
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 11 — 2026-10-11T02:43:47+00:00

send_ops_alert() now suppresses identical alert text within 24h (ledger data/interim/weekly/ops_alerts.json). Stops 2-hourly Discord spam from grading/discovery retries. 251 tests pass. Commit 76ef7bf pushed.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-11T02:43:47+00:00",
  "status": "observing",
  "summary": "send_ops_alert() now suppresses identical alert text within 24h (ledger data/interim/weekly/ops_alerts.json). Stops 2-hourly Discord spam from grading/discovery retries. 251 tests pass. Commit 76ef7bf pushed.",
  "experiment": null,
  "watching_for": null,
  "next_action": null,
  "deployed": false,
  "git_commit": "",
  "check_back": {
    "kind": "grade_event",
    "label": "Golf ops alerts deduped (24h)",
    "target": null,
    "baseline": "2026-10-11T02:43:47+00:00",
    "events": [],
    "target_date": null
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 10 — 2026-10-11T01:15:10+00:00

Baycurrent 3* raw ValueError fixed: grade only final leaderboards, clean Discord retry lines, scrub raw exceptions belt-and-braces. 246 tests pass. Commits 4dd9274+89932ed pushed.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-11T01:15:10+00:00",
  "status": "observing",
  "summary": "Baycurrent 3* raw ValueError fixed: grade only final leaderboards, clean Discord retry lines, scrub raw exceptions belt-and-braces. 246 tests pass. Commits 4dd9274+89932ed pushed.",
  "experiment": null,
  "watching_for": null,
  "next_action": null,
  "deployed": false,
  "git_commit": "",
  "check_back": {
    "kind": "grade_event",
    "label": "raw ValueError fix",
    "target": null,
    "baseline": "2026-10-11T01:15:10+00:00",
    "events": [],
    "target_date": null
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 9 — 2026-10-07T12:03:11+00:00

Fixed sports-golf-forecast.service 203-EXEC failure: run_linux_task.sh was committed without the execute bit. Restored +x in working tree and git, commit 435873a, pushed, service restarted and now executing normally.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-07T12:03:11+00:00",
  "status": "observing",
  "summary": "Fixed sports-golf-forecast.service 203-EXEC failure: run_linux_task.sh was committed without the execute bit. Restored +x in working tree and git, commit 435873a, pushed, service restarted and now executing normally.",
  "experiment": null,
  "watching_for": null,
  "next_action": null,
  "deployed": false,
  "git_commit": "",
  "check_back": {
    "kind": "grade_event",
    "label": "post-event forecast grading",
    "target": null,
    "baseline": "2026-10-07T12:03:11+00:00",
    "events": [],
    "target_date": null
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ],
  "run_recoveries": [
    {
      "service": "sports-golf-forecast.service",
      "fix_deployed_at": "2026-10-07T12:02Z",
      "summary": "Restored execute bit on run_linux_task.sh, committed 435873a and pushed, service verified running."
    }
  ]
}
```

### Entry 8 — 2026-10-07T04:36:34+00:00

Weekly-loop grading safeguard shipped (19386e0): post_event_grading auto-grades ended archived forecasts on the 2-hourly loop, adopts the manual Bank of Utah grade, raises [URGENT] blocked + Discord alert on grading failure; 241 tests pass.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-07T04:36:34+00:00",
  "status": "observing",
  "summary": "Weekly-loop grading safeguard shipped (19386e0): post_event_grading auto-grades ended archived forecasts on the 2-hourly loop, adopts the manual Bank of Utah grade, raises [URGENT] blocked + Discord alert on grading failure; 241 tests pass.",
  "experiment": null,
  "watching_for": "Next tournament end triggers first automatic grading attempt; no silent misses.",
  "next_action": "None; safeguard runs automatically in the weekly loop.",
  "deployed": true,
  "git_commit": "19386e0",
  "check_back": {
    "kind": "grade_event",
    "label": "post-event forecast grading",
    "target": null,
    "baseline": "2026-10-07T04:36:34+00:00",
    "events": [],
    "target_date": null
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 7 — 2026-10-07T04:18:16+00:00

Hojgaard fix: transliteration fold (o->o, ae->ae, l->l, etc) in _canonical_name_key; Bank of Utah re-grade 108 players (was 107), Hojgaard matched; full suite 232 passed.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-07T04:18:16+00:00",
  "status": "observing",
  "summary": "Hojgaard fix: transliteration fold (o->o, ae->ae, l->l, etc) in _canonical_name_key; Bank of Utah re-grade 108 players (was 107), Hojgaard matched; full suite 232 passed.",
  "experiment": null,
  "watching_for": null,
  "next_action": null,
  "deployed": false,
  "git_commit": "",
  "check_back": {
    "kind": "grade_event",
    "label": "after a week of games",
    "target": null,
    "baseline": "2026-10-07T04:18:16+00:00",
    "events": [],
    "target_date": null
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 6 — 2026-10-07T03:56:02+00:00

Bank of Utah Championship graded (7eef471): integrated canonical-name grader upgrade (intersection grading, 9 real aliases resolved); 107 of 115 forecast players graded, Brier top20 0.1453 (+0.0009 vs structural baseline). Actual winner Austin Smotherman vs forecast favorite Maverick McNealy. Frozen 365/8/20 unchanged; 231 tests pass.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-07T03:56:02+00:00",
  "status": "observing",
  "summary": "Bank of Utah Championship graded (7eef471): integrated canonical-name grader upgrade (intersection grading, 9 real aliases resolved); 107 of 115 forecast players graded, Brier top20 0.1453 (+0.0009 vs structural baseline). Actual winner Austin Smotherman vs forecast favorite Maverick McNealy. Frozen 365/8/20 unchanged; 231 tests pass.",
  "experiment": "Frozen 365/8/20 incumbent; no retuning. One 107-player graded event is too small for calibration conclusions -- accumulate more genuinely prospective events.",
  "watching_for": "Next genuinely prospective event grade (Baycurrent Classic Oct 8 awaiting official field); known grader gap: o-slash transliteration (Rasmus Hojgaard) unmatched, 107 graded instead of 108.",
  "next_action": "Decide on o-slash transliteration fix for forecast_grading.py; let the scheduler advance Baycurrent Classic when official field evidence appears.",
  "deployed": true,
  "git_commit": "7eef4715cf025f7fa949ca23b7a1a891ffeab8d4",
  "check_back": {
    "kind": "grade_event",
    "label": "After Baycurrent Classic is graded",
    "target": null,
    "baseline": "2026-10-07T03:56:02+00:00",
    "events": []
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 5 — 2026-10-05T12:03:49+00:00

Oct 5 check-in (report only): verified the Oct 1 bovada 203/EXEC failure is stale — launcher permissions were corrected Oct 2 (230 tests pass) and the timer is armed for Mon Oct 5 08:56 ET, which is the post-fix verification run. No collection gap beyond the single Oct 1 miss (Mon/Wed/Thu schedule; backfill not feasible or needed). Bank of Utah grade_event check-back still open: preserve CBS leaderboard and run grade-forecast, no retune of 365/8/20.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-05T12:03:49+00:00",
  "status": "observing",
  "summary": "Oct 5 check-in (report only): verified the Oct 1 bovada 203/EXEC failure is stale — launcher permissions were corrected Oct 2 (230 tests pass) and the timer is armed for Mon Oct 5 08:56 ET, which is the post-fix verification run. No collection gap beyond the single Oct 1 miss (Mon/Wed/Thu schedule; backfill not feasible or needed). Bank of Utah grade_event check-back still open: preserve CBS leaderboard and run grade-forecast, no retune of 365/8/20.",
  "experiment": "Frozen 365/8/20 incumbent; no retuning. Verify the launcher fix by the next scheduled Bovada collection.",
  "watching_for": "Monday Oct 5 8:56am ET Bovada collection succeeds on the fixed launcher; Bank of Utah grade preserved without retuning.",
  "next_action": "After Bank of Utah finishes, preserve the CBS leaderboard and run grade-forecast; confirm the Monday Bovada run.",
  "deployed": true,
  "git_commit": "",
  "check_back": {
    "kind": "grade_event",
    "label": "After Bank of Utah Championship is graded",
    "target": null,
    "baseline": "2026-09-26T04:07:22+00:00",
    "events": [],
    "target_date": "2026-10-04"
  },
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 4 — 2026-10-02T13:39:16+00:00

Corrected task-launcher executable permissions

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-02T13:39:16+00:00",
  "status": "observing",
  "summary": "Corrected task-launcher executable permissions",
  "experiment": "Frozen 365/8/20 incumbent; no retuning. Verify the launcher fix by the next scheduled Bovada collection.",
  "watching_for": "Monday Oct 5 8:56am ET Bovada collection succeeds on the fixed launcher; Bank of Utah grade preserved without retuning.",
  "next_action": "After Bank of Utah finishes, preserve the CBS leaderboard and run grade-forecast; confirm the Monday Bovada run.",
  "deployed": true,
  "git_commit": null,
  "check_back": {
    "kind": "grade_event",
    "label": "After Bank of Utah Championship is graded",
    "target": null,
    "baseline": "2026-09-26T04:07:22+00:00",
    "events": [],
    "target_date": "2026-10-04"
  },
  "run_recoveries": [
    {
      "service": "sports-golf-bovada.service",
      "fix_deployed_at": "2026-10-02T00:32:03+00:00",
      "summary": "Corrected task-launcher executable permissions"
    }
  ],
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 3 — 2026-10-02T02:22:31+00:00

Fixed and deployed the Azure task-launcher permission defect. The next scheduled forecast run succeeded and advanced safely to Baycurrent Classic (awaiting official field); Bank of Utah remains archived and awaits grading after the event.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-02T02:22:31+00:00",
  "status": "observing",
  "summary": "Fixed and deployed the Azure task-launcher permission defect. The next scheduled forecast run succeeded and advanced safely to Baycurrent Classic (awaiting official field); Bank of Utah remains archived and awaits grading after the event.",
  "experiment": "Frozen 365/8/20 incumbent; no retuning. Launcher is tracked as executable, installer enforces mode 0755, regression test added; 230 tests pass. Azure forecast timer succeeded; Bovada's next scheduled collection is Monday and awaits its post-fix run.",
  "watching_for": "Preserved final CBS leaderboard and grade for Bank of Utah top-20/top-10/top-5/winner and make-cut; verify grade without retuning. Confirm Monday Bovada collection succeeds. Baycurrent Classic (Oct 8) should remain awaiting official field evidence until the scheduled loop advances it.",
  "next_action": "After Bank of Utah finishes, preserve the CBS leaderboard under data/raw/prospective_results/bank_of_utah_championship_2026/ and run grade-forecast; assess the two-event prospective record without retuning. Let the scheduler handle Baycurrent; check the Monday Bovada run.",
  "deployed": true,
  "git_commit": null,
  "check_back": {
    "kind": "grade_event",
    "label": "After Bank of Utah Championship is graded",
    "target": null,
    "baseline": "2026-09-26T04:07:22+00:00",
    "events": [],
    "target_date": "2026-10-04"
  },
  "run_recoveries": [],
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 2 — 2026-10-01T03:43:56+00:00

Bank of Utah Championship 2026 frozen forecast archived pre-start and verified; forecast-only Discord board sent. Deployed fixes for PGA TOUR Last, First identity matching and the tee-time fallback deadlock; 113 of 115 players resolved to canonical history.

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-10-01T03:43:56+00:00",
  "status": "observing",
  "summary": "Bank of Utah Championship 2026 frozen forecast archived pre-start and verified; forecast-only Discord board sent. Deployed fixes for PGA TOUR Last, First identity matching and the tee-time fallback deadlock; 113 of 115 players resolved to canonical history.",
  "experiment": "Frozen 365/8/20 incumbent; no retuning. Second prospective event forecast uses 20,000 simulations and ordinary top-65 cut.",
  "watching_for": "Preserved CBS final leaderboard and prospective grade for top-20/top-10/top-5/winner and make-cut; verify archive and identity audit, then compare Brier scores without treating one event as edge evidence.",
  "next_action": "After play completes, preserve the CBS leaderboard under data/raw/prospective_results/bank_of_utah_championship_2026/ and run grade-forecast; then assess the two-event prospective record without retuning.",
  "deployed": true,
  "git_commit": "c3bc4f0a2975b234bc22b940e84b73bc699c8211",
  "check_back": {
    "kind": "grade_event",
    "label": "After Bank of Utah Championship is graded",
    "target": null,
    "baseline": "2026-09-26T04:07:22+00:00",
    "events": [],
    "target_date": "2026-10-04"
  },
  "run_recoveries": [],
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

### Entry 1 — 2026-09-26T04:07:22+00:00

Forecast-only Discord publisher deployed on Azure; weekly loop waiting quietly for a valid pre-start forecast for Biltmore (weekly-forecast-status = awaiting_field). [bootstrapped 2026-09-26 from docs/NEXT_CHECKIN.md]

```json
{
  "schema_version": 1,
  "project_id": "golf_props",
  "updated_at": "2026-09-26T04:07:22+00:00",
  "status": "observing",
  "summary": "Forecast-only Discord publisher deployed on Azure; weekly loop waiting quietly for a valid pre-start forecast for Biltmore (weekly-forecast-status = awaiting_field). [bootstrapped 2026-09-26 from docs/NEXT_CHECKIN.md]",
  "experiment": "Frozen 365/8/20 incumbent; one graded event beat structural baseline but lost to historical rolling aggregates - no retune.",
  "watching_for": "weekly-forecast-status still awaiting_field; a valid pre-start forecast archived and the forecast-only board auto-published.",
  "next_action": "Preserve official final field/tee-time evidence for Biltmore if the pre-start window is available; otherwise wait for the next eligible event, then preserve the CBS leaderboard and run grade-forecast.",
  "deployed": true,
  "git_commit": null,
  "check_back": {
    "kind": "calendar",
    "label": "weekly event watch",
    "target": 7,
    "baseline": "2026-09-26T04:07:22+00:00",
    "events": [],
    "target_date": null
  },
  "run_recoveries": [],
  "docs": [
    {
      "label": "Next check-in",
      "path": "docs/NEXT_CHECKIN.md"
    },
    {
      "label": "Project handoff",
      "path": "docs/project_handoff.md"
    },
    {
      "label": "Azure deployment",
      "path": "docs/azure_deployment.md"
    }
  ]
}
```

## Earlier Mac diary source

These entries are preserved separately without replacing any Azure history.

```json
[
  {
    "schema_version": 1,
    "project_id": "golf_props",
    "updated_at": "2026-09-26T00:07:22-04:00",
    "status": "observing",
    "summary": "Forecast-only Discord publisher deployed on Azure; weekly loop waiting quietly for a valid pre-start forecast for Biltmore (weekly-forecast-status = awaiting_field). [bootstrapped 2026-09-26 from docs/NEXT_CHECKIN.md]",
    "experiment": "Frozen 365/8/20 incumbent; one graded event beat structural baseline but lost to historical rolling aggregates - no retune.",
    "watching_for": "weekly-forecast-status still awaiting_field; a valid pre-start forecast archived and the forecast-only board auto-published.",
    "next_action": "Preserve official final field/tee-time evidence for Biltmore if the pre-start window is available; otherwise wait for the next eligible event, then preserve the CBS leaderboard and run grade-forecast.",
    "deployed": true,
    "git_commit": "",
    "check_back": {
      "kind": "calendar",
      "target": 7,
      "label": "weekly event watch",
      "baseline": "2026-09-26T00:07:22-04:00"
    },
    "docs": [
      {
        "label": "Next check-in",
        "path": "docs/NEXT_CHECKIN.md"
      },
      {
        "label": "Project handoff",
        "path": "docs/project_handoff.md"
      },
      {
        "label": "Azure deployment",
        "path": "docs/azure_deployment.md"
      }
    ]
  },
  {
    "schema_version": 1,
    "project_id": "golf_props",
    "updated_at": "2026-09-30T23:43:56-04:00",
    "status": "observing",
    "summary": "Bank of Utah Championship 2026 frozen forecast archived pre-start and verified; forecast-only Discord board sent. Deployed fixes for PGA TOUR Last, First identity matching and the tee-time fallback deadlock; 113 of 115 players resolved to canonical history.",
    "experiment": "Frozen 365/8/20 incumbent; no retuning. Second prospective event forecast uses 20,000 simulations and ordinary top-65 cut.",
    "watching_for": "Preserved CBS final leaderboard and prospective grade for top-20/top-10/top-5/winner and make-cut; verify archive and identity audit, then compare Brier scores without treating one event as edge evidence.",
    "next_action": "After play completes, preserve the CBS leaderboard under data/raw/prospective_results/bank_of_utah_championship_2026/ and run grade-forecast; then assess the two-event prospective record without retuning.",
    "deployed": true,
    "git_commit": "c3bc4f0a2975b234bc22b940e84b73bc699c8211",
    "check_back": {
      "kind": "grade_event",
      "label": "After Bank of Utah Championship is graded",
      "target": null,
      "baseline": "2026-09-26T00:07:22-04:00",
      "events": [],
      "target_date": "2026-10-04"
    },
    "docs": [
      {
        "label": "Next check-in",
        "path": "docs/NEXT_CHECKIN.md"
      },
      {
        "label": "Project handoff",
        "path": "docs/project_handoff.md"
      },
      {
        "label": "Azure deployment",
        "path": "docs/azure_deployment.md"
      }
    ]
  },
  {
    "schema_version": 1,
    "project_id": "golf_props",
    "updated_at": "2026-10-01T22:22:31-04:00",
    "status": "observing",
    "summary": "Fixed and deployed the Azure task-launcher permission defect. The next scheduled forecast run succeeded and advanced safely to Baycurrent Classic (awaiting official field); Bank of Utah remains archived and awaits grading after the event.",
    "experiment": "Frozen 365/8/20 incumbent; no retuning. Launcher is tracked as executable, installer enforces mode 0755, regression test added; 230 tests pass. Azure forecast timer succeeded; Bovada's next scheduled collection is Monday and awaits its post-fix run.",
    "watching_for": "Preserved final CBS leaderboard and grade for Bank of Utah top-20/top-10/top-5/winner and make-cut; verify grade without retuning. Confirm Monday Bovada collection succeeds. Baycurrent Classic (Oct 8) should remain awaiting official field evidence until the scheduled loop advances it.",
    "next_action": "After Bank of Utah finishes, preserve the CBS leaderboard under data/raw/prospective_results/bank_of_utah_championship_2026/ and run grade-forecast; assess the two-event prospective record without retuning. Let the scheduler handle Baycurrent; check the Monday Bovada run.",
    "deployed": true,
    "git_commit": "",
    "check_back": {
      "kind": "grade_event",
      "label": "After Bank of Utah Championship is graded",
      "target": null,
      "baseline": "2026-09-26T00:07:22-04:00",
      "events": [],
      "target_date": "2026-10-04"
    },
    "docs": [
      {
        "label": "Next check-in",
        "path": "docs/NEXT_CHECKIN.md"
      },
      {
        "label": "Project handoff",
        "path": "docs/project_handoff.md"
      },
      {
        "label": "Azure deployment",
        "path": "docs/azure_deployment.md"
      }
    ]
  },
  {
    "schema_version": 1,
    "project_id": "golf_props",
    "updated_at": "2026-10-02T09:39:16-04:00",
    "status": "observing",
    "summary": "Launcher permission fix is deployed; Bovada's last attempt (Oct 1 8:56am ET) predates it and is awaiting the next scheduled collection to verify. The forecast timer has run successfully on the fixed launcher several times since. Bank of Utah remains archived and awaiting grading after the event.",
    "experiment": "Frozen 365/8/20 incumbent; no retuning. Verify the launcher fix by the next scheduled Bovada collection.",
    "watching_for": "Monday Oct 5 8:56am ET Bovada collection succeeds on the fixed launcher; Bank of Utah grade preserved without retuning.",
    "next_action": "After Bank of Utah finishes, preserve the CBS leaderboard and run grade-forecast; confirm the Monday Bovada run.",
    "deployed": true,
    "git_commit": "",
    "check_back": {
      "kind": "grade_event",
      "label": "After Bank of Utah Championship is graded",
      "target": null,
      "baseline": "2026-09-26T00:07:22-04:00",
      "events": [],
      "target_date": "2026-10-04"
    },
    "docs": [
      {
        "label": "Next check-in",
        "path": "docs/NEXT_CHECKIN.md"
      },
      {
        "label": "Project handoff",
        "path": "docs/project_handoff.md"
      },
      {
        "label": "Azure deployment",
        "path": "docs/azure_deployment.md"
      }
    ],
    "run_recoveries": [
      {
        "service": "sports-golf-bovada.service",
        "fix_deployed_at": "2026-10-02T00:32:03+00:00",
        "summary": "Corrected task-launcher executable permissions"
      }
    ]
  }
]
```
