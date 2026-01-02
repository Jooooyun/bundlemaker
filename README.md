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

- `Enter`  → next unfinished file  
- `<number>` → jump to file index  
- `a` → set next action to AUTO-READ  
- `p` → set next action to PASTE  
- `m` → cycle mode (HYBRID → PASTE → AUTO)  
- `r` → toggle “remaining-only” view  
- `q` → quit (with warning if some files have no content)

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