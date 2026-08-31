from pathlib import Path
import re


WORKFLOWS_DIR = Path(__file__).parents[1] / ".github" / "workflows"
REQUIREMENTS_FILES = (
    Path(__file__).parents[1] / "requirements.txt",
    Path(__file__).parents[1] / "requirements-dev.txt",
)
ACTION_USE_RE = re.compile(r"^\s*uses:\s*[^\s@]+@([0-9a-fA-F]{40})(?:\s|$)")
EXACT_PIN_RE = re.compile(r"^[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+$")


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


def test_all_workflow_actions_use_full_commit_shas():
    for workflow_path in _workflow_files():
        for line_number, line in enumerate(workflow_path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith("uses:"):
                assert ACTION_USE_RE.match(line), f"{workflow_path}:{line_number} is not pinned to a full SHA"


def test_direct_requirements_use_exact_versions():
    for requirements_path in REQUIREMENTS_FILES:
        for line_number, line in enumerate(requirements_path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("-"):
                continue
            assert EXACT_PIN_RE.fullmatch(stripped), (
                f"{requirements_path}:{line_number} must pin a direct dependency with =="
            )


def test_checkout_does_not_persist_credentials():
    for workflow_path in _workflow_files():
        text = workflow_path.read_text(encoding="utf-8")
        if "actions/checkout@" in text:
            assert "persist-credentials: false" in text


def test_runtime_secrets_are_not_job_level_environment_variables():
    for workflow_path in _workflow_files():
        for line_number, line in enumerate(workflow_path.read_text(encoding="utf-8").splitlines(), start=1):
            if "secrets." not in line:
                continue
            indent = len(line) - len(line.lstrip())
            assert indent >= 10, f"{workflow_path}:{line_number} exposes a secret above step scope"


def test_core_writer_token_is_limited_to_commit_step():
    text = (WORKFLOWS_DIR / "TradeEye-1.0.0.yml").read_text(encoding="utf-8")

    assert "GH_TOKEN: ${{ github.token }}" in text
    assert "git -c http.extraheader=\"AUTHORIZATION: bearer ${GH_TOKEN}\" pull" in text
    assert "git -c http.extraheader=\"AUTHORIZATION: bearer ${GH_TOKEN}\" push" in text
    assert not re.search(r"^\s{4}env:\s*$", text, flags=re.MULTILINE)


def test_core_execution_and_state_write_use_separate_permission_scopes():
    text = (WORKFLOWS_DIR / "TradeEye-1.0.0.yml").read_text(encoding="utf-8")

    assert re.search(r"core_batch:\s*\n\s+permissions:\s*\n\s+contents: read", text)
    assert re.search(r"commit_state:\s*\n\s+if: needs\.core_batch\.result == 'success'", text)
    assert re.search(r"commit_state:.*?permissions:\s*\n\s+contents: write", text, flags=re.DOTALL)
    assert "actions/upload-artifact@" in text
    assert "actions/download-artifact@" in text
