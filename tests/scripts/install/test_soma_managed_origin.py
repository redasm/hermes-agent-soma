"""Soma desktop managed checkouts migrate their upstream origin during a real repository stage."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALL_PS1 = Path(__file__).resolve().parents[3] / "scripts" / "install.ps1"
POWERSHELL = shutil.which("powershell.exe")

def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )

def _make_conflicted_managed_checkout(tmp_path: Path) -> Path:
    """Create a managed checkout whose autostash conflicts with its origin."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init")
    (seed / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "tracked.txt")
    _git(seed, "commit", "-m", "base")
    _git(seed, "branch", "-M", "main")

    remote = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    managed = tmp_path / "hermes-agent"
    _git(tmp_path, "clone", "--branch", "main", str(remote), str(managed))

    (managed / "tracked.txt").write_text("local edit\n", encoding="utf-8")

    upstream = tmp_path / "upstream"
    _git(tmp_path, "clone", "--branch", "main", str(remote), str(upstream))
    (upstream / "tracked.txt").write_text("upstream edit\n", encoding="utf-8")
    _git(upstream, "commit", "-am", "upstream")
    _git(upstream, "push", "origin", "main")

    return managed

@pytest.mark.platforms("windows")
def test_install_ps1_migrates_only_desktop_managed_upstream_checkout(
    tmp_path: Path,
) -> None:
    """The desktop-owned checkout follows the Soma fork without rebinding arbitrary repos."""
    managed = _make_conflicted_managed_checkout(tmp_path)
    local_origin = tmp_path / "origin.git"
    upstream_url = "https://github.com/NousResearch/hermes-agent.git"
    fork_url = "https://github.com/redasm/hermes-agent-soma.git"

    # Preserve a real repository-stage execution without network access: Git
    # records the public URL, while insteadOf routes both fetch targets to the
    # local bare repository created by the fixture.
    rewrite_key = f"url.{local_origin.as_uri()}.insteadOf"
    _git(managed, "config", "--add", rewrite_key, upstream_url)
    _git(managed, "config", "--add", rewrite_key, fork_url)
    _git(managed, "remote", "set-url", "origin", upstream_url)

    probe = (
        f". '{INSTALL_PS1}'; "
        f"$script:InstallDir = '{managed}'; $script:HermesHome = '{tmp_path}'; "
        "function Ensure-Git { return $true }; Stage-Repository"
    )
    env = dict(os.environ)
    env.pop("HERMES_REPO_URL", None)
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", probe],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (
        _git(managed, "config", "--get", "remote.origin.url").stdout.strip() == fork_url
    )
    assert _git(managed, "status", "--porcelain").stdout.strip() == ""
    assert _git(managed, "stash", "list").stdout.strip()
    assert (managed / "tracked.txt").read_text(encoding="utf-8") == "upstream edit\n"
