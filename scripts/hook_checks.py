from __future__ import annotations

import json
import os
import py_compile
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_PATTERNS = [
    re.compile(r"(^|/)\.codex(/|$)"),
    re.compile(r"(^|/)__pycache__(/|$)"),
    re.compile(r"\.pyc$"),
    re.compile(r"(^|/)backend/data/models_cache(/|$)"),
    re.compile(r"(^|/)backend/\.env$"),
    re.compile(r"(^|/)nul$"),
    re.compile(r"\.log$"),
]
CONVENTIONAL_COMMIT_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)"
    r"(\([a-z0-9._/-]+\))?: .+"
)
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
COMMENT_CHECK_EXTS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".css",
    ".html",
    ".sh",
    ".ps1",
}


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def staged_files() -> list[Path]:
    output = run_git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    if not output:
        return []
    return [Path(line) for line in output.splitlines() if line.strip()]


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def ensure_no_forbidden_files(files: list[Path]) -> None:
    bad = []
    for path in files:
        unix_path = path.as_posix()
        if any(pattern.search(unix_path) for pattern in FORBIDDEN_PATTERNS):
            bad.append(unix_path)
    if bad:
        fail("Refusing to commit forbidden files:\n- " + "\n- ".join(sorted(bad)))


def compile_python(files: list[Path]) -> None:
    for rel_path in files:
        if rel_path.suffix != ".py":
            continue
        py_compile.compile(str(ROOT / rel_path), doraise=True)


def validate_json(files: list[Path]) -> None:
    for rel_path in files:
        if rel_path.suffix not in {".json", ".jsonl"}:
            continue
        file_path = ROOT / rel_path
        with file_path.open("r", encoding="utf-8") as handle:
            if rel_path.suffix == ".json":
                json.load(handle)
            else:
                for line_no, line in enumerate(handle, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as exc:
                        fail(f"Invalid JSONL in {rel_path}:{line_no}: {exc}")


def validate_commit_message(path_arg: str) -> None:
    msg_path = Path(path_arg)
    content = msg_path.read_text(encoding="utf-8").strip()
    if not CONVENTIONAL_COMMIT_RE.match(content):
        fail(
            "Commit message must follow conventional commits, for example:\n"
            "feat(hooks): add repository hook workflow"
        )


def validate_docs() -> None:
    readme = ROOT / "README.md"
    if not readme.exists():
        fail("README.md is required before push.")
    content = readme.read_text(encoding="utf-8")
    required_snippets = [
        "git config core.hooksPath .githooks",
        "pre-commit",
        "pre-push",
        "commit-msg",
        "--no-verify",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in content]
    if missing:
        fail("README.md is missing hook documentation for: " + ", ".join(missing))


def validate_repo_files() -> None:
    required_paths = [
        ROOT / "backend" / "requirements.txt",
        ROOT / "frontend" / "index.html",
        ROOT / "backend" / "app" / "main.py",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    if missing:
        fail("Repository is missing required project files: " + ", ".join(missing))


def _extract_comment_payload(rel_path: Path, line: str) -> str | None:
    suffix = rel_path.suffix.lower()
    stripped = line.lstrip()

    if suffix in {".py", ".sh", ".ps1"}:
        if stripped.startswith("#") and not stripped.startswith("#!"):
            return stripped[1:].strip()
        return None

    if suffix in {".js", ".jsx", ".ts", ".tsx", ".css"}:
        if stripped.startswith("//"):
            return stripped[2:].strip()
        if stripped.startswith("/*"):
            return stripped[2:].split("*/", 1)[0].strip()
        if stripped.startswith("*"):
            return stripped[1:].strip()
        return None

    if suffix == ".html" and "<!--" in stripped:
        return stripped.split("<!--", 1)[1].split("-->", 1)[0].strip()

    return None


def validate_comment_language(files: list[Path]) -> None:
    comment_language = os.getenv("COMMENT_LANGUAGE", "en").strip().lower()
    if comment_language not in {"en", "english"}:
        return

    violations = []
    for rel_path in files:
        if rel_path.suffix.lower() not in COMMENT_CHECK_EXTS:
            continue

        file_path = ROOT / rel_path
        if not file_path.exists() or not file_path.is_file():
            continue

        content = file_path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(content.splitlines(), start=1):
            payload = _extract_comment_payload(rel_path, line)
            if not payload or not CJK_RE.search(payload):
                continue
            snippet = payload if len(payload) <= 80 else (payload[:77] + "...")
            violations.append(f"{rel_path}:{line_no}: {snippet}")

    if violations:
        fail(
            "Comment language policy violation (expected English comments):\n- "
            + "\n- ".join(violations)
        )


def run_pre_commit() -> None:
    files = staged_files()
    ensure_no_forbidden_files(files)
    compile_python(files)
    validate_json(files)
    validate_comment_language(files)


def run_pre_push() -> None:
    validate_repo_files()
    validate_docs()
    py_files = [
        path.relative_to(ROOT)
        for folder in ("backend", "scripts")
        for path in (ROOT / folder).rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    compile_python(py_files)
    json_files = [
        path.relative_to(ROOT)
        for path in (ROOT / "backend").rglob("*.json*")
        if "models_cache" not in path.parts and "__pycache__" not in path.parts
    ]
    validate_json(json_files)
    comment_files = [
        path.relative_to(ROOT)
        for folder in ("backend", "frontend", "scripts")
        for path in (ROOT / folder).rglob("*")
        if path.is_file()
        and path.suffix.lower() in COMMENT_CHECK_EXTS
        and "__pycache__" not in path.parts
    ]
    validate_comment_language(comment_files)


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        fail("Usage: hook_checks.py <pre-commit|pre-push|commit-msg> [args]")
    command = argv[1]
    if command == "pre-commit":
        run_pre_commit()
        return
    if command == "pre-push":
        run_pre_push()
        return
    if command == "commit-msg":
        if len(argv) != 3:
            fail("commit-msg requires a path to the commit message file")
        validate_commit_message(argv[2])
        return
    fail(f"Unknown command: {command}")


if __name__ == "__main__":
    main(sys.argv)
