"""tools/deploy.sh: runs published images, and rolls back when they do not come up healthy.

A stand-in `docker` records what the script asks for, and fails `compose up`
for the tags named in FAIL_TAGS, as images that never get healthy would.
"""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "deploy.sh"

FAKE_DOCKER = """#!/bin/sh
echo "$* | $MINI_RAG_IMAGE | $MINI_RAG_WEB_IMAGE" >> "$DOCKER_LOG"
if [ "$2" = up ]; then
    for tag in $FAIL_TAGS; do
        case $MINI_RAG_IMAGE in *:"$tag") exit 1 ;; esac
    done
fi
exit 0
"""


@pytest.fixture
def server(tmp_path):
    """A deployment folder, and a PATH whose docker is the stand-in."""
    folder = tmp_path / "mini-rag"
    folder.mkdir()
    (folder / "compose.yaml").write_text("services: {}\n")
    (folder / ".env").write_text("OPENAI_API_KEY=unused\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    return folder


def deploy(server, *args, fail=()):
    log = server.parent / "docker.log"
    log.unlink(missing_ok=True)
    env = {**os.environ, "PATH": f"{server.parent / 'bin'}:{os.environ['PATH']}",
           "DOCKER_LOG": str(log), "FAIL_TAGS": " ".join(fail),
           "MINI_RAG_IMAGES": "ghcr.io/acme", "DEPLOY_TIMEOUT": "30"}
    result = subprocess.run(["sh", str(SCRIPT), *args], cwd=server, env=env,
                            capture_output=True, text=True, timeout=30)
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


def state(server):
    folder = server / ".deploy"
    return {name: (folder / name).read_text().strip()
            for name in ("current", "previous") if (folder / name).exists()}


def test_a_deployment_pulls_and_starts_the_images_of_a_tag(server):
    result, calls = deploy(server, "sha-1111111")

    assert result.returncode == 0, result.stderr
    images = "ghcr.io/acme/mini-rag:sha-1111111 | ghcr.io/acme/mini-rag-web:sha-1111111"
    assert calls == [
        f"compose pull --quiet app web | {images}",
        f"compose up --detach --no-build --wait --wait-timeout 30 app web | {images}",
    ]
    assert state(server) == {"current": "sha-1111111"}
    assert "sha-1111111 is up and healthy" in result.stdout


def test_each_deployment_remembers_the_one_before(server):
    deploy(server, "sha-1111111")
    deploy(server, "sha-2222222")
    result, _ = deploy(server, "sha-2222222")  # Again: nothing changes.

    assert result.returncode == 0
    assert state(server) == {"current": "sha-2222222", "previous": "sha-1111111"}


def test_unhealthy_images_are_rolled_back(server):
    deploy(server, "1.0.0")

    result, calls = deploy(server, "1.1.0", fail=["1.1.0"])

    assert result.returncode == 1
    assert "1.1.0 did not come up healthy: rolling back to 1.0.0" in result.stdout
    assert "1.0.0 runs again" in result.stderr
    # What went wrong is in the log, then the images before run again.
    assert any(call.startswith("compose logs --no-color --tail 50 app web") for call in calls)
    assert calls[-1].startswith("compose up") and calls[-1].endswith("mini-rag-web:1.0.0")
    assert state(server) == {"current": "1.0.0"}


def test_a_failing_first_deployment_has_nothing_to_roll_back_to(server):
    result, calls = deploy(server, "1.0.0", fail=["1.0.0"])

    assert result.returncode == 1
    assert "nothing to roll back to" in result.stderr
    assert state(server) == {}


def test_a_failing_rollback_says_so(server):
    deploy(server, "1.0.0")

    result, _ = deploy(server, "1.1.0", fail=["1.1.0", "1.0.0"])

    assert result.returncode == 1
    assert "the rollback to 1.0.0 failed too" in result.stderr


def test_rolling_back_by_hand_swaps_the_deployments(server):
    deploy(server, "1.0.0")
    deploy(server, "1.1.0")

    result, calls = deploy(server, "rollback")

    assert result.returncode == 0, result.stderr
    assert calls[-1].endswith("ghcr.io/acme/mini-rag-web:1.0.0")
    assert state(server) == {"current": "1.0.0", "previous": "1.1.0"}
    status, _ = deploy(server, "status")
    assert status.stdout.split() == ["current:", "1.0.0", "previous:", "1.1.0"]


def test_there_is_no_rollback_before_a_second_deployment(server):
    deploy(server, "1.0.0")

    result, calls = deploy(server, "rollback")

    assert result.returncode == 1
    assert "no earlier deployment" in result.stderr
    assert calls == []


@pytest.mark.parametrize("tag", ["", "-rf", ".hidden", "1.0;rm", "a b", "x" * 129])
def test_only_image_tags_are_deployed(server, tag):
    result, calls = deploy(server, tag) if tag else deploy(server)

    assert result.returncode != 0
    assert calls == []


def test_a_deployment_needs_its_settings(server):
    (server / ".env").unlink()

    result, calls = deploy(server, "1.0.0")

    assert result.returncode == 1
    assert "there is no .env here" in result.stderr
    assert calls == []


def test_help_explains_the_commands(server):
    result, _ = deploy(server, "--help")

    assert result.returncode == 0
    assert "tools/deploy.sh rollback" in result.stdout
