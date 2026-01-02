#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import sys
import os
import json
from datetime import datetime

# =========================
# ✅ Config: extensions / exclude rules (hard-coded)
# =========================

# ✅ Allowed extensions (lowercase, without dot)
# C# uses `.cs`. There's no such thing as ".c#". Damn.
ALLOWED_EXTS = {
    "py", "sql",
    "html", "css", "js",
    "c", "h",
    "cpp", "hpp", "cc", "hh",
    "cs",
}

# ✅ Default excluded directories (hard-coded)
EXCLUDE_DIRS = {
    ".git", ".svn", ".hg",
    "__pycache__", ".pytest_cache",
    "node_modules",
    "venv", ".venv",
    "dist", "build",
    ".idea", ".vscode",
}

# =========================
# ✅ Generated files / state files
# =========================
BUNDLE_NAME = "bundle.txt"
STATE_FILE = "bundle_state.json"
EXCLUDE_FILES = {BUNDLE_NAME, STATE_FILE}

# =========================
# ✅ Output format
# =========================
HEADER_FMT = "=== FILE: {path} ===\n"
FOOTER_FMT = "=== END FILE: {path} ===\n"
SECTION_GAP = "\n"

# ✅ Section end marker (user types \END on a single line)
SECTION_END_MARKER = r"\END"

# =========================
# ✅ Modes
# =========================
MODE_AUTO = "auto"      # Scan → auto-read files → build bundle and exit
MODE_PASTE = "paste"    # Legacy mode: user copy-pastes file contents
MODE_HYBRID = "hybrid"  # Default: auto-read first, fall back to paste when needed
MODES = (MODE_HYBRID, MODE_PASTE, MODE_AUTO)

# =========================
# ✅ auto-read safety guards (hard-coded)
# =========================
AUTO_MAX_BYTES = 5 * 1024 * 1024  # Skip files larger than 5MB (bundle hell prevention)
AUTO_ENCODINGS = ("utf-8", "utf-8-sig", "cp949")

# Optional: names/extensions to skip in auto-read (for secrets / noise)
AUTO_SKIP_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_dsa", "id_ed25519",
}
AUTO_SKIP_EXTS = {
    "pem", "key", "p12", "pfx", "der", "crt", "cer",
}

# =========================
# ✅ ANSI colors
# =========================
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"


def _use_color() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


USE_COLOR = _use_color()


def color(text: str, *styles: str) -> str:
    if (not USE_COLOR) or (not styles):
        return text
    return "".join(styles) + text + RESET


def _to_posix(path: str) -> str:
    return path.replace(os.sep, "/")


def _from_posix(path: str) -> str:
    return path.replace("/", os.sep)


def _strip_wrapping_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def parse_mode_and_dirs(argv: list[str]) -> tuple[str, list[str], bool]:
    """
    Parse CLI flags and split mode vs remaining arguments.

    Supported mode flags:
      --auto   / -a
      --paste  / -p
      --hybrid / -h

    * If no mode flag is given, the script will later ask the user
      to select a mode interactively BEFORE asking for paths.

    Returns: (mode, remaining_paths, mode_forced_flag)
    """
    mode = MODE_HYBRID
    rest: list[str] = []
    forced = False

    for a in argv:
        if a in ("--auto", "-a"):
            mode = MODE_AUTO
            forced = True
        elif a in ("--paste", "-p"):
            mode = MODE_PASTE
            forced = True
        elif a in ("--hybrid", "-h"):
            mode = MODE_HYBRID
            forced = True
        else:
            rest.append(a)

    return mode, rest, forced


def select_mode_before_path(default: str = MODE_HYBRID) -> str:
    """
    Ask the user to choose a mode before asking for paths.

    - Enter → default (HYBRID by default)
    - 1 → HYBRID
    - 2 → PASTE
    - 3 → AUTO
    """
    print()
    print(color("=========== Select Mode ===========", BOLD))
    print(color("1) HYBRID", CYAN), "- auto-read by default, fall back to paste")
    print(color("2) PASTE ", CYAN), "- manual copy-paste for every file + \\END")
    print(color("3) AUTO  ", CYAN), "- auto-read everything and build bundle immediately")
    print(color(f"[Enter]=default({default.upper()})", DIM))
    while True:
        try:
            ans = input(color("Mode > ", BOLD)).strip()
        except EOFError:
            return default

        if ans == "":
            return default
        if ans == "1":
            return MODE_HYBRID
        if ans == "2":
            return MODE_PASTE
        if ans == "3":
            return MODE_AUTO

        print(color("Only 1/2/3 or Enter.", RED))


def get_scan_dirs(paths_from_argv: list[str]) -> list[str]:
    r"""
    Decide which directories/files to scan.

    1) If paths are provided via CLI, use them:
       python bundlemaker.py "C:\path\to\project" "C:\path\to\other"

    2) If no paths were passed, ask once via prompt:
       Paste project root path ... >

    - Windows backslashes are fine.
    - Quotes from drag-and-drop in terminals will be stripped.

    Multiple paths can be separated by ';' in the prompt.
    """
    if paths_from_argv:
        return [_strip_wrapping_quotes(x) for x in paths_from_argv if x.strip()]

    try:
        p = input(color("Paste project root path (Enter = current folder) > ", BOLD)).strip()
    except EOFError:
        p = ""

    if not p:
        return ["."]
    p = _strip_wrapping_quotes(p)

    # Allow multiple paths separated by ';'
    if ";" in p:
        parts = [_strip_wrapping_quotes(x) for x in p.split(";")]
        return [x for x in parts if x]
    return [p]


def normalize_base_dirs(base_dirs: list[str]) -> list[str]:
    out: list[str] = []
    cwd = os.getcwd()

    for b in base_dirs:
        if not b:
            continue
        b = _strip_wrapping_quotes(b)

        if os.path.isabs(b):
            abs_path = os.path.abspath(b)
        else:
            abs_path = os.path.abspath(os.path.join(cwd, b))

        out.append(abs_path)

    seen = set()
    uniq: list[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def compute_rel_root(base_dirs_abs: list[str]) -> str:
    """
    Compute the common root directory used for relative paths.
    """
    if not base_dirs_abs:
        return os.getcwd()
    if len(base_dirs_abs) == 1:
        if os.path.isfile(base_dirs_abs[0]):
            return os.path.dirname(base_dirs_abs[0])
        return base_dirs_abs[0]
    try:
        return os.path.commonpath(base_dirs_abs)
    except Exception:
        return os.getcwd()


def generate_files(base_dirs_abs: list[str]) -> list[str]:
    """
    Walk given base directories and collect all allowed files
    as POSIX-style relative paths from rel_root.
    """
    out: set[str] = set()
    rel_root = compute_rel_root(base_dirs_abs)

    def allow_file(fp: str) -> bool:
        name = os.path.basename(fp)
        if name in EXCLUDE_FILES:
            return False
        if ".tmp." in name:
            return False
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        return bool(ext) and ext in ALLOWED_EXTS

    for base_path in base_dirs_abs:
        if not os.path.exists(base_path):
            continue

        if os.path.isfile(base_path):
            if allow_file(base_path):
                rel = os.path.relpath(base_path, rel_root)
                out.add(_to_posix(rel))
            continue

        for cur, dirnames, filenames in os.walk(base_path):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for fn in filenames:
                full = os.path.join(cur, fn)
                if allow_file(full):
                    rel = os.path.relpath(full, rel_root)
                    out.add(_to_posix(rel))

    return sorted(out)


def next_undone_index(done: list[bool], start: int = 0) -> int | None:
    for i in range(start, len(done)):
        if not done[i]:
            return i
    for i in range(0, start):
        if not done[i]:
            return i
    return None


def atomic_write_text(path: str, data: str, encoding: str = "utf-8") -> None:
    """
    Safely write text to disk using a temporary file and atomic replace.
    """
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding=encoding, newline="") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def atomic_write_json(path: str, obj: object) -> None:
    data = json.dumps(obj, ensure_ascii=False, indent=2)
    atomic_write_text(path, data, encoding="utf-8")


def save_state(
    files: list[str],
    scan_dirs_abs: list[str],
    rel_root: str,
    done: list[bool],
    contents: dict[str, str],
    cursor: int,
    show_remaining_only: bool,
    mode: str,
) -> None:
    """
    Persist current interactive session so the user can resume later.
    """
    state = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scan_dirs_abs": scan_dirs_abs,
        "rel_root": rel_root,
        "files": files,
        "done": done,
        "cursor": cursor,
        "show_remaining_only": show_remaining_only,
        "mode": mode,
        "contents": contents,
    }
    atomic_write_json(STATE_FILE, state)


def load_state(
    files: list[str],
    scan_dirs_abs: list[str],
    rel_root: str,
) -> tuple[list[bool], dict[str, str], int, bool, str] | None:
    """
    Try to restore an existing session state if it matches the current setup.
    """
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        if state.get("scan_dirs_abs") != scan_dirs_abs:
            return None
        if state.get("rel_root") != rel_root:
            return None
        if state.get("files") != files:
            return None

        done = state.get("done")
        contents = state.get("contents")
        cursor = state.get("cursor", -1)
        show_remaining_only = state.get("show_remaining_only", False)
        mode = state.get("mode", MODE_HYBRID)

        if not isinstance(done, list) or len(done) != len(files):
            return None
        if not isinstance(contents, dict):
            return None
        if not isinstance(cursor, int):
            cursor = -1
        if not isinstance(show_remaining_only, bool):
            show_remaining_only = False
        if mode not in MODES:
            mode = MODE_HYBRID

        contents = {k: v for k, v in contents.items() if k in files and isinstance(v, str)}
        done = [bool(x) for x in done]
        cursor = max(-1, min(cursor, len(files) - 1))

        return done, contents, cursor, show_remaining_only, mode
    except Exception:
        return None


def _mode_label(mode: str) -> str:
    if mode == MODE_AUTO:
        return "AUTO"
    if mode == MODE_PASTE:
        return "PASTE"
    return "HYBRID"


def print_screen(
    files: list[str],
    done: list[bool],
    show_remaining_only: bool,
    cursor: int,
    scan_dirs_abs: list[str],
    mode: str,
    next_action_override: str | None,
) -> None:
    """
    Render the main interactive screen with file list and progress.
    """
    total = len(files)
    done_count = sum(1 for x in done if x)

    if total == 0:
        nxt = None
    else:
        start = (cursor + 1) % total if cursor >= 0 else 0
        nxt = next_undone_index(done, start)

    nxt_name = files[nxt] if nxt is not None else "(none)"
    mode_str = _mode_label(mode)
    if next_action_override == "a":
        override_str = " (next: AUTO-READ)"
    elif next_action_override == "p":
        override_str = " (next: PASTE)"
    else:
        override_str = ""

    print()
    print(color("=============== Bundle Maker ===============", BOLD))
    print(f"Mode: {color(mode_str, CYAN)}{color(override_str, DIM)}")
    print(f"Scanned files: {color(str(total), CYAN)}")
    print(f"Scan roots: {color(' | '.join(scan_dirs_abs), DIM)}")
    print(f"Output: {color(BUNDLE_NAME, CYAN)}")
    print(
        f"Progress: {color(str(done_count), GREEN if done_count == total else YELLOW)}"
        f"/{total}  |  Next: {color(nxt_name, YELLOW)}"
    )
    print(f"End marker: {color(SECTION_END_MARKER, CYAN)}")
    print("Cmd:", end=" ")
    print(
        color("[Enter]=next", CYAN), "|",
        color("[number]=jump", CYAN), "|",
        color("a=auto-read(next)", CYAN), "|",
        color("p=paste(next)", CYAN), "|",
        color("m=mode", CYAN), "|",
        color("r=remaining", CYAN), "|",
        color("q=quit", CYAN)
    )
    print(color("Tip: 'a 12' or 'p 12' is also supported.", DIM))
    print("---------------------------------------------------")

    for i, pth in enumerate(files):
        if show_remaining_only and done[i]:
            continue

        mark = "[x]" if done[i] else "[ ]"
        idx_str = f"{i:>2}"

        if done[i]:
            line = f"{idx_str} : {mark} {pth}"
            print(color(line, DIM, GREEN))
        else:
            if nxt is not None and i == nxt:
                line = f"{idx_str} : {mark} {pth}  <-- next"
                print(color(line, YELLOW, BOLD))
            else:
                line = f"{idx_str} : {mark} {pth}"
                print(line)

    if show_remaining_only:
        print("---------------------------------------------------")
        print(color("(remaining-only view ON)", DIM))


def read_cmd() -> str:
    try:
        return input(color("> ", BOLD)).strip()
    except EOFError:
        return "q"


def ask_yes_no(prompt: str, default_no: bool = True) -> bool:
    """
    Simple yes/no prompt. Default is NO unless the user explicitly says yes.
    """
    try:
        ans = input(prompt).strip().lower()
    except EOFError:
        return False

    if ans in ("y", "yes"):
        return True
    if ans in ("n", "no"):
        return False
    return not default_no


def capture_section(path: str, index: int, total: int, progress_step: int = 50) -> str:
    """
    Capture pasted content for a single file path until SECTION_END_MARKER appears.
    """
    print()
    print(color(f"[{index+1}/{total}] {path}", BOLD))
    print(f"Paste the file content. When you're done, type {color(SECTION_END_MARKER, CYAN)} on a single line.")
    print("(Input won't be echoed back, only progress will be shown.)\n")

    lines: list[str] = []
    line_count = 0

    while True:
        line = sys.stdin.readline()
        if line == "":
            sys.stdout.write("\r" + " " * 60 + "\r")
            sys.stdout.flush()
            print(color(f"STDIN EOF. {line_count} lines captured.", YELLOW))
            break

        if line.strip() == SECTION_END_MARKER:
            sys.stdout.write("\r" + " " * 60 + "\r")
            sys.stdout.flush()
            print(color(f"{line_count} lines captured for [{path}].", GREEN))
            break

        lines.append(line)
        line_count += 1

        if line_count % progress_step == 0:
            msg = f"Capturing... {line_count} lines"
            sys.stdout.write("\r" + msg[:60].ljust(60))
            sys.stdout.flush()

    return "".join(lines)


def _should_skip_autoread(abs_fp: str) -> tuple[bool, str]:
    name = os.path.basename(abs_fp)
    ext = os.path.splitext(name)[1].lower().lstrip(".")

    if name in AUTO_SKIP_NAMES:
        return True, f"skip-name({name})"
    if ext in AUTO_SKIP_EXTS:
        return True, f"skip-ext(.{ext})"

    try:
        sz = os.path.getsize(abs_fp)
        if sz > AUTO_MAX_BYTES:
            return True, f"too-large({sz} bytes)"
    except Exception:
        pass

    return False, ""


def auto_read_file(rel_root: str, rel_posix_path: str) -> tuple[str | None, str]:
    """
    Try to read a file from disk (binary-safe) and decode as text.
    Returns (content_or_None, reason_string).
    """
    abs_fp = os.path.join(rel_root, _from_posix(rel_posix_path))

    if not os.path.exists(abs_fp):
        return None, "not-found"

    skip, why = _should_skip_autoread(abs_fp)
    if skip:
        return None, why

    try:
        with open(abs_fp, "rb") as f:
            data = f.read()
    except Exception as e:
        return None, f"read-failed({type(e).__name__})"

    if b"\x00" in data:
        return None, "binary-detected(NULL)"

    for enc in AUTO_ENCODINGS:
        try:
            return data.decode(enc), f"ok({enc})"
        except Exception:
            continue

    return None, "decode-failed"


def cycle_mode(mode: str) -> str:
    i = MODES.index(mode) if mode in MODES else 0
    return MODES[(i + 1) % len(MODES)]


def build_bundle_text(rel_root: str, files: list[str], contents: dict[str, str], skipped: dict[str, str]) -> str:
    """
    Assemble the final bundle.txt contents.
    """
    parts: list[str] = []
    parts.append(f"=== BUNDLE GENERATED: {datetime.now().isoformat(timespec='seconds')} ===\n")
    parts.append(f"=== REL_ROOT: {rel_root} ===\n")

    if skipped:
        parts.append("=== SKIPPED (auto-read) ===\n")
        for p, why in sorted(skipped.items()):
            parts.append(f"- {p} :: {why}\n")
        parts.append("\n")

    parts.append("\n")

    for path in files:
        if path not in contents:
            continue
        parts.append(HEADER_FMT.format(path=path))
        body = contents[path]
        parts.append(body)
        if body and not body.endswith("\n"):
            parts.append("\n")
        parts.append(FOOTER_FMT.format(path=path))
        parts.append(SECTION_GAP)

    return "".join(parts)


def main() -> int:
    # ✅ 1) Decide mode first
    mode, rest_paths, mode_forced = parse_mode_and_dirs(sys.argv[1:])
    if not mode_forced:
        mode = select_mode_before_path(default=MODE_HYBRID)

    # ✅ 2) Then collect and normalize scan paths
    scan_dirs_raw = get_scan_dirs(rest_paths)
    scan_dirs_abs = normalize_base_dirs(scan_dirs_raw)
    rel_root = compute_rel_root(scan_dirs_abs)

    files = generate_files(scan_dirs_abs)
    if not files:
        print(color("No files found to scan.", RED))
        print(color("Check:", YELLOW), "are the paths correct? is the extension in ALLOWED_EXTS?")
        print(color("Scan roots:", DIM), scan_dirs_abs)
        return 1

    # =========================
    # ✅ AUTO mode: non-interactive, build bundle and exit
    # =========================
    if mode == MODE_AUTO:
        print(color("AUTO mode: reading files directly and building bundle.", BOLD))
        print(color("No copy-paste. Just build.", DIM))

        contents: dict[str, str] = {}
        skipped: dict[str, str] = {}

        for i, p in enumerate(files, start=1):
            c, why = auto_read_file(rel_root, p)
            if c is None:
                skipped[p] = why
                continue
            contents[p] = c

            if i % 50 == 0:
                print(color(f"Reading... {i}/{len(files)}", DIM))

        bundle_text = build_bundle_text(rel_root, files, contents, skipped)
        atomic_write_text(BUNDLE_NAME, bundle_text, encoding="utf-8")

        print()
        print(color(f"Done. Created: {BUNDLE_NAME} | Included: {len(contents)}/{len(files)}", BOLD))
        if skipped:
            print(color("Skipped files:", YELLOW))
            for p, why in sorted(skipped.items()):
                print(" -", p, "::", why)
        else:
            print(color("No skipped files. Clean.", GREEN))
        return 0

    # =========================
    # ✅ INTERACTIVE (HYBRID/PASTE)
    # =========================
    done = [False] * len(files)
    show_remaining_only = False
    contents: dict[str, str] = {}
    cursor = -1
    next_action_override: str | None = None  # "a" or "p"

    loaded = load_state(files, scan_dirs_abs, rel_root)
    if loaded is not None:
        done, contents, cursor, show_remaining_only, saved_mode = loaded
        # If you want, you can respect saved_mode instead of current mode.
        # For now, we keep the mode the user just picked.
        print(color("Bundle Maker resume: existing state loaded.", BOLD))
        print("Resumed. Let's keep going.\n")
    else:
        print(color("Bundle Maker started.", BOLD))
        print("This is the real workflow.\n")

    try:
        while True:
            print_screen(files, done, show_remaining_only, cursor, scan_dirs_abs, mode, next_action_override)
            cmd = read_cmd()

            if cmd.lower() == "q":
                remaining = [p for p, d in zip(files, done) if not d]
                if remaining:
                    print()
                    print(color("You still have files with no content:", YELLOW))
                    for p in remaining:
                        print(" -", p)
                    if not ask_yes_no(color("Quit anyway? (y/N) > ", RED), default_no=True):
                        print(color("Aborted. Keep going.", GREEN))
                        continue
                break

            if cmd.lower() == "r":
                show_remaining_only = not show_remaining_only
                save_state(files, scan_dirs_abs, rel_root, done, contents, cursor, show_remaining_only, mode)
                continue

            if cmd.lower() == "m":
                mode = cycle_mode(mode)
                save_state(files, scan_dirs_abs, rel_root, done, contents, cursor, show_remaining_only, mode)
                continue

            if cmd.lower() == "a":
                next_action_override = "a"
                continue
            if cmd.lower() == "p":
                next_action_override = "p"
                continue

            # 'a 12' / 'p 12'
            action = None
            idx = None
            parts = cmd.split()
            if len(parts) == 2 and parts[0].lower() in ("a", "p") and parts[1].isdigit():
                action = parts[0].lower()
                idx = int(parts[1])
            elif cmd == "":
                start = (cursor + 1) % len(done) if cursor >= 0 else 0
                idx = next_undone_index(done, start)
                if idx is None:
                    print()
                    print(color("All files are done. If you're finished, press q to quit.", GREEN))
                    continue
            else:
                if not cmd.isdigit():
                    print()
                    print(color("Valid inputs: Enter / number / a / p / m / r / q only.", RED))
                    continue
                idx = int(cmd)

            if idx is None or idx < 0 or idx >= len(files):
                print()
                print(color("Index out of range.", RED))
                continue

            path = files[idx]

            if done[idx]:
                ok = ask_yes_no(
                    color(f"\n[{path}] is already done. Overwrite it? (y/N) > ", YELLOW),
                    default_no=True,
                )
                if not ok:
                    print(color("Cancelled.", DIM))
                    continue

            # Decide the action for this file
            if action is None:
                if next_action_override is not None:
                    action = next_action_override
                else:
                    if mode == MODE_PASTE:
                        action = "p"
                    else:
                        action = "a"
            next_action_override = None

            # Execute action
            if action == "a":
                content, why = auto_read_file(rel_root, path)
                if content is None:
                    print()
                    print(color(f"[{path}] AUTO-READ failed/skipped: {why}", YELLOW))
                    if mode == MODE_HYBRID:
                        if ask_yes_no(color("Switch to PASTE mode for this file? (y/N) > ", CYAN), default_no=True):
                            content = capture_section(path, idx, len(files))
                        else:
                            print(color("Skipped. Move on to something else.", DIM))
                            continue
                    else:
                        continue
                contents[path] = content
                done[idx] = True
                cursor = idx
                print(color(f"\n[{path}] AUTO-READ complete.", GREEN))

            else:  # action == "p"
                content = capture_section(path, idx, len(files))
                contents[path] = content
                done[idx] = True
                cursor = idx
                print(color(f"\n[{path}] PASTE capture complete.", GREEN))

            save_state(files, scan_dirs_abs, rel_root, done, contents, cursor, show_remaining_only, mode)
            print(color(f"(autosaved -> {STATE_FILE})", DIM))

    except KeyboardInterrupt:
        print()
        print(color("KeyboardInterrupt detected. Saving state and exiting.", YELLOW))
        save_state(files, scan_dirs_abs, rel_root, done, contents, cursor, show_remaining_only, mode)

    bundle_text = build_bundle_text(rel_root, files, contents, skipped={})
    atomic_write_text(BUNDLE_NAME, bundle_text, encoding="utf-8")

    done_count = sum(1 for x in done if x)
    print()
    print(color(f"Done. Created: {BUNDLE_NAME} | done flags: {done_count}/{len(files)}", BOLD))

    remaining = [p for p, d in zip(files, done) if not d]
    if remaining:
        print(color("Files with no content (still incomplete):", YELLOW))
        for p in remaining:
            print(" -", p)
    else:
        print(color("All files completed. Good job.", GREEN))

    print(color("Re-running a file will fully overwrite its previous content in the bundle.", CYAN))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
