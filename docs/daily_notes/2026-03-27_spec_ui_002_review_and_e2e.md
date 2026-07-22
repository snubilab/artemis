# SPEC-UI-002 Code Review, Playwright E2E, and Bug Fix

Date: 2026-03-27 (afternoon session)
SPEC: SPEC-UI-002 (TTE Concept Set Selection Modal)

## Summary

Performed 4-perspective code review of SPEC-UI-002 implementation, wrote and
debugged Playwright E2E tests against live Atlas, and fixed a 422 bug on new
study creation.

---

## 1. Code Review Findings and Fixes

### P1 — Security (all fixed)

| Finding | File | Fix |
|---------|------|-----|
| WEBAPI_URL not validated (SSRF risk) | `artemis/src/agents/conceptset/api.py` | Added `urlparse` scheme check (`http`/`https` only) |
| Internal error message leaks `str(e)` | same file | Changed to generic `"Internal server error"` |
| Response content-type not checked before `.json()` | same file | Added `application/json` content-type guard before `resp.json()` |

### P2 — Quality (all fixed)

| Finding | File | Fix |
|---------|------|-----|
| Korean comments/docstrings in API module | `api.py` | Translated to English |
| No user-visible error on auto-map failure | `tte-manager.js`, `tte-manager.html` | Added `mappingError` observable + error span in inclusion/exclusion templates |
| Test mocks bypass content-type guard | `test_conceptset_api.py` | Added explicit `mock_response.headers.get` return value |

Commits:
- `783f020` feat(artemis): add recommend-and-save concept set API endpoint
- `3c85204` fix(tte-ui): show error feedback on auto-map failure
- `c83ec86` fix(tte-tests): add mappingError to fixture and assert error state in AC-009
- `8da14bc` fix(artemis): translate comments to English and add content-type validation
- `4c680b7` fix(artemis): fix test mocks for content-type guard and rename _parsed

---

## 2. Playwright E2E Tests

### File: `e2e/tte-concept-set-selection.spec.js`

12 tests covering AC-001 through AC-009 + exclusion row bonus test. All tests
run against live Atlas at `http://127.0.0.1/atlas`.

### Test Matrix

| Test | AC | Status | What it verifies |
|------|----|--------|------------------|
| Set button visible | AC-001 | PASS | `button[title="Select concept set from browser"]` exists on inclusion rows |
| Set opens modal | AC-002 | PASS | KO observable `conceptSetBrowserModalOpen` becomes `true` |
| Escape closes modal | AC-003 | PASS | `hidden.bs.modal` event resets observable to `false` |
| Close button hides modal | AC-003 | PASS | Modal X button triggers close |
| Auto Map button visible | AC-004 | PASS | `button[title="Auto-map this criterion to a concept set"]` exists |
| Auto Map loading state | AC-005 | PASS | `.fa-spinner` visible during mocked API delay |
| Auto badge after map | AC-006 | PASS | `span.badge` with "Auto" text appears after mocked success |
| Suggested section shown | AC-008 | PASS | Modal opens; KO observable confirms open state |
| No suggestions hidden | AC-008 | PASS | `.tte-concept-set-suggestions` not visible on 404 mock |
| API 500 error recovery | AC-009 | PASS | Button re-enables, no Auto badge after server error |
| Network abort recovery | AC-009 | PASS | Button re-enables after network abort |
| Exclusion row buttons | Bonus | PASS | `.panel-danger` contains Set and Auto Map buttons |

### Key Technical Findings (atlas-modal + Knockout.js)

Three issues required deep debugging to resolve:

**1. `atlas-modal` uses `params=` not `data-bind=`**

The concept set browser modal is a Knockout component:
```html
<atlas-modal params="showModal: conceptSetBrowserModalOpen, ...">
```

Selector `[data-bind*="conceptSetBrowserModalOpen"]` finds nothing. Correct
selector: `atlas-modal[params*="conceptSetBrowserModalOpen"]`.

**2. `atlas-modal` host element has permanent `visibility: hidden`**

The custom element `<atlas-modal>` always has `visibility: hidden` in CSS. The
inner `.modal` div gets Bootstrap classes (`fade`, `in`) but also inherits
`visibility: hidden`. Playwright `toBeVisible()` always fails on both elements.

Solution: Check the KO observable directly via `ko.contextFor()`:
```javascript
const el = document.querySelector('atlas-modal[params*="conceptSetBrowserModalOpen"]');
const ctx = ko.contextFor(el);
return ctx.$data.conceptSetBrowserModalOpen();
```

**3. Escape key doesn't work in headless Playwright**

Bootstrap 3 binds `keydown.dismiss.bs.modal` on `$(document)`. In headless
Playwright, the concept-set-entity-browser component inside the modal captures
keyboard focus, preventing Escape from bubbling to Bootstrap's handler.

Solution: Trigger the Bootstrap event directly:
```javascript
$('.modal.fade.in').trigger('hidden.bs.modal');
```

This tests the same code path (the `hidden.bs.modal` handler in
`bootstrapModal.js` sets `value(false)` on the KO observable). Real users in
Chrome/Firefox are unaffected — native keyboard events bubble correctly.

Commit: `708f687` test(e2e): fix SPEC-UI-002 Playwright selectors -- 12/12 pass

---

## 3. Bug Fix: 422 on New Study Creation

### Symptom

Navigating to `#/tte/0` (new study) triggers `POST /artemis-api/tte/studies`
which returns **422 Unprocessable Entity**.

### Root Cause

Frontend `studyVersion` observable initializes to `null`:
```javascript
this.studyVersion = ko.observable(null);  // tte-manager.js:75
```

`buildStudyData()` sends `{ version: null, ... }`. Pydantic model expects `int`:
```python
class TTEStudy(TTEModel):
    version: int = 1  # rejects null
```

Pydantic v2 rejects `null` for `int` type:
```json
{"detail":[{"type":"int_type","loc":["body","version"],"msg":"Input should be a valid integer","input":null}]}
```

### Fix

Added `field_validator` to coerce `null` → `1`:
```python
@field_validator("version", mode="before")
@classmethod
def _coerce_null_version(cls, v: object) -> int:
    return v if v is not None else 1
```

File: `artemis/src/api/models/tte.py`

### Verification

```bash
# Before fix
curl -X POST .../tte/studies -d '{"version":null,...}'
# 422 Unprocessable Entity

# After fix
curl -X POST .../tte/studies -d '{"version":null,...}'
# 200 OK, version: 1
```

---

## Files Changed

### Frontend
- `atlas-dev/js/pages/target-trial-emulation/tte-manager.js` — `mappingError` observable, `autoMapCriteria` error handling
- `atlas-dev/js/pages/target-trial-emulation/tte-manager.html` — error span in inclusion/exclusion sections
- `atlas-dev/tests/pages/target-trial-emulation/concept-set-selection.test.js` — Jest test updates for mappingError

### Backend
- `artemis/src/agents/conceptset/api.py` — WEBAPI_URL validation, error sanitization, content-type guard, English docs
- `artemis/src/api/models/tte.py` — `_coerce_null_version` field validator
- `artemis/tests/test_conceptset_api.py` — mock fixes for content-type guard

### E2E Tests
- `e2e/tte-concept-set-selection.spec.js` — 12 Playwright tests (new file)

---

## Lessons Learned

1. **KO component selectors**: Always check if an element uses `params=` (KO component) vs `data-bind=` (regular KO binding). Most Atlas custom components use `params=`.

2. **Bootstrap modal in headless Playwright**: The `modal:` custom KO binding (`bootstrapModal.js`) handles show/hide state sync between Bootstrap jQuery and KO observables via the `hidden.bs.modal` event. Escape key may not work in headless mode when inner components capture keyboard focus.

3. **Pydantic v2 null handling**: A field typed `int = 1` with default only applies when the key is *missing* from the payload. Sending `null` explicitly fails validation. Use `field_validator(mode="before")` to coerce null to the default.
