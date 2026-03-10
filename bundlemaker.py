#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import sys
import os
import json
import difflib
import shutil
import hashlib
from datetime import datetime

# =========================================================
# ✅ BundleMaker v2.1 (ARTIFACTS PACKED)
# - STEP 1: 번들 생성 (auto / hybrid / paste)
# - STEP 3: 번들 diff + 패치 적용 (safe / full / dry-run)
# - VERIFY: 적용 후 디스크/재번들 교차검증
# - RESTORE: manifest 기반 롤백(복구) + restore-verify
#
# ✅ NEW:
# - state / reports / manifests / backups / locks / quarantine
#   -> ALL go under:  <REL_ROOT>/.bundlemaker/
#
# ✅ CHANGE:
# - bundle outputs ALWAYS go under: <CWD>/bundles/
#   (bundle.txt, bundle_applied_*.txt 등)
#
# ✅ SAFETY:
# - <CWD>/bundles/ 는 스캔에서 하드 제외 (자기 번들 다시 번들링 방지)
# =========================================================

# =========================
# ✅ Product config (wizard-based)
# =========================
CONFIG_FILE = ".bundlemaker.json"

# ✅ Default allowed extensions (lowercase, without dot)
DEFAULT_ALLOWED_EXTS = {
    "py", "sql",
    "html", "css", "js",
    "c", "h",
    "cpp", "hpp", "cc", "hh",
    "cs",
}

# ✅ Default excluded directories (directory name filter)
DEFAULT_EXCLUDE_DIRS = {
    ".git", ".svn", ".hg",
    "__pycache__", ".pytest_cache",
    "node_modules",
    "venv", ".venv",
    "dist", "build",
    ".idea", ".vscode",
}

# ✅ Wizard config template (mode: default/custom)
CONFIG_TEMPLATE = {
    "version": 1,
    "generated_at": None,
    "extensions": {
        "mode": "default",   # "default" or "custom"
        "only": [],          # used when mode="custom"
        "add": [],           # used when mode="default"
        "remove": []
    },
    "exclude_dirs": {
        "mode": "default",   # "default" or "custom"
        "only": [],          # used when mode="custom"
        "add": [],
        "remove": []
    }
}

# =========================
# ✅ Artifact directory (ALL internal generated files go here)
# =========================
ARTIFACT_DIRNAME = ".bundlemaker"
ARTIFACT_SUBDIRS = {
    "bundles": "bundles",        # (legacy / not used for output bundles anymore)
    "state": "state",
    "manifests": "manifests",
    "reports": "reports",
    "backups": "backups",
    "locks": "locks",
    "quarantine": "quarantine",
}

# =========================
# ✅ Bundle OUTPUT directory (CWD-based)
# =========================
BUNDLES_OUT_DIRNAME = "bundles"   # <CWD>/bundles/

def _bundles_out_dir() -> str:
    return os.path.join(os.getcwd(), BUNDLES_OUT_DIRNAME)

def bundle_out_path(filename: str) -> str:
    """
    Output bundle files under <CWD>/bundles/
    """
    out_dir = _bundles_out_dir()
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, filename)

def _art_root(rel_root: str) -> str:
    return os.path.join(rel_root, ARTIFACT_DIRNAME)

def _art_dir(rel_root: str, key: str) -> str:
    return os.path.join(_art_root(rel_root), ARTIFACT_SUBDIRS[key])

def ensure_artifacts(rel_root: str) -> None:
    """
    Create .bundlemaker/ subdirectories under rel_root.
    """
    try:
        os.makedirs(_art_root(rel_root), exist_ok=True)
        for k in ARTIFACT_SUBDIRS:
            os.makedirs(_art_dir(rel_root, k), exist_ok=True)
    except Exception:
        # never hard fail on artifact dir creation
        pass

def art_path(rel_root: str, key: str, filename: str) -> str:
    ensure_artifacts(rel_root)
    return os.path.join(_art_dir(rel_root, key), filename)

def _rel_posix_from_abs(rel_root: str, abs_path: str) -> str:
    return _to_posix(os.path.relpath(abs_path, rel_root))

def _rel_posix_from_cwd(abs_path: str) -> str:
    """
    Pretty print path relative to current working dir.
    """
    try:
        return _to_posix(os.path.relpath(abs_path, os.getcwd()))
    except Exception:
        return _to_posix(abs_path)

# =========================
# ✅ Generated files / state files
# =========================
BUNDLE_BASENAME = "bundle.txt"
STATE_BASENAME = "bundle_state.json"
EXCLUDE_FILES = {BUNDLE_BASENAME, STATE_BASENAME, CONFIG_FILE}

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
AUTO_MAX_BYTES = 5 * 1024 * 1024  # Skip files larger than 5MB
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
# ✅ Backup / restore / verify artifacts
# =========================
MANIFEST_PREFIX = "bundle_patch_manifest_"
MANIFEST_EXT = ".json"
RESTORE_SAFETY_SUFFIX = ".restorebak_"

VERIFY_REPORT_PREFIX = "bundle_verify_report_"
REBUNDLE_REPORT_PREFIX = "bundle_rebundle_compare_"
REBUNDLE_NAME_PREFIX = "bundle_applied_"
RESTORE_VERIFY_REPORT_PREFIX = "bundle_restore_verify_report_"

# STEP3 lock name (stored under .bundlemaker/locks/)
STEP3_LOCK_BASENAME = ".step3.lock"

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


def _strip_bundle_tail(s: str) -> str:
    """
    Strip trailing '===' from bundle header values.
    Example:
      'C:\\proj\\x ===' -> 'C:\\proj\\x'
      'templates/a.html ===' -> 'templates/a.html'
    """
    s = s.strip()
    if s.endswith("==="):
        s = s[:-3].strip()
    return s


def _is_within_root(root: str, target: str) -> bool:
    """
    root 밖으로 튀는 경로 차단 (path traversal 방지)
    """
    root = os.path.abspath(root)
    target = os.path.abspath(target)
    try:
        common = os.path.commonpath([root, target])
        return common == root
    except Exception:
        return False


def atomic_write_text(path: str, data: str, encoding: str = "utf-8") -> None:
    """
    Safely write text to disk using a temporary file and atomic replace.
    """
    tmp = f"{path}.tmp.{os.getpid()}"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding=encoding, newline="") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def atomic_write_json(path: str, obj: object) -> None:
    data = json.dumps(obj, ensure_ascii=False, indent=2)
    atomic_write_text(path, data, encoding="utf-8")


def _acquire_step3_lock(rel_root: str) -> bool:
    """
    Prevent STEP3 from running multiple times concurrently or via re-entry.
    Works on Windows too (O_CREAT | O_EXCL).
    """
    ensure_artifacts(rel_root)
    lock_path = art_path(rel_root, "locks", STEP3_LOCK_BASENAME)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except Exception:
        # If lock fails unexpectedly, don't block execution.
        return True


def _release_step3_lock(rel_root: str) -> None:
    try:
        ensure_artifacts(rel_root)
        lock_path = art_path(rel_root, "locks", STEP3_LOCK_BASENAME)
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception:
        pass


def _sha256_file(abs_path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(abs_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


# =========================
# ✅ Wizard helpers
# =========================

def _normalize_ext(x: str) -> str:
    x = (x or "").strip().lower()
    if x.startswith("."):
        x = x[1:]
    return x


def _normalize_dirname(x: str) -> str:
    return (x or "").strip()


def _parse_csv_list(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


def _ask(prompt: str, default: str | None = None) -> str:
    try:
        s = input(prompt).strip()
    except EOFError:
        s = ""
    if s == "" and default is not None:
        return default
    return s


def _ask_yes_no(prompt: str, default_yes: bool = False) -> bool:
    """
    y/yes -> True, n/no -> False, empty -> default
    """
    try:
        s = input(prompt).strip().lower()
    except EOFError:
        return default_yes
    if s in ("y", "yes"):
        return True
    if s in ("n", "no"):
        return False
    return default_yes


def _print_set_preview(title: str, items: set[str], max_items: int = 24) -> None:
    arr = sorted(items)
    head = arr[:max_items]
    suffix = "" if len(arr) <= max_items else f" ... (+{len(arr)-max_items} more)"
    print(color(f"{title} ({len(arr)}): ", BOLD) + color(", ".join(head) + suffix, DIM))


def wizard_config(rel_root: str) -> dict:
    """
    Interactive wizard that produces CONFIG_TEMPLATE-shaped dict.
    """
    cfg = json.loads(json.dumps(CONFIG_TEMPLATE))  # deep copy
    cfg["generated_at"] = datetime.now().isoformat(timespec="seconds")

    print()
    print(color("=============== CONFIG WIZARD ===============", BOLD))
    print(color(f"Project root: {rel_root}", DIM))
    print(color("Rule: Press Enter to skip and move on.", DIM))
    print()

    # ---------- Chapter 1: Extensions ----------
    while True:
        print(color("----- Chapter 1: Extensions -----", BOLD))
        _print_set_preview("Default extensions", DEFAULT_ALLOWED_EXTS)

        use_default = _ask_yes_no(color("Use DEFAULT extensions? (Enter=Yes / n=No) > ", CYAN), default_yes=True)
        if use_default:
            cfg["extensions"]["mode"] = "default"
            add_raw = _ask(color("Add extensions (comma, empty=skip) > ", BOLD), default="")
            rm_raw = _ask(color("Remove extensions (comma, empty=skip) > ", BOLD), default="")

            add_list = [_normalize_ext(x) for x in _parse_csv_list(add_raw)]
            rm_list = [_normalize_ext(x) for x in _parse_csv_list(rm_raw)]
            add_list = [x for x in add_list if x]
            rm_list = [x for x in rm_list if x]

            cfg["extensions"]["only"] = []
            cfg["extensions"]["add"] = sorted(set(add_list))
            cfg["extensions"]["remove"] = sorted(set(rm_list))
            print(color("[OK] Extensions configured (DEFAULT mode).", GREEN))
            break

        # custom
        cfg["extensions"]["mode"] = "custom"
        only_raw = _ask(color("Select ONLY extensions to include (comma). empty=fall back > ", BOLD), default="")
        only_list = [_normalize_ext(x) for x in _parse_csv_list(only_raw)]
        only_list = [x for x in only_list if x]
        only_set = set(only_list)

        if not only_set:
            print(color("WARNING: CUSTOM mode but 'only' is empty.", YELLOW))
            go_default = _ask_yes_no(color("Proceed with DEFAULT and continue to next chapter? (y/n) > ", CYAN), default_yes=False)
            if go_default:
                cfg["extensions"]["mode"] = "default"
                cfg["extensions"]["only"] = []
                cfg["extensions"]["add"] = []
                cfg["extensions"]["remove"] = []
                print(color("[OK] Extensions fell back to DEFAULT. Moving on.", GREEN))
                break
            else:
                print(color("Re-enter extensions (CUSTOM only).", DIM))
                continue

        cfg["extensions"]["only"] = sorted(only_set)
        cfg["extensions"]["add"] = []
        cfg["extensions"]["remove"] = []
        print(color("[OK] Extensions configured (CUSTOM mode).", GREEN))
        break

    print()

    # ---------- Chapter 2: Exclude Dirs ----------
    while True:
        print(color("----- Chapter 2: Excluded Directories -----", BOLD))
        _print_set_preview("Default exclude dirs", DEFAULT_EXCLUDE_DIRS)

        use_default = _ask_yes_no(color("Use DEFAULT exclude dirs? (Enter=Yes / n=No) > ", CYAN), default_yes=True)
        if use_default:
            cfg["exclude_dirs"]["mode"] = "default"
            add_raw = _ask(color("Add exclude dirs (comma, empty=skip) > ", BOLD), default="")
            rm_raw = _ask(color("Remove exclude dirs (comma, empty=skip) > ", BOLD), default="")

            add_list = [_normalize_dirname(x) for x in _parse_csv_list(add_raw)]
            rm_list = [_normalize_dirname(x) for x in _parse_csv_list(rm_raw)]
            add_list = [x for x in add_list if x]
            rm_list = [x for x in rm_list if x]

            cfg["exclude_dirs"]["only"] = []
            cfg["exclude_dirs"]["add"] = sorted(set(add_list))
            cfg["exclude_dirs"]["remove"] = sorted(set(rm_list))
            print(color("[OK] Exclude dirs configured (DEFAULT mode).", GREEN))
            break

        # custom
        cfg["exclude_dirs"]["mode"] = "custom"
        only_raw = _ask(color("Select ONLY dirs to exclude (comma). empty=fall back > ", BOLD), default="")
        only_list = [_normalize_dirname(x) for x in _parse_csv_list(only_raw)]
        only_list = [x for x in only_list if x]
        only_set = set(only_list)

        if not only_set:
            print(color("WARNING: CUSTOM mode but 'only' is empty.", YELLOW))
            go_default = _ask_yes_no(color("Proceed with DEFAULT and continue to next chapter? (y/n) > ", CYAN), default_yes=False)
            if go_default:
                cfg["exclude_dirs"]["mode"] = "default"
                cfg["exclude_dirs"]["only"] = []
                cfg["exclude_dirs"]["add"] = []
                cfg["exclude_dirs"]["remove"] = []
                print(color("[OK] Exclude dirs fell back to DEFAULT. Moving on.", GREEN))
                break
            else:
                print(color("Re-enter exclude dirs (CUSTOM only).", DIM))
                continue

        cfg["exclude_dirs"]["only"] = sorted(only_set)
        cfg["exclude_dirs"]["add"] = []
        cfg["exclude_dirs"]["remove"] = []
        print(color("[OK] Exclude dirs configured (CUSTOM mode).", GREEN))
        break

    print()

    # ---------- Summary ----------
    print(color("----- Summary -----", BOLD))
    print(color(f"Extensions mode: {cfg['extensions']['mode']}", CYAN))
    if cfg["extensions"]["mode"] == "default":
        print(color(f"  add: {cfg['extensions']['add']}", DIM))
        print(color(f"  remove: {cfg['extensions']['remove']}", DIM))
    else:
        print(color(f"  only: {cfg['extensions']['only']}", DIM))

    print(color(f"Exclude dirs mode: {cfg['exclude_dirs']['mode']}", CYAN))
    if cfg["exclude_dirs"]["mode"] == "default":
        print(color(f"  add: {cfg['exclude_dirs']['add']}", DIM))
        print(color(f"  remove: {cfg['exclude_dirs']['remove']}", DIM))
    else:
        print(color(f"  only: {cfg['exclude_dirs']['only']}", DIM))

    print()
    return cfg


def _read_json_best_effort(path: str) -> dict | None:
    for enc in ("utf-8", "utf-8-sig", "cp949"):
        try:
            with open(path, "r", encoding=enc) as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                return obj
            return None
        except Exception:
            continue
    return None


# In-process config cache to prevent repeated wizard prompts in the same run
_CFG_CACHE: dict[str, dict] = {}


def ensure_config_or_wizard(rel_root: str) -> dict:
    """
    If config exists & valid -> return it.
    If missing -> run wizard -> save -> return.
    If broken -> backup -> run wizard -> save -> return.
    """
    rel_root = os.path.abspath(os.path.expanduser(rel_root))
    if rel_root in _CFG_CACHE:
        return _CFG_CACHE[rel_root]

    cfg_path = os.path.join(rel_root, CONFIG_FILE)

    if os.path.exists(cfg_path):
        obj = _read_json_best_effort(cfg_path)
        if obj is not None:
            _CFG_CACHE[rel_root] = obj
            return obj

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        bad_path = f"{cfg_path}.bad_{ts}"
        try:
            shutil.move(cfg_path, bad_path)
            print(color(f"[CONFIG] Broken JSON. Backed up -> {bad_path}", YELLOW))
        except Exception:
            print(color("[CONFIG] Broken JSON and backup failed. Continuing.", YELLOW))

        cfg = wizard_config(rel_root)
        atomic_write_json(cfg_path, cfg)
        print(color(f"[CONFIG] Saved -> {cfg_path}", GREEN))
        _CFG_CACHE[rel_root] = cfg
        return cfg

    print(color(f"[CONFIG] {CONFIG_FILE} not found. Running wizard...", CYAN))
    cfg = wizard_config(rel_root)
    try:
        atomic_write_json(cfg_path, cfg)
        print(color(f"[CONFIG] Saved -> {cfg_path}", GREEN))
    except Exception as e:
        print(color(f"[CONFIG] Save failed: {type(e).__name__}. Using in-memory config.", YELLOW))
    _CFG_CACHE[rel_root] = cfg
    return cfg


def _safe_get_list(d: dict, *keys: str) -> list[str]:
    cur = d
    for k in keys[:-1]:
        v = cur.get(k) if isinstance(cur, dict) else None
        if not isinstance(v, dict):
            return []
        cur = v
    last = keys[-1]
    v = cur.get(last) if isinstance(cur, dict) else None
    if isinstance(v, list):
        out: list[str] = []
        for x in v:
            if isinstance(x, str):
                out.append(x)
        return out
    return []


def _safe_get_str(d: dict, *keys: str) -> str | None:
    cur = d
    for k in keys[:-1]:
        v = cur.get(k) if isinstance(cur, dict) else None
        if not isinstance(v, dict):
            return None
        cur = v
    last = keys[-1]
    v = cur.get(last) if isinstance(cur, dict) else None
    return v if isinstance(v, str) else None


def interpret_rules_from_config(cfg: dict) -> tuple[set[str], set[str], str]:
    """
    Interpret config into effective (allowed_exts, exclude_dirs).
    remove wins over add.
    """
    ext_mode = (_safe_get_str(cfg, "extensions", "mode") or "default").lower()
    ext_only = {_normalize_ext(x) for x in _safe_get_list(cfg, "extensions", "only")}
    ext_add = {_normalize_ext(x) for x in _safe_get_list(cfg, "extensions", "add")}
    ext_rm = {_normalize_ext(x) for x in _safe_get_list(cfg, "extensions", "remove")}
    ext_only.discard("")
    ext_add.discard("")
    ext_rm.discard("")

    if ext_mode == "custom":
        base_exts = set(ext_only) if ext_only else set(DEFAULT_ALLOWED_EXTS)
        note = "custom" if ext_only else "custom-only-empty->default"
    else:
        base_exts = set(DEFAULT_ALLOWED_EXTS)
        note = "default"

    base_exts |= ext_add
    base_exts -= ext_rm

    dir_mode = (_safe_get_str(cfg, "exclude_dirs", "mode") or "default").lower()
    dir_only = {_normalize_dirname(x) for x in _safe_get_list(cfg, "exclude_dirs", "only")}
    dir_add = {_normalize_dirname(x) for x in _safe_get_list(cfg, "exclude_dirs", "add")}
    dir_rm = {_normalize_dirname(x) for x in _safe_get_list(cfg, "exclude_dirs", "remove")}
    dir_only.discard("")
    dir_add.discard("")
    dir_rm.discard("")

    if dir_mode == "custom":
        base_dirs = set(dir_only) if dir_only else set(DEFAULT_EXCLUDE_DIRS)
        note += " | exclude:custom" if dir_only else " | exclude:custom-only-empty->default"
    else:
        base_dirs = set(DEFAULT_EXCLUDE_DIRS)
        note += " | exclude:default"

    base_dirs |= dir_add
    base_dirs -= dir_rm

    # HARD ENFORCE: never scan artifact dir nor output bundles dir
    base_dirs.add(ARTIFACT_DIRNAME)
    base_dirs.add(BUNDLES_OUT_DIRNAME)

    return base_exts, base_dirs, note


# =========================
# ✅ Configure-only entry (menu + CLI)
# =========================

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


def ask_yes_no_default(prompt: str, default_yes: bool = False) -> bool:
    """
    y/yes -> True, n/no -> False, empty/other -> default_yes
    """
    try:
        ans = input(prompt).strip().lower()
    except EOFError:
        return default_yes
    if ans in ("y", "yes"):
        return True
    if ans in ("n", "no"):
        return False
    return default_yes


def get_scan_dirs(paths_from_argv: list[str]) -> list[str]:
    r"""
    Decide which directories/files to scan.
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


def run_config_wizard_only(argv: list[str]) -> int:
    """
    Configure rules (.bundlemaker.json) only.
    - use argv path if provided
    - run wizard
    - save config
    """
    print()
    print(color("=============== CONFIG ONLY ===============", BOLD))
    print(color("This will create/overwrite .bundlemaker.json", DIM))

    # argv에서 '-'로 시작하는건 플래그로 보고 제외
    path_args = [a for a in argv if a and not a.startswith("-")]

    scan_dirs_raw = get_scan_dirs(path_args)
    scan_dirs_abs = normalize_base_dirs(scan_dirs_raw)
    rel_root = compute_rel_root(scan_dirs_abs)

    cfg_path = os.path.join(rel_root, CONFIG_FILE)

    if os.path.exists(cfg_path):
        print()
        print(color(f"[CONFIG] Existing config found: {cfg_path}", YELLOW))
        if not ask_yes_no(color("Overwrite it? (y/N) > ", RED), default_no=True):
            print(color("Cancelled. Keeping existing config.", DIM))
            return 0

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup = f"{cfg_path}.bak_{ts}"
        try:
            shutil.copy2(cfg_path, backup)
            print(color(f"[CONFIG] Backup created -> {backup}", DIM))
        except Exception:
            try:
                shutil.copy(cfg_path, backup)
                print(color(f"[CONFIG] Backup created -> {backup}", DIM))
            except Exception:
                print(color("[CONFIG] Backup failed (continuing anyway).", YELLOW))

    cfg = wizard_config(rel_root)
    try:
        atomic_write_json(cfg_path, cfg)
        print()
        print(color(f"[CONFIG] Saved -> {cfg_path}", GREEN))
        _CFG_CACHE[os.path.abspath(os.path.expanduser(rel_root))] = cfg
    except Exception as e:
        print(color(f"[CONFIG] Save failed: {type(e).__name__} :: {e}", RED))
        return 1

    return 0


# =========================
# ✅ STEP 1: bundle 생성용 CLI 파서
# =========================

def parse_mode_and_dirs(argv: list[str]) -> tuple[str, list[str], bool]:
    """
    Parse CLI flags and split mode vs remaining arguments.

    Supported mode flags:
      --auto   / -a
      --paste  / -p
      --hybrid / -h

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
    """
    print()
    print(color("=========== STEP 1: Select Mode ===========", BOLD))
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


def generate_files(base_dirs_abs: list[str], allowed_exts: set[str], exclude_dirs: set[str]) -> list[str]:
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
        return bool(ext) and ext in allowed_exts

    for base_path in base_dirs_abs:
        if not os.path.exists(base_path):
            continue

        if os.path.isfile(base_path):
            if allow_file(base_path):
                rel = os.path.relpath(base_path, rel_root)
                out.add(_to_posix(rel))
            continue

        for cur, dirnames, filenames in os.walk(base_path):
            # enforce excluding dirs (includes .bundlemaker + bundles)
            dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
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
    Stored under .bundlemaker/state/bundle_state.json
    """
    ensure_artifacts(rel_root)
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
    state_path = art_path(rel_root, "state", STATE_BASENAME)
    atomic_write_json(state_path, state)


def load_state(
    files: list[str],
    scan_dirs_abs: list[str],
    rel_root: str,
) -> tuple[list[bool], dict[str, str], int, bool, str] | None:
    """
    Try to restore an existing session state if it matches the current setup.
    Prefers .bundlemaker/state/bundle_state.json
    Falls back to legacy ./bundle_state.json if present.
    """
    ensure_artifacts(rel_root)
    state_path = art_path(rel_root, "state", STATE_BASENAME)
    legacy_state = os.path.join(os.getcwd(), STATE_BASENAME)
    if (not os.path.exists(state_path)) and os.path.exists(legacy_state):
        state_path = legacy_state

    if not os.path.exists(state_path):
        return None

    try:
        with open(state_path, "r", encoding="utf-8") as f:
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
    rel_root: str,
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

    bundle_abs = bundle_out_path(BUNDLE_BASENAME)
    output_rel = _rel_posix_from_cwd(bundle_abs)

    print()
    print(color("=============== STEP 1: Create Bundle ===============", BOLD))
    print(f"Mode: {color(mode_str, CYAN)}{color(override_str, DIM)}")
    print(f"Scanned files: {color(str(total), CYAN)}")
    print(f"Scan roots: {color(' | '.join(scan_dirs_abs), DIM)}")
    print(f"Output: {color(output_rel, CYAN)}")
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


# =========================
# ✅ v2: bundle.txt 파서 + diff/패치용 유틸
# =========================

def parse_bundle_file(bundle_path: str) -> tuple[str, dict[str, str]]:
    """
    bundle.txt 형식을 파싱해서 (rel_root, {path: content}) 반환.
    rel_root가 없으면 현재 디렉토리 사용.
    """
    if not os.path.exists(bundle_path):
        raise FileNotFoundError(bundle_path)

    rel_root: str | None = None
    contents: dict[str, str] = {}

    current_path: str | None = None
    buf: list[str] = []

    with open(bundle_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("=== REL_ROOT:"):
                inner = line.split(":", 1)[1].strip()
                rel_root = _strip_bundle_tail(inner)
                continue

            if line.startswith("=== FILE:"):
                if current_path is not None:
                    contents[current_path] = "".join(buf)
                    buf = []
                inner = line[len("=== FILE:"):].strip()
                inner = _strip_bundle_tail(inner)
                current_path = inner
                continue

            if line.startswith("=== END FILE:"):
                if current_path is not None:
                    contents[current_path] = "".join(buf)
                    buf = []
                    current_path = None
                continue

            if current_path is not None:
                buf.append(line)

    if current_path is not None:
        contents[current_path] = "".join(buf)

    if rel_root is None:
        rel_root = os.getcwd()

    rel_root = os.path.abspath(os.path.expanduser(rel_root))
    return rel_root, contents


def analyze_diff(orig_files: dict[str, str], mod_files: dict[str, str]) -> tuple[list[dict], dict]:
    """
    원본/수정본 파일 맵을 받아서 파일별 diff 요약과 전체 통계를 반환.
    """
    all_paths = set(orig_files.keys()) | set(mod_files.keys())
    per_file: list[dict] = []

    total_changed_files = 0
    total_new = 0
    total_deleted = 0
    total_added_lines = 0
    total_removed_lines = 0

    for path in sorted(all_paths):
        o = orig_files.get(path)
        m = mod_files.get(path)

        if o is None and m is not None:
            new_lines = m.splitlines()
            info = {
                "path": path,
                "kind": "new",
                "orig_lines": 0,
                "mod_lines": len(new_lines),
                "changed_ratio": 1.0,
                "added": len(new_lines),
                "removed": 0,
            }
            total_new += 1
            total_added_lines += len(new_lines)
            per_file.append(info)
            continue

        if o is not None and m is None:
            orig_lines = o.splitlines()
            info = {
                "path": path,
                "kind": "deleted",
                "orig_lines": len(orig_lines),
                "mod_lines": 0,
                "changed_ratio": 1.0,
                "added": 0,
                "removed": len(orig_lines),
            }
            total_deleted += 1
            total_removed_lines += len(orig_lines)
            per_file.append(info)
            continue

        assert o is not None and m is not None
        if o == m:
            info = {
                "path": path,
                "kind": "same",
                "orig_lines": len(o.splitlines()),
                "mod_lines": len(m.splitlines()),
                "changed_ratio": 0.0,
                "added": 0,
                "removed": 0,
            }
            per_file.append(info)
            continue

        orig_lines = o.splitlines()
        mod_lines = m.splitlines()
        sm = difflib.SequenceMatcher(a=orig_lines, b=mod_lines)

        added = 0
        removed = 0
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            removed += (i2 - i1)
            added += (j2 - j1)

        base = max(len(orig_lines), len(mod_lines), 1)
        ratio = (added + removed) / base

        info = {
            "path": path,
            "kind": "changed",
            "orig_lines": len(orig_lines),
            "mod_lines": len(mod_lines),
            "changed_ratio": ratio,
            "added": added,
            "removed": removed,
        }
        per_file.append(info)

        total_changed_files += 1
        total_added_lines += added
        total_removed_lines += removed

    summary = {
        "total_files": len(all_paths),
        "changed_files": total_changed_files,
        "new_files": total_new,
        "deleted_files": total_deleted,
        "total_added_lines": total_added_lines,
        "total_removed_lines": total_removed_lines,
    }
    return per_file, summary


def _read_text_best_effort(abs_path: str) -> tuple[str | None, str]:
    """
    디스크 파일을 텍스트로 읽기(최대한). (verify용)
    """
    try:
        with open(abs_path, "rb") as f:
            data = f.read()
    except Exception as e:
        return None, f"read-failed({type(e).__name__})"

    if b"\x00" in data:
        return None, "binary(NULL)"

    for enc in AUTO_ENCODINGS:
        try:
            return data.decode(enc), f"ok({enc})"
        except Exception:
            continue
    return None, "decode-failed"


def _unique_backup_path(backup_root: str, rel_posix_path: str) -> str:
    """
    backup_root 아래에 rel_posix_path 구조로 백업 경로를 만들되,
    이미 있으면 suffix를 붙여 충돌을 회피한다.
    """
    base = os.path.join(backup_root, _from_posix(rel_posix_path))
    os.makedirs(os.path.dirname(base) or ".", exist_ok=True)

    if not os.path.exists(base):
        return base

    stem, ext = os.path.splitext(base)
    # 충돌 회피: .dup_0001 같은 suffix
    for i in range(1, 10_000):
        cand = f"{stem}.dup_{i:04d}{ext}"
        if not os.path.exists(cand):
            return cand

    # 최후 수단
    cand = f"{stem}.dup_{datetime.now().strftime('%H%M%S_%f')}{ext}"
    return cand

def _unique_safety_abs_path(base_abs: str) -> str:
    """
    base_abs가 이미 존재하면 .dup_0001 같은 suffix로 충돌 회피한 새 경로를 만든다.
    (restore safety 용)
    """
    if not os.path.exists(base_abs):
        return base_abs

    stem, ext = os.path.splitext(base_abs)
    for i in range(1, 10_000):
        cand = f"{stem}.dup_{i:04d}{ext}"
        if not os.path.exists(cand):
            return cand
    return f"{stem}.dup_{datetime.now().strftime('%H%M%S_%f')}{ext}"


def _move_overwrite_with_safety(src_abs: str, dst_abs: str, ts_restore: str) -> tuple[bool, str | None]:
    """
    Windows 포함 안전 overwrite restore:
    - dst가 있으면 safety로 'move' 우선 (디스크 절약 + 덮어쓰기 확보)
    - move 실패하면 safety로 copy 후 dst 제거 시도
    - 마지막에 src -> dst는 os.replace 우선(가능하면 원자적)
    반환: (success, safety_path_or_None)
    """
    safety_path = None
    moved_dst_out = False

    # 1) dst exists -> move it out (preferred) or copy+remove
    if os.path.exists(dst_abs):
        safety_path = _unique_safety_abs_path(f"{dst_abs}{RESTORE_SAFETY_SUFFIX}{ts_restore}")
        try:
            os.makedirs(os.path.dirname(safety_path) or ".", exist_ok=True)
        except Exception:
            pass

        # try move-out first
        try:
            shutil.move(dst_abs, safety_path)
            moved_dst_out = True
        except Exception:
            # fallback: copy then remove
            copied = False
            try:
                shutil.copy2(dst_abs, safety_path)
                copied = True
            except Exception:
                try:
                    shutil.copy(dst_abs, safety_path)
                    copied = True
                except Exception:
                    copied = False

            # remove dst so overwrite is possible
            if copied:
                try:
                    os.remove(dst_abs)
                except Exception:
                    # couldn't clear destination -> fail
                    return False, safety_path
            else:
                return False, None

    # 2) now put src into dst (prefer os.replace)
    try:
        os.makedirs(os.path.dirname(dst_abs) or ".", exist_ok=True)
    except Exception:
        pass

    try:
        os.replace(src_abs, dst_abs)  # overwrites if exists (Windows OK)
        return True, safety_path
    except Exception:
        try:
            shutil.move(src_abs, dst_abs)
            return True, safety_path
        except Exception:
            # rollback dst if we moved it out
            if moved_dst_out and safety_path and os.path.exists(safety_path) and (not os.path.exists(dst_abs)):
                try:
                    shutil.move(safety_path, dst_abs)
                except Exception:
                    pass
            return False, safety_path



def apply_patches(
    rel_root: str,
    per_file: list[dict],
    orig_files: dict[str, str],
    mod_files: dict[str, str],
    strategy: str,
    pre_hashes: dict[str, str | None],
    deleted_snapshots: dict[str, str],
    big_change_threshold: float = 0.3,
) -> dict:
    """
    strategy:
      "safe"  -> 작은 변경만 자동 적용 (비율 <= big_change_threshold, 삭제는 적용 X)
      "full"  -> 모든 변경 적용 (삭제 포함)

    returns manifest dict (for restore/verify)
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    ensure_artifacts(rel_root)
    backup_root = os.path.join(_art_dir(rel_root, "backups"), ts)
    os.makedirs(backup_root, exist_ok=True)

    print()
    print(color(f"Applying patches (strategy={strategy}, rel_root={rel_root})", BOLD))

    big_candidates: list[dict] = []
    applied: list[str] = []
    skipped: list[str] = []
    deleted_applied: list[str] = []
    created_files: list[str] = []

    # rel_path -> bak_rel_path (posix)
    backup_map: dict[str, str] = {}

    for info in per_file:
        path = info["path"]
        kind = info["kind"]
        ratio = info["changed_ratio"]

        if kind == "same":
            continue

        # SAFE mode rules
        if strategy == "safe" and kind == "changed" and ratio > big_change_threshold:
            big_candidates.append(info)
            skipped.append(path)
            print(color(f"[SKIP-BIG] {path} (changed_ratio={ratio:.2f})", YELLOW))
            continue

        if strategy == "safe" and kind == "deleted":
            skipped.append(path)
            print(color(f"[SKIP-DEL] {path} (deleted, safe mode)", YELLOW))
            continue

        target = os.path.join(rel_root, _from_posix(path))
        if not _is_within_root(rel_root, target):
            skipped.append(path)
            print(color(f"[BLOCKED] {path} (path traversal?)", RED))
            continue

        # changed/new는 디렉토리 필요
        if kind in ("changed", "new"):
            dirname = os.path.dirname(target) or "."
            if not os.path.exists(dirname):
                os.makedirs(dirname, exist_ok=True)

        # -------------------------
        # ✅ BACKUP + APPLY
        # -------------------------

        if kind in ("changed", "new"):
            # 1) 기존 파일이면 copy 백업
            if os.path.exists(target):
                backup_path = _unique_backup_path(backup_root, path)
                try:
                    shutil.copy2(target, backup_path)
                except Exception:
                    try:
                        shutil.copy(target, backup_path)
                    except Exception:
                        backup_path = None

                if backup_path and os.path.exists(backup_path):
                    rel_bak = _rel_posix_from_abs(rel_root, backup_path)
                    backup_map[path] = rel_bak

            # 2) new 파일 생성 기록 (정확)
            if kind == "new" and (not os.path.exists(target)):
                created_files.append(path)

            # 3) write
            new_body = mod_files.get(path, "")
            atomic_write_text(target, new_body, encoding="utf-8")
            applied.append(path)

            bak = backup_map.get(path)
            if bak:
                print(color(f"[OK] {path} (backup: {bak})", GREEN))
            else:
                print(color(f"[OK] {path}", GREEN))
            continue

        if kind == "deleted" and strategy == "full":
            # ✅ 치명 버그 수정 포인트:
            # deleted(full)는 copy 백업을 절대 하지 않고
            # move 한 번으로 "백업 + 삭제"를 처리한다.
            if os.path.exists(target):
                backup_path = _unique_backup_path(backup_root, path)
                try:
                    shutil.move(target, backup_path)
                    deleted_applied.append(path)

                    rel_bak = _rel_posix_from_abs(rel_root, backup_path)
                    backup_map[path] = rel_bak  # 실제 저장 경로 기록
                    print(color(f"[DEL] {path} -> backup: {rel_bak}", YELLOW))
                except Exception as e:
                    print(color(f"[ERR-DEL] {path} :: {type(e).__name__}", RED))
                    skipped.append(path)
            else:
                print(color(f"[DEL-SKIP] {path} (file not found on disk)", DIM))
            continue

        # 나머지(예: deleted인데 safe라 여기 못 옴)는 그냥 skip 처리
        skipped.append(path)
        print(color(f"[SKIP] {path} (unhandled kind={kind})", YELLOW))

    print()
    print(color("Patch result:", BOLD))
    print(f"  Applied files: {len(applied)}")
    print(f"  Created files: {len(created_files)}")
    print(f"  Deleted files (full mode): {len(deleted_applied)}")
    print(f"  Skipped files: {len(skipped)}")

    if big_candidates:
        report_path = art_path(rel_root, "reports", "bundle_patch_big_changes.txt")
        lines: list[str] = []
        lines.append("# BIG changes (not auto-applied in SAFE mode)\n")
        for info in big_candidates:
            lines.append(
                f"- {info['path']} :: ratio={info['changed_ratio']:.2f}, "
                f"+{info['added']} / -{info['removed']}\n"
            )
        atomic_write_text(report_path, "".join(lines), encoding="utf-8")
        print(color(f"Big change candidates listed in {_rel_posix_from_abs(rel_root, report_path)}", YELLOW))

    manifest = {
        "ts": ts,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rel_root": rel_root,
        "strategy": strategy,
        "big_change_threshold": big_change_threshold,
        "applied": applied,
        "created_files": created_files,
        "deleted_applied": deleted_applied,
        "skipped": skipped,
        "backup_map": backup_map,

        "pre_hashes": pre_hashes,
        "deleted_snapshots": deleted_snapshots,
    }
    manifest_path = art_path(rel_root, "manifests", f"{MANIFEST_PREFIX}{ts}{MANIFEST_EXT}")
    atomic_write_json(manifest_path, manifest)
    print(color(f"[MANIFEST] Saved -> {_rel_posix_from_abs(rel_root, manifest_path)}", DIM))

    return manifest


# =========================
# ✅ VERIFY (after patch)
# =========================

def verify_disk_against_modified(rel_root: str, manifest: dict, mod_files: dict[str, str], ts: str) -> tuple[dict, str]:
    """
    VERIFY-A) modified bundle 내용 vs 실제 디스크 파일 (MANIFEST-BASED)

    - applied: 디스크 내용 == mod_files[path] 이어야 OK
    - deleted_applied: 디스크에 없어야 OK
    - skipped: EXPECTED_SKIP로만 기록 (mismatch로 치지 않음)
    """
    applied = manifest.get("applied")
    if not isinstance(applied, list):
        applied = []
    deleted_applied = manifest.get("deleted_applied")
    if not isinstance(deleted_applied, list):
        deleted_applied = []
    skipped = manifest.get("skipped")
    if not isinstance(skipped, list):
        skipped = []

    ok = 0
    mismatch = 0
    missing = 0
    unread = 0
    blocked = 0
    expected_skip = 0

    lines: list[str] = []
    lines.append(f"# VERIFY DISK REPORT (MANIFEST) @ {datetime.now().isoformat(timespec='seconds')}\n")
    lines.append(f"REL_ROOT: {rel_root}\n\n")

    # ---- Applied files: must match mod_files ----
    lines.append("---- APPLIED (must match modified bundle) ----\n")
    for path in applied:
        if not isinstance(path, str):
            continue

        abs_target = os.path.join(rel_root, _from_posix(path))
        if not _is_within_root(rel_root, abs_target):
            blocked += 1
            lines.append(f"BLOCKED  {path}\n")
            continue

        if not os.path.exists(abs_target):
            missing += 1
            lines.append(f"MISSING  {path} :: not found on disk\n")
            continue

        disk_text, why = _read_text_best_effort(abs_target)
        if disk_text is None:
            unread += 1
            lines.append(f"UNREAD   {path} :: {why}\n")
            continue

        expected = mod_files.get(path, "")
        if disk_text == expected:
            ok += 1
            lines.append(f"OK       {path}\n")
        else:
            mismatch += 1
            lines.append(f"MISMATCH {path} :: disk != modified_bundle\n")

    # ---- Deleted-applied: must NOT exist ----
    lines.append("\n---- DELETED_APPLIED (must be absent) ----\n")
    for path in deleted_applied:
        if not isinstance(path, str):
            continue

        abs_target = os.path.join(rel_root, _from_posix(path))
        if not _is_within_root(rel_root, abs_target):
            blocked += 1
            lines.append(f"BLOCKED  {path}\n")
            continue

        if os.path.exists(abs_target):
            mismatch += 1
            lines.append(f"MISMATCH {path} :: expected deleted but exists\n")
        else:
            ok += 1
            lines.append(f"OK       {path} :: deleted\n")

    # ---- Skipped: expected skip ----
    lines.append("\n---- SKIPPED (expected) ----\n")
    for path in skipped:
        if not isinstance(path, str):
            continue
        expected_skip += 1
        lines.append(f"EXPECTED_SKIP {path}\n")

    summary = {
        "ok": ok,
        "mismatch": mismatch,
        "missing": missing,
        "unread": unread,
        "blocked": blocked,
        "expected_skip": expected_skip,
        "checked_applied": len([x for x in applied if isinstance(x, str)]),
        "checked_deleted_applied": len([x for x in deleted_applied if isinstance(x, str)]),
    }

    report_path = art_path(rel_root, "reports", f"{VERIFY_REPORT_PREFIX}{ts}.txt")
    lines.append("\n---- SUMMARY ----\n")
    for k, v in summary.items():
        lines.append(f"{k}: {v}\n")

    atomic_write_text(report_path, "".join(lines), encoding="utf-8")
    return summary, report_path



def _load_scan_dirs_from_state_if_possible(rel_root: str) -> tuple[list[str] | None, str | None]:
    """
    STEP1에서 쓴 scan_dirs_abs / rel_root를 STATE_FILE에서 뽑아오면
    patch 후 재번들 검증을 '같은 경로'로 할 수 있음.
    """
    ensure_artifacts(rel_root)
    state_path = art_path(rel_root, "state", STATE_BASENAME)
    legacy_state = os.path.join(os.getcwd(), STATE_BASENAME)

    use_path = None
    if os.path.exists(state_path):
        use_path = state_path
    elif os.path.exists(legacy_state):
        use_path = legacy_state
    else:
        return None, None

    try:
        with open(use_path, "r", encoding="utf-8") as f:
            st = json.load(f)
        scan_dirs_abs = st.get("scan_dirs_abs")
        st_rel_root = st.get("rel_root")
        if isinstance(scan_dirs_abs, list) and all(isinstance(x, str) for x in scan_dirs_abs):
            scan_dirs_abs = [os.path.abspath(x) for x in scan_dirs_abs]
        else:
            scan_dirs_abs = None
        if not isinstance(st_rel_root, str):
            st_rel_root = None
        return scan_dirs_abs, st_rel_root
    except Exception:
        return None, None


def rebuild_bundle_for_verify(
    rel_root: str,
    scan_dirs_abs: list[str] | None,
    cfg: dict,
    ts: str
) -> tuple[str, dict[str, str], dict[str, str]]:
    """
    검증 B) 적용된 프로젝트를 다시 스캔해서 번들 생성
    - (out_bundle_path, applied_map, skipped_map) 반환
    """
    allowed_exts, exclude_dirs, note = interpret_rules_from_config(cfg)

    if scan_dirs_abs is None or not scan_dirs_abs:
        scan_dirs_abs = [rel_root]

    files = generate_files(scan_dirs_abs, allowed_exts=allowed_exts, exclude_dirs=exclude_dirs)

    contents: dict[str, str] = {}
    skipped: dict[str, str] = {}

    for i, p in enumerate(files, start=1):
        c, why = auto_read_file(rel_root, p)
        if c is None:
            skipped[p] = why
            continue
        contents[p] = c

        if i % 80 == 0:
            print(color(f"[REBUNDLE] reading... {i}/{len(files)}", DIM))

    out_name = bundle_out_path(f"{REBUNDLE_NAME_PREFIX}{ts}.txt")
    bundle_text = build_bundle_text(rel_root, files, contents, skipped)
    atomic_write_text(out_name, bundle_text, encoding="utf-8")

    print(color(f"[REBUNDLE] created -> {_rel_posix_from_cwd(out_name)} (included {len(contents)}/{len(files)})", DIM))
    return out_name, contents, skipped



def compare_modified_vs_applied(
    rel_root: str,
    manifest: dict,
    mod_files: dict[str, str],
    applied_files: dict[str, str],
    rebundle_skipped: dict[str, str],
    ts: str
) -> tuple[dict, str]:
    """
    VERIFY-B) modified bundle vs rebundled scan (MANIFEST-BASED)

    - 검사 대상 = manifest["applied"] 만
    - 재번들에서 파일을 못 읽은 경우(rebundle_skipped)는 expected_unread로 분리
    """
    applied = manifest.get("applied")
    if not isinstance(applied, list):
        applied = []

    ok = 0
    mismatch = 0
    missing_in_applied = 0
    expected_unread = 0
    checked = 0

    lines: list[str] = []
    lines.append(f"# REBUNDLE COMPARE (MANIFEST) @ {datetime.now().isoformat(timespec='seconds')}\n\n")

    for path in applied:
        if not isinstance(path, str):
            continue
        checked += 1

        # modified bundle must have content for applied path (normally true)
        expected = mod_files.get(path, None)
        if expected is None:
            # weird: applied but not in mod_files
            mismatch += 1
            lines.append(f"MISMATCH {path} :: missing in modified bundle\n")
            continue

        if path not in applied_files:
            # if rebundle skipped reading it, don't call it a mismatch
            if path in rebundle_skipped:
                expected_unread += 1
                lines.append(f"UNREAD   {path} :: rebundle skipped ({rebundle_skipped.get(path)})\n")
            else:
                missing_in_applied += 1
                lines.append(f"MISSING  {path} :: not present in applied scan\n")
            continue

        if applied_files[path] == expected:
            ok += 1
            lines.append(f"OK       {path}\n")
        else:
            mismatch += 1
            lines.append(f"MISMATCH {path}\n")

    summary = {
        "ok": ok,
        "mismatch": mismatch,
        "missing_in_applied": missing_in_applied,
        "expected_unread": expected_unread,
        "checked_files": checked,
    }

    report_path = art_path(rel_root, "reports", f"{REBUNDLE_REPORT_PREFIX}{ts}.txt")
    lines.append("\n---- SUMMARY ----\n")
    for k, v in summary.items():
        lines.append(f"{k}: {v}\n")

    atomic_write_text(report_path, "".join(lines), encoding="utf-8")
    return summary, report_path



# =========================
# ✅ RESTORE (rollback) + RESTORE-VERIFY
# =========================

def list_manifests(rel_root: str) -> list[str]:
    ensure_artifacts(rel_root)
    mdir = _art_dir(rel_root, "manifests")
    out = []
    try:
        for fn in os.listdir(mdir):
            if fn.startswith(MANIFEST_PREFIX) and fn.endswith(MANIFEST_EXT):
                out.append(os.path.join(mdir, fn))
    except Exception:
        return []
    return sorted(out)


def load_manifest(path: str) -> dict | None:
    obj = _read_json_best_effort(path)
    return obj if isinstance(obj, dict) else None


def _restore_verify(rel_root: str, mf: dict, ts_restore: str) -> tuple[dict, str]:
    """
    Verify rollback by comparing pre_hashes vs post restore disk hashes.
    Also checks created_files are gone (or moved).
    """
    pre_hashes = mf.get("pre_hashes")
    if not isinstance(pre_hashes, dict):
        pre_hashes = {}

    created_files = mf.get("created_files")
    if not isinstance(created_files, list):
        created_files = []

    ok = 0
    mismatch = 0
    blocked = 0
    skipped = 0
    created_left = 0

    lines: list[str] = []
    lines.append(f"# RESTORE VERIFY REPORT @ {datetime.now().isoformat(timespec='seconds')}\n")
    lines.append(f"REL_ROOT: {rel_root}\n\n")

    # hash verify
    for rel_posix_path, pre_h in pre_hashes.items():
        if not isinstance(rel_posix_path, str):
            continue

        abs_target = os.path.join(rel_root, _from_posix(rel_posix_path))
        if not _is_within_root(rel_root, abs_target):
            blocked += 1
            lines.append(f"BLOCKED  {rel_posix_path}\n")
            continue

        if pre_h is None:
            # file was missing/unhashable before patch; can't strictly verify
            skipped += 1
            lines.append(f"SKIP     {rel_posix_path} :: pre_hash=None\n")
            continue

        post_h = _sha256_file(abs_target) if os.path.exists(abs_target) else None
        if post_h == pre_h:
            ok += 1
            lines.append(f"OK       {rel_posix_path}\n")
        else:
            mismatch += 1
            lines.append(f"MISMATCH {rel_posix_path} :: pre != post\n")

    # created files should be gone at original location
    for rel_posix_path in created_files:
        if not isinstance(rel_posix_path, str):
            continue
        abs_target = os.path.join(rel_root, _from_posix(rel_posix_path))
        if not _is_within_root(rel_root, abs_target):
            blocked += 1
            lines.append(f"BLOCKED  {rel_posix_path} (created)\n")
            continue
        if os.path.exists(abs_target):
            created_left += 1
            lines.append(f"MISMATCH {rel_posix_path} :: created file still exists\n")
        else:
            ok += 1
            lines.append(f"OK       {rel_posix_path} :: created removed/quarantined\n")

    summary = {
        "ok": ok,
        "mismatch": mismatch,
        "blocked": blocked,
        "skipped": skipped,
        "created_left": created_left,
    }

    report_path = art_path(rel_root, "reports", f"{RESTORE_VERIFY_REPORT_PREFIX}{ts_restore}.txt")
    lines.append("\n---- SUMMARY ----\n")
    for k, v in summary.items():
        lines.append(f"{k}: {v}\n")

    atomic_write_text(report_path, "".join(lines), encoding="utf-8")
    return summary, report_path

def _safe_remove_file(path: str) -> bool:
    """Windows 포함: 읽기전용/권한 꼬임 대비해서 삭제 시도"""
    try:
        if os.path.exists(path):
            try:
                os.chmod(path, 0o666)
            except Exception:
                pass
            os.remove(path)
        return True
    except Exception:
        return False



def restore_from_manifest(manifest_path: str) -> int:
    mf = load_manifest(manifest_path)
    if not mf:
        print(color(f"[RESTORE] Bad manifest: {manifest_path}", RED))
        return 1

    rel_root = mf.get("rel_root") or os.getcwd()
    rel_root = os.path.abspath(os.path.expanduser(rel_root))
    ensure_artifacts(rel_root)

    backup_map = mf.get("backup_map")
    if not isinstance(backup_map, dict) or not backup_map:
        backup_map = {}

    created_files = mf.get("created_files")
    if not isinstance(created_files, list):
        created_files = []

    deleted_snapshots = mf.get("deleted_snapshots")
    if not isinstance(deleted_snapshots, dict):
        deleted_snapshots = {}

    pre_hashes = mf.get("pre_hashes")
    if not isinstance(pre_hashes, dict):
        pre_hashes = {}

    # ✅ FIX #1: restore가 backup_map 없다고 거부하면 안 됨
    # - created_files만 있거나 deleted_snapshots만 있어도 restore 가능해야 한다.
    if (not backup_map) and (not created_files) and (not deleted_snapshots):
        print(color("[RESTORE] Nothing to restore (backup_map/created_files/deleted_snapshots all empty).", YELLOW))
        return 1

    ts_restore = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    print()
    print(color("=============== RESTORE ===============", BOLD))
    print(color(f"Manifest: {manifest_path}", DIM))
    print(color(f"REL_ROOT: {rel_root}", DIM))
    print(color(f"Backups: {len(backup_map)} files", CYAN))
    print(color(f"Created files recorded: {len(created_files)}", CYAN))
    print(color(f"Deleted snapshots: {len(deleted_snapshots)}", CYAN))

    if not ask_yes_no(color("Proceed restore? (y/N) > ", RED), default_no=True):
        print(color("Cancelled.", DIM))
        return 0
    
    # (선택) 백업을 “보존(copy)”할지 “소모(move)”할지
    # - 기본은 move (디스크 절약)
    keep_backups = ask_yes_no_default(
        color("Keep backups after restore? (Enter=No(move) / y=Yes(copy)) > ", CYAN),
        default_yes=False
     )

    # handle created files (quarantine by default)
    do_quarantine = True
    if created_files:
        do_quarantine = ask_yes_no_default(
            color("Quarantine created files (recommended)? (Enter=Yes / n=No) > ", CYAN),
            default_yes=True
        )

    quarantine_dir = None
    if do_quarantine and created_files:
        quarantine_dir = os.path.join(_art_dir(rel_root, "quarantine"), f"created_{ts_restore}")
        os.makedirs(quarantine_dir, exist_ok=True)

    q_ok = 0
    q_fail = 0
    q_blocked = 0

    if do_quarantine and created_files and quarantine_dir:
        print()
        print(color("[RESTORE] Handling created files...", BOLD))
        for rel_posix_path in created_files:
            if not isinstance(rel_posix_path, str):
                continue
            abs_target = os.path.join(rel_root, _from_posix(rel_posix_path))
            if not _is_within_root(rel_root, abs_target):
                q_blocked += 1
                print(color(f"[BLOCKED] {rel_posix_path} (created)", RED))
                continue
            if not os.path.exists(abs_target):
                continue
            try:
                # ✅ FIX #3: 폴더 구조 유지 (quarantine 안에서 상대경로 그대로)
                dst = os.path.join(quarantine_dir, _from_posix(rel_posix_path))
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                # 충돌 회피
                if os.path.exists(dst):
                    dst = _unique_safety_abs_path(dst + f".dup_{datetime.now().strftime('%H%M%S_%f')}")
                shutil.move(abs_target, dst)
                print(color(f"[QUARANTINED] {rel_posix_path} -> {_rel_posix_from_abs(rel_root, dst)}", DIM))
                q_ok += 1
            except Exception as e:
                print(color(f"[Q-ERR] {rel_posix_path} :: {type(e).__name__}", YELLOW))
                q_fail += 1

        print(color(f"[RESTORE] Created quarantine result: OK={q_ok}, FAIL={q_fail}, BLOCKED={q_blocked}", DIM))

    ok = 0
    fail = 0
    blocked = 0
    missing_bak = 0

    print()
    print(color("[RESTORE] Restoring backups...", BOLD))

    for rel_posix_path, bak_rel_posix in backup_map.items():
        target = os.path.join(rel_root, _from_posix(rel_posix_path))
        bak_abs = os.path.join(rel_root, _from_posix(bak_rel_posix))

        if not _is_within_root(rel_root, target) or not _is_within_root(rel_root, bak_abs):
            print(color(f"[BLOCKED] Path escapes root: {rel_posix_path}", RED))
            blocked += 1
            continue

        if not os.path.exists(bak_abs):
            print(color(f"[MISSING-BAK] {bak_rel_posix}", YELLOW))
            missing_bak += 1
            continue

       
        # ✅ FIX #2: restore에서 safety copy로 디스크 쌓지 말고
        # _move_overwrite_with_safety로 "기존 dst -> safety(move/copy) + bak -> dst" 한 방 처리.
        src_for_restore = bak_abs
        tmp_copy = None
        if keep_backups:
            # 백업 보존: bak_abs는 그대로 두고 임시 복사본을 src로 사용
            tmp_copy = f"{bak_abs}.tmp_restore_{ts_restore}"
            try:
                shutil.copy2(bak_abs, tmp_copy)
            except Exception:
                try:
                    shutil.copy(bak_abs, tmp_copy)
                except Exception:
                    tmp_copy = None
            if tmp_copy is None or not os.path.exists(tmp_copy):
                print(color(f"[ERR] {rel_posix_path} :: cannot copy backup for keep-backups", RED))
                fail += 1
                continue
            src_for_restore = tmp_copy

        success, safety_path = _move_overwrite_with_safety(src_for_restore, target, ts_restore)
        if success:
            if safety_path:
                print(color(f"[RESTORED] {rel_posix_path} (dst safety -> {_rel_posix_from_abs(rel_root, safety_path)})", GREEN))
            else:
                print(color(f"[RESTORED] {rel_posix_path}", GREEN))
            ok += 1
        else:
            print(color(f"[ERR] {rel_posix_path} :: restore failed (Windows lock?)", RED))
            fail += 1

        # cleanup tmp copy if used
        if tmp_copy and os.path.exists(tmp_copy):
            _safe_remove_file(tmp_copy)


    # restore deleted snapshots when needed (full-mode deletes)
    print()
    print(color("[RESTORE] Recovering deleted files from snapshots (if needed)...", BOLD))

    snap_ok = 0
    snap_skip = 0
    snap_blocked = 0
    snap_fail = 0

    for rel_posix_path, body in deleted_snapshots.items():
        if not isinstance(rel_posix_path, str) or not isinstance(body, str):
            continue

        # Only recreate if it existed pre-patch (pre_hash is not None)
        if pre_hashes.get(rel_posix_path, None) is None:
            snap_skip += 1
            continue

        abs_target = os.path.join(rel_root, _from_posix(rel_posix_path))
        if not _is_within_root(rel_root, abs_target):
            snap_blocked += 1
            continue

        if os.path.exists(abs_target):
            # already restored by backup_map move-back
            snap_skip += 1
            continue

        try:
            os.makedirs(os.path.dirname(abs_target) or ".", exist_ok=True)
            atomic_write_text(abs_target, body, encoding="utf-8")
            print(color(f"[SNAP-RESTORED] {rel_posix_path}", GREEN))
            snap_ok += 1
        except Exception as e:
            print(color(f"[SNAP-ERR] {rel_posix_path} :: {type(e).__name__}", YELLOW))
            snap_fail += 1

    print(color(f"[RESTORE] Snapshot restore: OK={snap_ok}, SKIP={snap_skip}, BLOCKED={snap_blocked}, FAIL={snap_fail}", DIM))

    print()
    print(color("Restore result:", BOLD))
    print(f"  OK:         {ok}")
    print(f"  FAIL:       {fail}")
    print(f"  BLOCKED:    {blocked}")
    print(f"  MISSING_BAK:{missing_bak}")

    # restore verify
    print()
    print(color("[RESTORE-VERIFY] Hash check (prove it).", BOLD))
    v_sum, v_report = _restore_verify(rel_root, mf, ts_restore)
    print(f"  OK: {v_sum['ok']}, MISMATCH: {v_sum['mismatch']}, BLOCKED: {v_sum['blocked']}, SKIPPED: {v_sum['skipped']}, CREATED_LEFT: {v_sum['created_left']}")
    print(color(f"  Report -> {_rel_posix_from_abs(rel_root, v_report)}", DIM))

    if v_sum["mismatch"] == 0 and v_sum["created_left"] == 0 and v_sum["blocked"] == 0:
        print(color("ROLLBACK VERIFIED.", GREEN))
        return 0
    else:
        print(color("WARNING: ROLLBACK NOT CLEAN. Check report.", YELLOW))
        return 1


def run_restore_menu() -> int:
    print()
    print(color("=============== RESTORE MENU ===============", BOLD))

    try:
        root_in = input(color("Project root for restore (Enter=.) > ", BOLD)).strip()
    except EOFError:
        root_in = ""
    if not root_in:
        root_in = "."
    rel_root = os.path.abspath(os.path.expanduser(_strip_wrapping_quotes(root_in)))

    mfs = list_manifests(rel_root)
    if not mfs:
        print(color("No manifest files found.", YELLOW))
        print(color("Tip: run STEP 3 patch at least once (manifest is saved under .bundlemaker/manifests).", DIM))
        return 1

    print(color("Available manifests:", CYAN))
    for i, fn in enumerate(mfs):
        print(f" {i:>2} : {_to_posix(os.path.relpath(fn, rel_root))}")

    try:
        s = input(color("Select index (Enter=0, q=cancel) > ", BOLD)).strip().lower()
    except EOFError:
        s = ""

    if s == "q":
        print(color("Cancelled.", DIM))
        return 0
    if s == "":
        idx = 0
    else:
        if not s.isdigit():
            print(color("Invalid input.", RED))
            return 1
        idx = int(s)

    if idx < 0 or idx >= len(mfs):
        print(color("Index out of range.", RED))
        return 1

    return restore_from_manifest(mfs[idx])


# =========================
# ✅ STEP 1 구현
# =========================

def run_step1_bundle(argv: list[str]) -> int:
    mode, rest_paths, mode_forced = parse_mode_and_dirs(argv)
    if not mode_forced:
        mode = select_mode_before_path(default=MODE_HYBRID)

    scan_dirs_raw = get_scan_dirs(rest_paths)
    scan_dirs_abs = normalize_base_dirs(scan_dirs_raw)
    rel_root = compute_rel_root(scan_dirs_abs)
    ensure_artifacts(rel_root)

    # ✅ Wizard-based config (missing/broken -> wizard)
    cfg = ensure_config_or_wizard(rel_root)
    allowed_exts, exclude_dirs, note = interpret_rules_from_config(cfg)
    print(color(f"[RULES] {note}", DIM))

    files = generate_files(scan_dirs_abs, allowed_exts=allowed_exts, exclude_dirs=exclude_dirs)
    if not files:
        print(color("No files found to scan.", RED))
        print(color("Check:", YELLOW), "paths / extensions / exclude dirs in .bundlemaker.json")
        print(color("Scan roots:", DIM), scan_dirs_abs)
        return 1

    # AUTO 모드: 비인터랙티브
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

            if i % 80 == 0:
                print(color(f"Reading... {i}/{len(files)}", DIM))

        bundle_abs = bundle_out_path(BUNDLE_BASENAME)
        bundle_text = build_bundle_text(rel_root, files, contents, skipped)
        atomic_write_text(bundle_abs, bundle_text, encoding="utf-8")

        # state도 같이 저장(패치 단계에서 재번들 검증 시 재사용)
        done = [p in contents for p in files]
        save_state(files, scan_dirs_abs, rel_root, done, contents, cursor=-1, show_remaining_only=False, mode=mode)

        print()
        print(color(f"[STEP 1 DONE] Created: {_rel_posix_from_cwd(bundle_abs)} | Included: {len(contents)}/{len(files)}", BOLD))
        if skipped:
            print(color("Skipped files:", YELLOW))
            for p, why in sorted(skipped.items()):
                print(" -", p, "::", why)
        else:
            print(color("No skipped files. Clean.", GREEN))

        print()
        print(color("NEXT (STEP 2):", CYAN), f"Send {_rel_posix_from_cwd(bundle_abs)} to your LLM, get modified bundle, save as bundle_modified.txt")
        print(color("When you're done, you can run STEP 3 to apply patches.", CYAN))

        if ask_yes_no(color("Run STEP 3 now after you prepare bundle_modified.txt? (y/N) > ", CYAN), default_no=True):
            return run_step3_patch()

        return 0

    # INTERACTIVE (HYBRID/PASTE)
    done = [False] * len(files)
    show_remaining_only = False
    contents: dict[str, str] = {}
    cursor = -1
    next_action_override: str | None = None

    loaded = load_state(files, scan_dirs_abs, rel_root)
    if loaded is not None:
        done, contents, cursor, show_remaining_only, saved_mode = loaded
        mode = saved_mode
        print(color("Bundle Maker resume: existing state loaded.", BOLD))
        print("Resumed. Let's keep going.\n")
    else:
        print(color("Bundle Maker started (STEP 1).", BOLD))
        print("Workflow start.\n")

    try:
        while True:
            print_screen(files, done, show_remaining_only, cursor, scan_dirs_abs, mode, next_action_override, rel_root)
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
                ok_ovr = ask_yes_no(
                    color(f"\n[{path}] is already done. Overwrite it? (y/N) > ", YELLOW),
                    default_no=True,
                )
                if not ok_ovr:
                    print(color("Cancelled.", DIM))
                    continue

            if action is None:
                if next_action_override is not None:
                    action = next_action_override
                else:
                    action = "p" if mode == MODE_PASTE else "a"
            next_action_override = None

            if action == "a":
                content, why = auto_read_file(rel_root, path)
                if content is None:
                    print()
                    print(color(f"[{path}] AUTO-READ failed/skipped: {why}", YELLOW))
                    if mode == MODE_HYBRID:
                        if ask_yes_no(color("Switch to PASTE mode for this file? (y/N) > ", CYAN), default_no=True):
                            content = capture_section(path, idx, len(files))
                        else:
                            print(color("Skipped. Move on.", DIM))
                            continue
                    else:
                        continue
                contents[path] = content
                done[idx] = True
                cursor = idx
                print(color(f"\n[{path}] AUTO-READ complete.", GREEN))
            else:
                content = capture_section(path, idx, len(files))
                contents[path] = content
                done[idx] = True
                cursor = idx
                print(color(f"\n[{path}] PASTE capture complete.", GREEN))

            save_state(files, scan_dirs_abs, rel_root, done, contents, cursor, show_remaining_only, mode)
            print(color(f"(autosaved -> {_rel_posix_from_abs(rel_root, art_path(rel_root, 'state', STATE_BASENAME))})", DIM))

    except KeyboardInterrupt:
        print()
        print(color("KeyboardInterrupt detected. Saving state and exiting.", YELLOW))
        save_state(files, scan_dirs_abs, rel_root, done, contents, cursor, show_remaining_only, mode)

    bundle_abs = bundle_out_path(BUNDLE_BASENAME)
    bundle_text = build_bundle_text(rel_root, files, contents, skipped={})
    atomic_write_text(bundle_abs, bundle_text, encoding="utf-8")

    done_count = sum(1 for x in done if x)
    print()
    print(color(f"[STEP 1 DONE] Created: {_rel_posix_from_cwd(bundle_abs)} | done flags: {done_count}/{len(files)}", BOLD))

    remaining = [p for p, d in zip(files, done) if not d]
    if remaining:
        print(color("Files with no content (still incomplete):", YELLOW))
        for p in remaining:
            print(" -", p)
    else:
        print(color("All files completed. Good job.", GREEN))

    print()
    print(color("NEXT (STEP 2):", CYAN), "Send bundle to your LLM, let it modify the code, and save the result as bundle_modified.txt.")
    print(color("When you're done, you can run STEP 3 to apply patches.", CYAN))

    if ask_yes_no(color("Run STEP 3 now after you prepare bundle_modified.txt? (y/N) > ", CYAN), default_no=True):
        return run_step3_patch()

    return 0


# =========================
# ✅ STEP 3 구현: bundle diff → 프로젝트 패치 + VERIFY
# =========================

def run_step3_patch() -> int:
    print()
    print(color("=============== STEP 3: Apply Patch from Modified Bundle ===============", BOLD))

    # Default original bundle path: prefer <CWD>/bundles/bundle.txt
    default_orig_new = os.path.join(os.getcwd(), BUNDLES_OUT_DIRNAME, BUNDLE_BASENAME)
    default_orig_legacy = os.path.join(os.getcwd(), BUNDLE_BASENAME)

    try:
        orig_path = input(color("Original bundle path (Enter=auto) > ", BOLD)).strip()
    except EOFError:
        orig_path = ""

    if not orig_path:
        if os.path.exists(default_orig_new):
            orig_path = default_orig_new
        else:
            orig_path = default_orig_legacy

    try:
        mod_path = input(color("Modified bundle path (Enter=bundle_modified.txt) > ", BOLD)).strip()
    except EOFError:
        mod_path = ""
    if not mod_path:
        mod_path = "bundle_modified.txt"

    if not os.path.exists(orig_path):
        print(color(f"Original bundle not found: {orig_path}", RED))
        return 1
    if not os.path.exists(mod_path):
        print(color(f"Modified bundle not found: {mod_path}", RED))
        return 1

    try:
        orig_rel_root, orig_files = parse_bundle_file(orig_path)
        mod_rel_root, mod_files = parse_bundle_file(mod_path)
    except Exception as e:
        print(color(f"Failed to parse bundle(s): {type(e).__name__} :: {e}", RED))
        return 1

    rel_root = orig_rel_root or os.getcwd()
    rel_root = os.path.abspath(os.path.expanduser(rel_root))
    ensure_artifacts(rel_root)

    # HARD GUARD: stop duplicate STEP3 execution (fixes verify spam)
    if not _acquire_step3_lock(rel_root):
        print(color("[STEP3] Already running (lock detected). Stop duplicate execution.", YELLOW))
        return 1

    try:
        if mod_rel_root and os.path.abspath(mod_rel_root) != os.path.abspath(rel_root):
            print(color("WARNING:", YELLOW), "Original REL_ROOT and modified REL_ROOT differ.")
            print(color(f"  original: {orig_rel_root}", DIM))
            print(color(f"  modified: {mod_rel_root}", DIM))
            print(color(f"Using original REL_ROOT: {rel_root}", CYAN))

        per_file, summary = analyze_diff(orig_files, mod_files)

        # Load config once
        cfg = ensure_config_or_wizard(rel_root)

        total_files = summary["total_files"]
        changed_files = summary["changed_files"]
        new_files = summary["new_files"]
        deleted_files = summary["deleted_files"]
        total_added_lines = summary["total_added_lines"]
        total_removed_lines = summary["total_removed_lines"]

        small_changes = [f for f in per_file if f["kind"] == "changed" and f["changed_ratio"] <= 0.3]
        big_changes = [f for f in per_file if f["kind"] == "changed" and f["changed_ratio"] > 0.3]

        print()
        print(color("Diff summary:", BOLD))
        print(f"  Total files in bundles: {total_files}")
        print(f"  Changed files:          {changed_files}")
        print(f"  New files:              {new_files}")
        print(f"  Deleted files:          {deleted_files}")
        print(f"  Total lines + / - :     +{total_added_lines} / -{total_removed_lines}")
        print(f"  Small changes (<=30%):  {len(small_changes)}")
        print(f"  BIG changes (>30%):     {len(big_changes)}")

        if big_changes:
            print()
            print(color("BIG change candidates:", YELLOW))
            for info in big_changes[:20]:
                print(
                    f" - {info['path']} :: ratio={info['changed_ratio']:.2f}, "
                    f"+{info['added']} / -{info['removed']}"
                )
            if len(big_changes) > 20:
                print(color(f"  ... and {len(big_changes) - 20} more", DIM))

        print()
        print(color("Choose patch strategy:", BOLD))
        print(color("[1] SAFE auto-apply", CYAN), " - small changes + new files only, no deletes, BIG changes skipped")
        print(color("[2] FULL auto-apply", CYAN), " - apply ALL changes including deletes (HIGH RISK)")
        print(color("[3] DRY RUN", CYAN), " - no write, just generate a diff summary report")
        print(color("[q] Cancel", CYAN))

        try:
            ans = input(color("Strategy > ", BOLD)).strip().lower()
        except EOFError:
            ans = "q"

        if ans == "q" or ans == "":
            print(color("Patch cancelled.", YELLOW))
            return 0

        if ans not in ("1", "2", "3"):
            print(color("Invalid choice.", RED))
            return 1

        if ans == "3":
            report_path = art_path(rel_root, "reports", "bundle_diff_report.txt")
            lines: list[str] = []
            lines.append(f"# Diff report generated at {datetime.now().isoformat(timespec='seconds')}\n\n")
            lines.append(f"REL_ROOT: {rel_root}\n\n")
            for info in per_file:
                if info["kind"] == "same":
                    continue
                lines.append(
                    f"{info['kind'].upper():7} {info['path']} "
                    f"(ratio={info['changed_ratio']:.2f}, "
                    f"+{info['added']} / -{info['removed']})\n"
                )
            atomic_write_text(report_path, "".join(lines), encoding="utf-8")
            print(color(f"Dry run done. See {_rel_posix_from_abs(rel_root, report_path)}", GREEN))
            return 0

        strategy = "safe" if ans == "1" else "full"

        # --- PRE-SNAPSHOT for real rollback verification ---
        pre_hashes: dict[str, str | None] = {}
        for info in per_file:
            if info["kind"] == "same":
                continue
            p = info["path"]
            abs_target = os.path.join(rel_root, _from_posix(p))
            if (not _is_within_root(rel_root, abs_target)) or (not os.path.exists(abs_target)):
                pre_hashes[p] = None
            else:
                pre_hashes[p] = _sha256_file(abs_target)

        # for delete restore when no disk backup exists
        deleted_snapshots: dict[str, str] = {}
        for info in per_file:
            if info["kind"] == "deleted":
                p = info["path"]
                if p in orig_files:
                    deleted_snapshots[p] = orig_files[p]

        manifest = apply_patches(
            rel_root=rel_root,
            per_file=per_file,
            orig_files=orig_files,
            mod_files=mod_files,
            strategy=strategy,
            pre_hashes=pre_hashes,
            deleted_snapshots=deleted_snapshots,
        )

        print()
        print(color("[STEP 3 DONE] Patch process finished.", BOLD))
        print(color("Now verifying applied result... (real check)", CYAN))

        ts = manifest["ts"]

        # ---- VERIFY A: disk check ----
        summary_a, report_a = verify_disk_against_modified(rel_root, manifest, mod_files, ts)
        print(color("[VERIFY-A] Disk vs modified (manifest-based):", BOLD))
        print(
            f"  OK: {summary_a['ok']}, MISMATCH: {summary_a['mismatch']}, "
            f"MISSING: {summary_a['missing']}, UNREAD: {summary_a['unread']}, "
            f"BLOCKED: {summary_a['blocked']}, EXPECTED_SKIP: {summary_a['expected_skip']}"
        )
        print(color(f"  Report -> {_rel_posix_from_abs(rel_root, report_a)}", DIM))

        # ---- VERIFY B: rebundle cross-check ----
        scan_dirs_abs, state_rel_root = _load_scan_dirs_from_state_if_possible(rel_root)
        if state_rel_root and os.path.abspath(state_rel_root) != os.path.abspath(rel_root):
            scan_dirs_abs = None

        out_bundle, applied_map, rebundle_skipped = rebuild_bundle_for_verify(rel_root, scan_dirs_abs, cfg, ts)

        summary_b, report_b = compare_modified_vs_applied(rel_root, manifest, mod_files, applied_map, rebundle_skipped, ts)
        print(color("[VERIFY-B] Modified vs rebundled scan (manifest-based):", BOLD))
        print(
            f"  OK: {summary_b['ok']}, MISMATCH: {summary_b['mismatch']}, "
            f"MISSING_IN_APPLIED: {summary_b['missing_in_applied']}, "
            f"EXPECTED_UNREAD: {summary_b['expected_unread']} / CHECKED: {summary_b['checked_files']}"
        )
        print(color(f"  Rebundle -> {_rel_posix_from_cwd(out_bundle)}", DIM))
        print(color(f"  Report   -> {_rel_posix_from_abs(rel_root, report_b)}", DIM))

        if summary_a["mismatch"] or summary_a["missing"] or summary_b["mismatch"] or summary_b["missing_in_applied"]:
            print()
            print(color("WARNING: Verification found mismatches.", YELLOW))
            print(color("If you need rollback: use main menu [r] Restore or CLI --restore.", CYAN))
        else:
            print()
            print(color("VERIFY PASSED. Applied result matches modified bundle (for applied set).", GREEN))

        return 0

    finally:
        _release_step3_lock(rel_root)


# =========================
# ✅ 메인 메뉴
# =========================

def main() -> int:
    argv = sys.argv[1:]

    # ✅ config only
    if any(a in ("--config", "--configure") for a in argv):
        filtered = [a for a in argv if a not in ("--config", "--configure")]
        return run_config_wizard_only(filtered)

    # ✅ patch
    if any(a in ("--patch", "--apply-patch") for a in argv):
        return run_step3_patch()

    # ✅ restore
    if any(a in ("--restore", "--rollback") for a in argv):
        return run_restore_menu()

    print(color("=============== BundleMaker v2.1 ===============", BOLD))
    print(color("LLM-friendly project bundler & patcher + verify + restore", DIM))
    print()
    print(color("Select:", BOLD))
    print(color("[1] STEP 1 — Create bundle from project", CYAN))
    print(color("[2] STEP 3 — Apply patch from modified bundle (+VERIFY)", CYAN))
    print(color("[c] Configure — create/overwrite .bundlemaker.json", CYAN))
    print(color("[r] Restore — rollback from patch manifest backups", CYAN))
    print(color("[q] Quit", CYAN))
    print(color("(TIP) CLI: --config, --auto/--paste/--hybrid, --patch, --restore", DIM))

    try:
        choice = input(color("Choice (Enter=1) > ", BOLD)).strip().lower()
    except EOFError:
        choice = "1"

    if choice in ("", "1"):
        return run_step1_bundle(argv)
    if choice == "2":
        return run_step3_patch()
    if choice == "c":
        return run_config_wizard_only(argv)
    if choice == "r":
        return run_restore_menu()
    if choice == "q":
        print(color("Bye.", DIM))
        return 0

    print(color("Invalid choice.", RED))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
