"""Where things live.

    engine (this repo, public)      code, packs/, demo_vault/
    vault  ($JOB_VAULT, private)    the candidate: CV facts, work authorisation, answers,
                                    secrets, the job database, applications/

The engine never writes outside the vault and never reads personal data from anywhere
else. Unset JOB_VAULT and everything runs against the fictional demo vault.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ENGINE = Path(__file__).resolve().parent.parent
PACKS = ENGINE / "packs"
DEMO_VAULT = ENGINE / "demo_vault"


@dataclass(frozen=True)
class Vault:
    root: Path

    @property
    def is_demo(self) -> bool:
        return self.root.resolve() == DEMO_VAULT.resolve()

    @property
    def db(self) -> Path:
        """<vault>/state/jobs.db, or $JOB_STATE/jobs.db when the ledger lives outside the vault."""
        return Path(os.environ.get("JOB_STATE") or self.root / "state") / "jobs.db"

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def yaml(self, name: str, default=None):
        p = self.root / name
        if not p.exists():
            return default
        return yaml.safe_load(p.read_text(encoding="utf-8")) or default

    def contact(self) -> dict:
        """Personal contact details, never in git: $CONTACT_YAML, else <repo>/private/contact.yml."""
        raw = os.environ.get("CONTACT_YAML")
        if raw:
            return yaml.safe_load(raw) or {}
        f = ENGINE / "private" / "contact.yml"
        return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.exists() else {}

    def answers(self) -> dict:
        """answers.yml with the contact fields merged into its profile."""
        a = self.yaml("answers.yml", {}) or {}
        c = self.contact()
        prof = {k: c[k] for k in ("email", "linkedin") if c.get(k)}
        if c.get("phone_se") or c.get("phone"):
            prof["phone"] = c.get("phone") or c["phone_se"]
        a["profile"] = {**prof, **(a.get("profile") or {})}
        return a

    def env(self) -> dict[str, str]:
        """KEY=VALUE lines from <vault>/.env, overridden by real environment variables."""
        out: dict[str, str] = {}
        p = self.root / ".env"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip().strip('"').strip("'")
        out.update({k: v for k, v in os.environ.items() if k.startswith(("TG_", "JOB_"))})
        return out


def load_vault(explicit: str | os.PathLike | None = None) -> Vault:
    root = Path(explicit or os.environ.get("JOB_VAULT") or DEMO_VAULT).expanduser()
    if not root.is_dir():
        raise SystemExit(f"vault not found: {root}")
    return Vault(root)


def load_pack(kind: str) -> dict[str, dict]:
    """packs/<kind>/*.yml -> {stem: data}. kind is 'roles' or 'countries'."""
    out = {}
    for p in sorted((PACKS / kind).glob("*.yml")):
        out[p.stem] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return out


def resume_dir(vault_root: Path, policy: dict) -> Path:
    """Where application folders and CV templates live (policy apply.resume_dir, default vault/resume)."""
    return vault_root / (policy.get("apply", {}).get("resume_dir") or "resume")
