from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_main_pr_source_guard_requires_staging():
    workflow = (ROOT / ".github/workflows/main-pr-source.yml").read_text(encoding="utf-8")

    assert 'branches: [ "main" ]' in workflow
    assert 'github.head_ref }}" != "staging"' in workflow
    assert "Pull requests into main must come from the staging branch." in workflow


def test_release_tag_workflow_tags_main_pushes():
    workflow = (ROOT / ".github/workflows/release-tag.yml").read_text(encoding="utf-8")

    assert 'branches: [ "main" ]' in workflow
    assert "contents: write" in workflow
    assert 'TAG="v${DATE}.${RUN_NUMBER}"' in workflow
    assert 'git tag -a "$TAG" "$SHA"' in workflow
