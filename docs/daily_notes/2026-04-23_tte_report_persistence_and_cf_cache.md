# 2026-04-23 TTE Report Persistence Bug + CloudFlare Edge Cache Fix

## Summary

1. **UI bug**: Generated TTE report disappears after page reload, forcing user to regenerate.
2. **Infra bug**: Edits to `atlas-dev/*.js` not visible on browser refresh; required manual "Disable cache" in DevTools.

Both resolved. Report now persists across reload; JS edits reflect on normal F5.

## Bug 1: Report Disappears After Reload

### Symptom

User generates Report in TTE manager. Navigates away (or refreshes). Returns to the same study. Report tab shows "Generate Report" CTA instead of the previously-generated iframe. User assumes regeneration is needed.

### Root Cause

The Report tab in `atlas-dev/js/pages/target-trial-emulation/tte-manager.html` has three mutually-exclusive visibility states bound only to `reportPreviewVisible` (no dependency on `reportHtmlContent` or artifact state):

```html
<div visible="!hasResults()">...warning...</div>
<div visible="hasResults() && !reportPreviewVisible()">...Generate CTA...</div>
<div visible="reportPreviewVisible">...iframe...</div>
```

**Asymmetry between create path and load path:**
- `triggerReportSummary()` (line 4412): sets both `reportHtmlContent(html)` AND `reportPreviewVisible(true)`.
- `loadAnalysis()` (line 1911): sets only `reportHtmlContent(reportHtml)`, leaves `reportPreviewVisible` at default `false`.

Backend persistence works — `TTEStore.create_artifact` writes the report_summary artifact to `artemis/tmp/tte/studies.json` and `loadArtifacts()` correctly retrieves it. The artifact HTML is restored to the observable. Only the visibility flag is missed.

### Fix

`atlas-dev/js/pages/target-trial-emulation/tte-manager.js:1914`

```diff
  .then(() => {
      const reportArtifact = this.getLatestReportSummaryArtifact();
      const reportHtml = reportArtifact && reportArtifact.payload && reportArtifact.payload.reportHtml;
      if (reportHtml) {
          this.reportHtmlContent(reportHtml);
+         this.reportPreviewVisible(true);
      }
      this.loading(false);
      this.dirtyFlag(false);
  })
```

### Verification

1. Generate report on any study.
2. Navigate away, return → report iframe visible immediately.
3. Hard refresh → still visible.

### Why This Bug Existed

Knockout observables split into "data" (`reportHtmlContent`) and "UI state" (`reportPreviewVisible`). Create path sets both; load path only restored data. A less bug-prone design would use `ko.pureComputed(() => !!reportHtml)` for visibility, but `hideReportPreview()` needs to forcibly hide even when HTML is present, so the two observables are intentionally independent.

## Bug 2: CloudFlare Serving Stale JS

### Symptom

After editing `atlas-dev/js/pages/target-trial-emulation/tte-manager.js` on the host, browser refresh (even `Ctrl+Shift+R`) kept loading the old code. Only DevTools → Network → "Disable cache" unblocked it.

### Root Cause

Origin nginx headers were `Cache-Control: no-cache, must-revalidate`. CloudFlare (between traefik and browser) treats `no-cache` as "cache at edge but revalidate", and in practice may serve stale edge copies without hitting origin. `must-revalidate` did not force CF to re-fetch.

When "Disable cache" is enabled, the browser sends `Cache-Control: no-cache` on the request, which triggers CF to revalidate. Without that, CF used its cached copy.

### Fix — Hybrid Cache Policy

`atlas/config/nginx-default.conf` (new, replaces image default via volume mount):

```nginx
location ~* ^/atlas/js/pages/target-trial-emulation/ {
    add_header Cache-Control     "no-cache, must-revalidate" always;
    add_header CDN-Cache-Control "no-store"                  always;
    try_files $uri =404;
}
```

Rationale:
- `CDN-Cache-Control: no-store` — CloudFlare-specific directive, forces edge to never cache. Every request reaches origin.
- `Cache-Control: no-cache, must-revalidate` — browser still stores + uses ETag. Unchanged files return HTTP 304 (zero body transferred).

Mounted via `compose/ohdsi-atlas.yml`:

```yaml
volumes:
  - ../atlas/config/nginx-default.conf:/etc/nginx/conf.d/default.conf:ro
```

### Verification

```
$ curl -sI http://localhost/atlas/js/pages/target-trial-emulation/tte-manager.js | grep -iE "cache|etag"
Cache-Control: no-cache, must-revalidate
Cdn-Cache-Control: no-store
Etag: "69e9dda4-40ce1"

$ curl -sI -H 'If-None-Match: "69e9dda4-40ce1"' \
    http://localhost/atlas/js/pages/target-trial-emulation/tte-manager.js
HTTP/1.1 304 Not Modified
```

## Gotcha: Bind Mount Inode Trap

After changing `nginx-default.conf` content via Edit/Write (atomic replace → new inode), `docker compose up -d` may report "Container Running" without recreating. Nginx still sees old file content through the old bind-mount inode.

**Required action after editing a bind-mounted config file:**

```
docker restart ohdsi-atlas
```

Simply `nginx -s reload` inside the container does not help — reload re-reads the file, but the file the container can see is still the old inode version.

## Files Changed

| File | Change |
|------|--------|
| `atlas-dev/js/pages/target-trial-emulation/tte-manager.js:1914` | +1 line: `this.reportPreviewVisible(true);` |
| `atlas/config/nginx-default.conf` | new: hybrid cache policy |
| `compose/ohdsi-atlas.yml` | +1 volume mount for nginx-default.conf |
| `.claude/rules/broadsea/atlas-dev-cache.md` | new: cache policy rule for future agents |

## References

- Failure mode discovered because user reported "나갔다 들어오면 다시 생성해야해"
- Initial fix verified only after "Disable cache" was toggled — revealed the CF staleness issue
- `CDN-Cache-Control` is a CloudFlare-supported directive (also respected by Fastly, Cloudfront with extensions). See https://developers.cloudflare.com/cache/concepts/cache-control/
