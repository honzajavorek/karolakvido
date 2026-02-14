from __future__ import annotations

from pathlib import Path


def test_workflow_contains_weekly_and_two_exports() -> None:
    workflow = Path(".github/workflows/publish-ics.yml").read_text(encoding="utf-8")

    assert 'cron: "0 6 * * 1"' in workflow
    assert "uv run karolakvido --output public/karolakvido.ics" in workflow
    assert "uv run karolakvido --kraj Praha --output public/karolakvido-praha.ics" in workflow
    assert "actions/deploy-pages@v4" in workflow
