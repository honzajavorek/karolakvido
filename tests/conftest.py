from __future__ import annotations

from pathlib import Path

import pytest
import requests


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--refresh-web-snapshots",
        action="store_true",
        default=False,
        help="Stáhne živá data z webu a uloží je do tests/snapshots.",
    )


@pytest.fixture()
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture()
def snapshots_dir() -> Path:
    directory = Path(__file__).parent / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@pytest.fixture()
def web_snapshot_loader(pytestconfig: pytest.Config, snapshots_dir: Path):
    refresh = bool(pytestconfig.getoption("refresh_web_snapshots"))

    def _load(name: str, url: str) -> str:
        target = snapshots_dir / name
        if refresh:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            target.write_text(response.text, encoding="utf-8")
            return response.text

        if not target.exists():
            pytest.skip(
                f"Snapshot {target} neexistuje. "
                "Spusť testy s --refresh-web-snapshots pro jeho vytvoření."
            )

        return target.read_text(encoding="utf-8")

    return _load
