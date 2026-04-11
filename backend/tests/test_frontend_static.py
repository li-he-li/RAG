from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"
INDEX_HTML = FRONTEND_DIR / "index.html"
APP_JS = FRONTEND_DIR / "app.js"
STYLES_CSS = FRONTEND_DIR / "styles.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_frontend_assets_exist() -> None:
    assert FRONTEND_DIR.is_dir()
    assert INDEX_HTML.is_file()
    assert APP_JS.is_file()
    assert STYLES_CSS.is_file()


def test_frontend_javascript_passes_node_syntax_check() -> None:
    result = subprocess.run(
        ["node", "--check", str(APP_JS)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_index_html_contains_core_application_shell() -> None:
    html = _read(INDEX_HTML)

    required_ids = {
        "app",
        "sidebar",
        "welcomePanel",
        "chat",
        "composerWrap",
        "composer",
        "input",
        "reviewUploadBtn",
        "contractReviewModeToggle",
        "opponentPredictionModeToggle",
        "similarCaseModeToggle",
        "citationSidebar",
        "citationSidebarBody",
        "docFileInput",
        "templateFileInput",
        "predictionCaseNameInput",
        "predictionOpponentCorpusInput",
        "predictionCaseMaterialInput",
    }

    found_ids = set(re.findall(r'id="([^"]+)"', html))
    assert required_ids.issubset(found_ids)
    assert './styles.css' in html
    assert './app.js' in html


def test_frontend_javascript_targets_all_migrated_backend_routes() -> None:
    javascript = _read(APP_JS)

    expected_routes = {
        "/chat/stream",
        "/contract-review/stream",
        "/opponent-prediction/start",
        "/similar-cases/compare",
        "/prediction/templates",
        "/documents/upload",
        "/templates/upload",
        "/health",
        "/bootstrap",
    }

    for route in expected_routes:
        assert route in javascript

    assert "function resolveApiBase()" in javascript
    assert "const API_BASE = resolveApiBase();" in javascript
    assert "AbortController" in javascript


def test_frontend_styles_include_mobile_and_sidebar_layout_rules() -> None:
    stylesheet = _read(STYLES_CSS)

    expected_selectors = {
        ".sidebar-backdrop",
        ".citation-sidebar",
        ".prediction-template-panel",
        ".status-grid",
        ".composer-wrap",
        "@media (max-width: 900px)",
        "@media (prefers-reduced-motion: reduce)",
    }

    for selector in expected_selectors:
        assert selector in stylesheet
