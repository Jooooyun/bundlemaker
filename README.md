# BundleMaker

CLI tool that scans your project, collects source files, and builds a single GPT-friendly `bundle.txt`.

No more copy-pasting 30 files into an AI chat window like an idiot.  
Point it at your project, get one clean text bundle, and feed it to your LLM.

---

## Features

- **Auto mode**  
  Scan directories, auto-read files, build `bundle.txt`, then exit.

- **Hybrid mode** (default)  
  Try auto-read first. If it fails (binary, encoding, size), fall back to manual paste.

- **Paste-only mode**  
  Fully manual: you paste content for each file and finish with `\END`.

- **Resumable sessions**  
  State is saved in `bundle_state.json`, so you can stop and resume later.

- **Safe auto-read**  
  - Skips large files (default: > 5 MB)  
  - Skips suspicious names/extensions (`.env`, keys, certs, etc.)  
  - Detects binary files via NULL bytes  

- **TUI-style UX**  
  Colored output, progress, remaining-only view, jump by index, quick commands.

- **Smart file selection (hard-coded)**  
  - Only specific source-like extensions are included  
  - Common junk / build / VCS directories are ignored  
  - Generated files from BundleMaker itself are never re-scanned

---

## File selection rules

BundleMaker is opinionated on purpose. It only picks “code-ish” files and avoids obvious trash / secrets.

### Included extensions

Only files with these lowercase extensions are scanned:

- `py`, `sql`
- `html`, `css`, `js`
- `c`, `h`
- `cpp`, `hpp`, `cc`, `hh`
- `cs`

If you’re wondering “why didn’t my file show up?”,  
check the extension first. If it’s not in this list, it’s ignored.

### Ignored directories

These directories are skipped recursively while walking:

- VCS / tooling:  
  - `.git`, `.svn`, `.hg`
  - `.idea`, `.vscode`
- Python / build junk:  
  - `__pycache__`, `.pytest_cache`
  - `dist`, `build`
  - `venv`, `.venv`
- Node / frontend:  
  - `node_modules`

If your code lives under one of these, move it or relax the rules in the script.

### Auto-read skip rules

Even if a file passes the extension filter, auto-read may still skip it:

- **By name** (exact match):
  - `.env`, `.env.local`, `.env.production`, `.env.development`
  - `id_rsa`, `id_dsa`, `id_ed25519`
- **By extension**:
  - `pem`, `key`, `p12`, `pfx`, `der`, `crt`, `cer`
- **By size**:
  - Larger than **5 MB** → skipped (`too-large(...)`)
- **By content**:
  - Contains NULL bytes → treated as binary and skipped

Skipped files and reasons are visible in AUTO mode in the `SKIPPED (auto-read)` section at the top of the bundle.

### Generated / internal files

These files are **never** scanned or re-included:

- `bundle.txt` (the final output)
- `bundle_state.json` (interactive session state)

So you can safely re-run BundleMaker in the same folder without it eating its own output.

---

## Installation (local script)

For now, clone the repo and run the script directly:

```bash
git clone https://github.com/Jooooyun/bundlemaker.git
cd bundlemaker
python bundlemaker.py
```

You’ll be asked to:

1. Select a mode: `HYBRID / PASTE / AUTO`
2. Paste your project root path (or hit Enter for current directory)
3. Let the tool scan and build the bundle

_PyPI / `pip install bundlemaker` is planned, not live yet._

---

## Usage

### Basic

```bash
python bundlemaker.py
```

- Select mode on the prompt  
- Paste project path  
- Let it run

### With CLI flags

```bash
# Force AUTO mode (non-interactive bundle build)
python bundlemaker.py --auto /path/to/project

# PASTE mode only
python bundlemaker.py --paste /path/to/project

# HYBRID mode (default behavior)
python bundlemaker.py --hybrid /path/to/project
```

Multiple paths:

```bash
python bundlemaker.py --auto /path/to/project1 /path/to/project2
```

Or via prompt:

```text
Paste project root path (Enter = current folder) > C:\proj1;C:\proj2
```

---

## Interactive controls

In HYBRID/PASTE mode:

- `Enter`      → next unfinished file  
- `<number>`   → jump to file index  
- `a`          → set next action to AUTO-READ  
- `p`          → set next action to PASTE  
- `m`          → cycle mode (HYBRID → PASTE → AUTO)  
- `r`          → toggle “remaining-only” view  
- `q`          → quit (with warning if some files have no content)

For paste mode, end the current file by typing:

```text
\END
```

on a single line.

---

## Output format

The tool generates a single `bundle.txt` with this structure:

```text
=== BUNDLE GENERATED: 2025-01-01T12:34:56 ===
=== REL_ROOT: /absolute/path/to/project ===

=== SKIPPED (auto-read) ===
- path/to/secret.pem :: skip-ext(.pem)
- path/to/huge.log :: too-large(12345678 bytes)

=== FILE: src/app.py ===
... file content ...

=== END FILE: src/app.py ===

=== FILE: templates/index.html ===
... file content ...

=== END FILE: templates/index.html ===
```

Drop this file into ChatGPT / Claude / whatever,  
and the model gets the full project context in one shot.

---

## Roadmap

- VSCode extension integration  
- Configurable extension / skip rules  
- Optional JSON / Markdown bundle formats  
- Direct “AI diff → patch” helper

---

## License

MIT License.
