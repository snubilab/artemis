# 2026-03-28: SPEC-UI-006 Eligibility Tab UX Overhaul

## Summary

Eligibility tab UX audit and 12 improvements implemented across P1/P2/P3 tiers.
Branch: `feat/spec-ui-006-eligibility-tab-ux-overhaul`

## Problem

The Eligibility tab had accumulated UX debt across SPEC-UI-001 through 005:
- Status banner consumed ~25% of viewport with no way to dismiss
- Builder Apply/Cancel scrolled out of view on long definitions
- 28+ criteria rows in flat list with no visual grouping or search
- 3 redundant eyebrow labels ("DEFINITION READY", "STRUCTURED RESULT WORKSPACE", "ATLAS COHORT EDITOR")
- "PRIMARY ACTION" label exposed internal UI meta to users
- Builder opened inline, pushing criteria out of view for comparison
- No WCAG AA compliance on eyebrow text contrast

## Changes

### P1 (Immediate UX wins)
1. **Removed "PRIMARY ACTION" label** — button visual emphasis is sufficient
2. **Sticky footer for Builder actions** — `.tte-eligibility-cohort-editor__sticky-foot` keeps Cancel/Apply visible at bottom of scrollable editor canvas

### P2 (Medium effort)
3. **Banner collapsible** — `eligibilityBannerCollapsed` observable + chevron toggle; collapsed state hides summary, support text, meta pills, secondary actions
4. **Criteria visual separation** — alternating row background (`:nth-child(even)`) + border-top separator between rows
5. **Structured Editor accent** — left border 4px solid #3498db + stronger gradient background
6. **Removed "Rows stay editable" pill** — set `meta: []` in `eligibilityMatrixBanner` computed (duplicate of criteria shell header text)
7. **Eyebrow consolidation** — removed "Structured Result Workspace" standalone eyebrow; "ATLAS Cohort Editor" converted to inline span next to "Structured Eligibility Editor"
8. **CTA button tooltips** — `title` attributes on Open Builder and Open Concept Sets buttons

### P3 (High effort)
9. **Builder side panel** — `editorPanelMode` observable auto-detects window >= 1200px; `.tte-structured-editor-shell--panel-mode` renders as fixed right panel (55% width, z-index 100) with close button
10. **Criteria search/filter** — `inclusionSearchTerm`/`exclusionSearchTerm` + `inclusionDomainFilter`/`exclusionDomainFilter` observables; `filteredInclusionCriteria`/`filteredExclusionCriteria` computed arrays; toolbar shown when count > 5
11. **Accessibility** — `role="region" aria-label="Cohort Definition Editor"` on editor shell; `aria-expanded` on banner toggle; eyebrow colors darkened #3f6a8f -> #2d5a7b for WCAG AA

### Bug fix
12. **Memory leak** — `window.addEventListener('resize', ...)` had no cleanup; added `this.subscriptions.push({ dispose: () => removeEventListener(...) })` following Atlas Component lifecycle pattern

## Files Modified

| File | Lines changed |
|------|--------------|
| `tte-manager.html` | +44 |
| `tte-manager.less` | +115 |
| `tte-manager.js` | +42 |
| `tte-eligibility-cohort-editor.html` | +11 |

## Review Results

- **Spec compliance**: 10/10 requirements verified by subagent
- **Code quality**: 1 Critical (memory leak — fixed), 3 Important (deferred: file size, filter perf, z-index strategy)

## Key Patterns Established

### Component lifecycle cleanup
```javascript
// Atlas Component.dispose() calls this.subscriptions[].dispose()
// For custom cleanup, push a duck-typed disposable:
this.subscriptions.push({
    dispose: () => window.removeEventListener('resize', this._handler)
});
```

### Criteria filtering pattern
```javascript
this.filteredInclusionCriteria = ko.pureComputed(() => {
    const term = (this.inclusionSearchTerm() || '').toLowerCase();
    const domain = this.inclusionDomainFilter();
    return this.inclusionCriteria().filter(c => {
        if (term && !(c.description() || '').toLowerCase().includes(term)) return false;
        if (domain && c.domain() !== domain) return false;
        return true;
    });
});
```

## Follow-up Items (separate PR)

- [ ] Debounce search input for large criteria lists (100+ items)
- [ ] Centralize z-index strategy in LESS variables
- [ ] Consider splitting tte-manager.js (~4400 lines) into feature modules
- [ ] Extract repeated gradient patterns into LESS mixins

## References

- Design spec: `docs/superpowers/specs/2026-03-28-eligibility-tab-ux-overhaul-design.md`
- Todolist: `todolist/20260328_180000_spec_ui_006_eligibility_ux.md`
- UX screenshot: `~/Desktop/SC/CleanShot 2026-03-28 at 17.58.59@2x.png`
