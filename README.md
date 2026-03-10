# BundleMaker v2.2.0

LLM-friendly project bundler with patch apply, verify, and restore workflow support.

BundleMaker is a Python CLI tool for packaging an entire source project into a single `bundle.txt`, sending it to an LLM for review or modification, then safely applying the modified result back to the real project with verification and rollback support.

---

## Why BundleMaker?

When using LLMs on multi-file projects, context often breaks down:

- only part of the code is considered
- project intent and implementation become separated
- modified results are hard to patch back safely
- rollback is painful when something goes wrong

BundleMaker was built to reduce that friction.

It supports a full workflow:

**Project → Bundle → LLM modification → Patch apply → Verify → Restore**

---

## Features

### Bundle creation
Creates a single `bundle.txt` from multiple project files.

Supported modes:

- **AUTO** — automatically reads files and builds a bundle
- **PASTE** — manually paste file contents
- **HYBRID** — auto-read first, manual fallback if needed

### Patch apply
Compares the original bundle and the modified bundle, then applies the changes back to the real project.

Strategies:

- **SAFE** — small changes + new files only, no deletes
- **FULL** — apply all changes including deletes
- **DRY RUN** — report only, no actual writes

### Verification
Performs real post-apply verification.

- **VERIFY-A** — compares modified bundle against actual disk files
- **VERIFY-B** — rebuilds a fresh bundle from disk and compares again

### Restore / rollback
Supports rollback using:

- manifest records
- file backups
- deleted file snapshots
- restore verification
- created file quarantine

### Config wizard
Interactive generation of `.bundlemaker.json` for:

- allowed extensions
- excluded directories

---

## Typical workflow

### 1. Create a bundle
```bash
python bundlemaker.py --auto
```

This generates:

```text
bundles/bundle.txt
```

### 2. Send the bundle to your LLM
A typical prompt example:

> 1.bundle.txt에는 모든 코드가 들어있고 master문서(EX.개발 명세서) 에는 이 프로젝트의 기획이 담겨있다. 이 모든걸 종합적으로 꼼꼼히 확인하여 지금 코드에서 나타나는 문제점과 버그를 알려줘라

Then save the modified result as:

```text
bundle_modified.txt
```

### 3. Apply the patch
```bash
python bundlemaker.py --patch
```

### 4. Verify the result
BundleMaker automatically runs verification after patching.

### 5. Restore if needed
```bash
python bundlemaker.py --restore
```

---

## Main menu

```text
[1] STEP 1 — Create bundle from project
[2] STEP 3 — Apply patch from modified bundle (+VERIFY)
[c] Configure — create/overwrite .bundlemaker.json
[r] Restore — rollback from patch manifest backups
[q] Quit
```

---

## CLI options

### Configure
```bash
python bundlemaker.py --config
python bundlemaker.py --configure
```

### Bundle creation
```bash
python bundlemaker.py --auto
python bundlemaker.py --paste
python bundlemaker.py --hybrid
```

### Patch apply
```bash
python bundlemaker.py --patch
python bundlemaker.py --apply-patch
```

### Restore
```bash
python bundlemaker.py --restore
python bundlemaker.py --rollback
```

---

## Directory layout

Internal artifacts are stored under the project root:

```text
<PROJECT_ROOT>/
└─ .bundlemaker/
   ├─ state/
   ├─ manifests/
   ├─ reports/
   ├─ backups/
   ├─ locks/
   └─ quarantine/
```

Generated bundles are stored under the current working directory:

```text
<CWD>/
└─ bundles/
   ├─ bundle.txt
   └─ bundle_applied_<timestamp>.txt
```

These paths are automatically excluded from scanning:

- `.bundlemaker`
- `bundles`

---

## Default supported extensions

```text
py, sql,
html, css, js,
c, h,
cpp, hpp, cc, hh,
cs
```

---

## Default excluded directories

```text
.git, .svn, .hg
__pycache__, .pytest_cache
node_modules
venv, .venv
dist, build
.idea, .vscode
.bundlemaker
bundles
```

---

## Bundle format

Generated bundles follow this structure:

```text
=== BUNDLE GENERATED: 2026-03-09T12:34:56 ===
=== REL_ROOT: C:\project ===

=== FILE: src/main.py ===
print("hello")
=== END FILE: src/main.py ===
```

---

## Safety features

BundleMaker includes:

- atomic file writes
- root boundary checks
- path traversal prevention
- manifest-based patch tracking
- backup handling
- duplicate STEP 3 lock
- disk verification after patch
- restore verification after rollback
- quarantine support for created files

---

## Auto-read safeguards

Auto-read may skip:

- files larger than 5MB
- binary files
- sensitive names such as `.env`, `id_rsa`
- sensitive extensions such as `.pem`, `.key`, `.pfx`, `.crt`

---

## Recommended usage order

```text
1. Configure rules
2. Create bundle
3. Send bundle to LLM
4. Save modified result as bundle_modified.txt
5. Run patch
6. Check verify reports
7. Restore if necessary
```

For important projects, start with:

- `DRY RUN`
- then `SAFE`
- use `FULL` only when needed

---

## Current status

BundleMaker is currently a **personal experimental tool** focused on text-based source projects and LLM-assisted workflows.

It is practical for personal use and internal tooling, but still evolving.

---

## Best use cases

- multi-file LLM code review
- whole-project context packaging
- safer LLM-assisted patch workflows
- educational / experimental coding
- internal developer tooling
- research prototypes

---

## Summary

**BundleMaker v2.2.0 helps turn multi-file codebases into a single LLM-friendly bundle, then safely apply, verify, and restore changes through a structured workflow.**
