# Remove Remaining Legacy Compatibility Implementation Plan

**Status:** completed on 2026-05-01. Implemented in commit for remaining legacy compatibility cleanup.

> **For Hermes:** Implement directly in small TDD slices; no subagent required unless a slice becomes ambiguous.

**Goal:** Remove the remaining unreleased legacy compatibility surfaces from `hermes-self-improvement`: JSON config input, direct-file import fallbacks, and compatibility wording that suggests old behavior is supported.

**Architecture:** Keep the plugin package-first and current-schema-only. Config loading accepts YAML operator overrides only. Runtime code imports through package-relative imports, with top-level `__init__.py` remaining only as the Hermes plugin discovery shim. Status/report wording should describe current integrations rather than “compatibility”.

**Tech Stack:** Python, pytest, YAML config, Hermes plugin API.

---

## Scope

Do:
- Remove JSON config parsing for explicit `--config` / `HERMES_SELF_IMPROVE_CONFIG`.
- Update tests to use YAML config fixtures only.
- Remove package-internal direct-file import fallbacks such as `except Exception: from config import ...`.
- Keep the root repository `__init__.py` plugin discovery shim; Hermes loads plugin roots this way.
- Rename user-visible `Curator compatibility` wording to current integration/telemetry wording.
- Update docs/tests to stop describing legacy compatibility as active support.

Do not:
- Reintroduce any config aliases or fallback shims.
- Change mutation policy, target routing, scorer behavior, Curator telemetry semantics, or memory provider semantics.
- Remove JSON runtime artifacts such as run reports, calibration ledgers, evidence files, eval fixtures, or `.jsonl` event logs. This cleanup is only for plugin config input and compatibility code.

---

## Task 1: Remove JSON config input support

**Objective:** Config files are YAML-only; explicit JSON config paths fail closed.

**Files:**
- Modify: `hermes_self_improvement/config.py`
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/schemas.py`
- Modify: `tests/test_config_precedence.py`

**Steps:**
1. Add/adjust tests in `tests/test_config_precedence.py`:
   - env override fixture uses `env-override.yaml`.
   - CLI override fixture uses `cli-override.yaml`.
   - explicit `.json` config raises `ValueError` / parse failure with unsupported extension.
2. In `config.py`, remove `json` import if no longer needed.
3. In `_parse_config_text()`, accept only `.yaml` / `.yml`; reject `.json` and suffixless paths.
4. Update docstrings/help strings from `JSON/YAML` to `YAML`.
5. Run:
   ```bash
   python -m pytest tests/test_config_precedence.py -q
   ```

---

## Task 2: Remove package-internal direct import fallbacks

**Objective:** The package uses package-relative imports only; tests and CLI wrappers import the package normally.

**Files:**
- Modify: `hermes_self_improvement/*.py`
- Modify: `hermes self-improvement` only if it relies on direct file import behavior
- Modify tests if they import files by path instead of package module

**Steps:**
1. Search:
   ```bash
   rg 'direct file import|from [a-z_]+ import|except Exception:  # pragma: no cover - direct' hermes_self_improvement
   ```
2. Replace broad direct import fallback blocks with normal relative imports.
3. Keep legitimate optional dependency guards only where they are not compatibility shims, e.g. PyYAML absence checks, Hermes runtime availability checks, DSPy optional imports, and defensive runtime tool availability checks.
4. Run focused tests around imports/surfaces:
   ```bash
   python -m py_compile __init__.py hermes_self_improvement/*.py
   python -m pytest tests/test_cli_surface.py tests/test_plugin_tools.py tests/test_config_precedence.py -q
   ```

---

## Task 3: Rename compatibility wording

**Objective:** User-visible docs/status output should say integration/telemetry, not legacy compatibility.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `tests/test_cli_surface.py`
- Modify: `README.md`, `AGENTS.md`, and bundled operation skill references only where wording implies compatibility support

**Steps:**
1. Change status output heading from `Curator compatibility:` to `Curator telemetry:` or `Curator integration:`.
2. Update JSON payload key only if it is not a persisted contract. Prefer current-only key such as `curator_telemetry` because this plugin is unreleased; do not add alias keys.
3. Update tests expecting old heading/key.
4. Clean docs wording that says historical compatibility may remain. Keep “do not reintroduce legacy commands” warnings where useful.
5. Run:
   ```bash
   python -m pytest tests/test_cli_surface.py tests/test_report_integration.py tests/test_plugin_tools.py -q
   ```

---

## Task 4: Strict search and full validation

**Objective:** Prove the legacy surfaces are gone and the plugin still runs.

**Commands:**
```bash
python -m py_compile __init__.py hermes_self_improvement/*.py tests/*.py
python -m pytest tests -q
hermes self-improvement status
hermes self-improvement improve --dry-run --json | python -m json.tool >/tmp/self_improve_dry_run.json
hermes self-improvement calibrate --dry-run --json | python -m json.tool >/tmp/self_improve_calibrate_dry_run.json
git diff --check
```

Strict searches:
```bash
rg 'config\.json|config\.local\.json|llm_scorer|automation_policy|mutation\.backend: hermes_agent|task_model|reflection_model|llm_source' . -g '!*.pyc' -g '!__pycache__'
rg 'Curator compatibility|direct file import used by tests/wrapper CLI|valid JSON/YAML|Explicit config JSON/YAML' . -g '!*.pyc' -g '!__pycache__'
```

Expected:
- Retired config terms have no hits except current LLM scorer function/error names where semantically current.
- No direct-file import fallback comments remain.
- No user-visible `Curator compatibility` wording remains.
- Full tests and smoke commands pass.

---

## Task 5: Commit and push

**Objective:** Land the cleanup as one coherent refactor commit.

**Commands:**
```bash
git status --short
git diff --stat
git add .
git commit -m "refactor(self-improvement): remove remaining legacy compatibility"
git push
```

After push, report:
- Changed surfaces.
- Validation results.
- Commit hash.
