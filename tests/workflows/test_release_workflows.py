from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_main_pr_source_guard_requires_staging():
    workflow = (ROOT / ".github/workflows/main-pr-source.yml").read_text(encoding="utf-8")

    assert 'branches: [ "main" ]' in workflow
    assert "HEAD_REF: ${{ github.head_ref }}" in workflow
    assert 'if [[ "$HEAD_REF" != "staging" ]]' in workflow
    assert "Pull requests into main must come from the staging branch." in workflow


def test_release_tag_workflow_is_reusable():
    workflow = (ROOT / ".github/workflows/release-tag.yml").read_text(encoding="utf-8")

    assert "workflow_call:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "contents: write" in workflow
    assert 'TAG="v${DATE}.${RUN_NUMBER}"' in workflow
    assert 'git tag -a "$TAG" "$SHA"' in workflow


def test_main_pipeline_runs_release_flow_after_main_push():
    workflow = (ROOT / ".github/workflows/main-pipeline.yml").read_text(encoding="utf-8")

    assert 'branches: [ "main" ]' in workflow
    assert "uses: ./.github/workflows/tests.yml" in workflow
    assert "uses: ./.github/workflows/terraform.yaml" in workflow
    assert "needs: [ tests, terraform ]" in workflow
    assert "uses: ./.github/workflows/deploy.yaml" in workflow
    assert "target_env: prod" in workflow
    assert "needs: deploy" in workflow
    assert "uses: ./.github/workflows/release-tag.yml" in workflow
    assert "sync-main-back-to-staging:" in workflow
    assert "git push origin HEAD:staging" in workflow


def test_staging_pipeline_deploys_after_quality():
    workflow = (ROOT / ".github/workflows/staging-pipeline.yml").read_text(encoding="utf-8")

    assert 'branches: [ "staging" ]' in workflow
    assert "uses: ./.github/workflows/quality.yml" in workflow
    assert "needs: quality" in workflow
    assert "uses: ./.github/workflows/deploy.yaml" in workflow
    assert "target_env: staging" in workflow
