# Backlog: `test_binder.py` — Replace implementation-level tests with public-API tests

Status: **planned** | File: [`test/unit/test_binder.py`](test/unit/test_binder.py)

---

## 1. Replace 5 `_build_binder_url` private-method tests with `test_post_*`

**Problem:** Tests call `vre._build_binder_url(...)` — a private method — instead of the public `post()` contract. Two are redundant with existing `test_post_repository_only_*` tests.

### 1.1. Add `test_post_repository_only_github_with_branch`

- Fixture: `binder_vre_github_with_branch` (already exists in conftest)
- Call: `post()`
- Assert: returns `"https://mybinder.org/v2/gh/example/notebook-repo/main"`
- Replaces: `test_build_binder_url_github_with_branch` (line 161)

### 1.2. Add `test_post_repository_only_unsupported_source_raises`

- Fixture: `binder_vre_gitlab_only` (already exists in conftest) — `is_repository_only=True`, URL is GitLab
- Call: `post()`
- Assert: raises `UnsupportedBinderSource`
- Replaces: `test_build_binder_url_unsupported_raises_exception` (line 185)

### 1.3. Remove 3 duplicate tests

- `test_build_binder_url_github_simple` (line 153) — already covered by `test_post_repository_only_github`
- `test_build_binder_url_zenodo` (line 169) — already covered by `test_post_repository_only_zenodo`
- `test_build_binder_url_zenodo_http` (line 177) — already covered by `test_post_repository_only_zenodo` (which uses `http://`)

### 1.4. Remove remaining 2 tests after replacement

- `test_build_binder_url_github_with_branch` (line 161)
- `test_build_binder_url_unsupported_raises_exception` (line 185)

**Net:** 5 tests deleted, 2 added = 3 tests removed.

---

## 2. Replace 2 `_clone_remote_files` private-method tests

### 2.1. `test_clone_remote_files_none_url_does_nothing` (line 205)

- This path (`url=None`) is unreachable through `post()` because `_build_local_git_repo` calls `_clone_remote_files(self.request_package.workflow.url, repo)` — if `url=None` you'd get `is_repository_only=False` ∪ no clones. The test verifies a safe early-return in a defensive guard clause.
- **Decision: keep as-is** — it's a valuable defensive guard test and cannot be expressed through the public API.

### 2.2. `test_clone_remote_files_non_github_logs_warning` (line 217)

- With a GitLab URL and `is_repository_only=False`, `post()` would hit `_build_local_git_repo` → `_clone_remote_files("https://gitlab.com/...", repo)` → warning. The test is reachable through `post()`, but asserting on log output (`caplog`) is fragile and still tests an internal implementation detail.
- **Option A:** Convert to a `test_post_non_github_clone_logs_warning` — use `binder_vre_gitlab_only` with a local file to force `is_repository_only=False`, call `post()`, check caplog. Marginally better.
- **Option B:** Keep as-is. The defensive guard against non-GitHub clones is tested.
- **Recommendation:** Option B.

---

## 3. Consolidate 4 borderline side-effect tests

These call `post()` but assert on filesystem/git side effects instead of return value or error behavior.

### 3.1. `test_post_dir_created` (line 22) + `test_post_git_repo_initialized` (line 28)

Both verify `post()` creates a git repo directory. A git repo directory existing is the same as a `.git` subdirectory existing. Merge into one:
- `test_post_creates_git_repo` — call `post()` → assert `.git` dir exists

### 3.2. `test_post_git_deamon_export_created` (line 34)

Verifies `git-daemon-export-ok` file exists. This is an implementation detail of the git daemon setup. **Delete** — if git-daemon export breaks, the integration test will catch it.

### 3.3. `test_post_git_commit` (line 42)

Verifies commit message `"on the fly"`. This is a hardcoded string — testing an implementation constant. **Delete** — commit existence is verified by `test_post_git_repo_initialized` (repo exists means it was committed).

**Net:** 4 tests → 1 consolidated test (3 tests removed).

---

## 4. `_write_start_script` tests (ours — keep as-is)

Tests at lines 240–319 call `_write_start_script` directly — a private method. Testing through `post()` would require:
1. Mock or real git clone of a repo with a `start` in it
2. Assert on git repo content post-`post()`

This is prohibitively complex for unit tests. These are defensible as practical exceptions. **No change.**

---

## Summary

| Action | Tests |
|--------|-------|
| Delete (redundant/duplicate) | `test_build_binder_url_github_simple`, `test_build_binder_url_zenodo`, `test_build_binder_url_zenodo_http`, `test_post_git_deamon_export_created`, `test_post_git_commit` |
| Delete (replaced by new) | `test_build_binder_url_github_with_branch`, `test_build_binder_url_unsupported_raises_exception` |
| Merge | `test_post_dir_created` + `test_post_git_repo_initialized` → `test_post_creates_git_repo` |
| Add new | `test_post_repository_only_github_with_branch`, `test_post_repository_only_unsupported_source_raises` |
| Keep as-is | 5 `_classify_*` (already good), 3 `_write_start_script_*` (practical), 2 `_clone_remote_files_*` (defensive guards), 6 good `test_post_*` |

**Net change:** 23 tests → 17 tests (-6). All remaining tests exercise the public `post()` contract or are documented defensive-guard exceptions.
