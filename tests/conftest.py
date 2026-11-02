import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def vault(tmp_path):
    """A throwaway copy of the demo vault."""
    from job_agent.config import DEMO_VAULT, Vault
    dst = tmp_path / "vault"
    shutil.copytree(DEMO_VAULT, dst, ignore=shutil.ignore_patterns("state"))
    return Vault(dst)


@pytest.fixture
def store(tmp_path):
    from job_agent.store import Store
    return Store(tmp_path / "jobs.db")


@pytest.fixture
def countries():
    from job_agent.config import DEMO_VAULT
    return yaml.safe_load((DEMO_VAULT / "work_authorization.yml").read_text())["countries"]


@pytest.fixture
def samples():
    return json.loads((FIX / "digest_samples.json").read_text())
