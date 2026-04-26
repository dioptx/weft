# Hook patch: allow fork→non-dioptx upstream PRs

The current `~/.claude/hooks/github-security.sh` blocks all `push|pr-create|workflow-run` operations against `dioptx/*` public repos (lines 167-172). This catches forks created under `dioptx/` for the purpose of opening contribution PRs upstream.

The patch below adds a narrow exception: **only when an `upstream` remote is set AND points outside the `dioptx/` namespace**, allow `push` and `pr-create`. All other operations (force-push, pr-merge, workflow-run) on dioptx public repos remain blocked.

## Apply manually

The harness blocks Claude from self-modifying its own security hook (sensible default). Apply this yourself:

```diff
--- a/.claude/hooks/github-security.sh
+++ b/.claude/hooks/github-security.sh
@@ -164,6 +164,17 @@
 case "$REPO_OWNER" in
     "dioptx")
         if [ "$IS_PRIVATE" = "false" ]; then
+            # Fork→upstream contribution exception: allow push/pr-create when the
+            # current repo is a fork (has an `upstream` remote pointing outside dioptx/).
+            # This does NOT weaken protection on dioptx-owned public repos themselves —
+            # those have no upstream remote.
+            UPSTREAM_URL=$(git remote get-url upstream 2>/dev/null || echo "")
+            UPSTREAM_OWNER=""
+            if [[ "$UPSTREAM_URL" =~ github\.com[:/]([^/]+)/([^/.]+) ]]; then
+                UPSTREAM_OWNER="${BASH_REMATCH[1]}"
+            fi
+            if [[ -n "$UPSTREAM_OWNER" && "$UPSTREAM_OWNER" != "dioptx" && "$OPERATION" =~ ^(push|pr-create)$ ]]; then
+                log_decision "ALLOW" "$OPERATION" "$FULL_REPO" "fork→upstream ($UPSTREAM_OWNER) contribution"
+                exit 0
+            fi
             if [[ "$OPERATION" =~ ^(push|force-push|pr-create|pr-merge|workflow-run)$ ]]; then
                 log_decision "DENY" "$OPERATION" "$FULL_REPO" "public repo blocked"
                 deny "Blocked: dioptx public repos are read-only. Operation: $OPERATION"
```

## Properties

- **Scope**: only `push` + `pr-create`. Force-push, pr-merge, workflow-run still blocked.
- **Trigger**: requires an `upstream` remote pointing to a non-`dioptx/` repo. Real dioptx-owned public repos have no upstream → unaffected.
- **Audit**: every allowance logs `fork→upstream (<owner>) contribution` to `~/.claude/logs/security-audit.log`.

## Test after applying

```bash
# Should ALLOW (fork → upstream PR)
cd /tmp/awesome-claude-code
git push origin add-weft   # should succeed (already pushed; no-op)
gh pr create --fill        # should succeed

# Should still DENY (direct mutation of dioptx public repo)
cd ~/projects/weft
git push --force origin main  # should still be blocked by force-push global block
```
