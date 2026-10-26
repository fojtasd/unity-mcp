"""With several Unity instances, a session is given the one whose project holds its MCP root."""
import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from .test_helpers import DummyContext
from core.config import config
from transport import unity_instance_middleware as mw
from transport.unity_instance_middleware import (
    UnityInstanceMiddleware,
    project_hashes_for_path,
    root_uri_to_path,
    select_instance_by_roots,
)


def unity_hash(project_folder: str) -> str:
    """The plugin's project hash: SHA1 of Application.dataPath, first 16 hex digits."""
    return hashlib.sha1(f"{project_folder}/Assets".encode("utf-8")).hexdigest()[:16]


MAIN = "C:/DEV/_Raccoon Survival/raccoon-beach-survival"
WORKTREE = "C:/DEV/raccoon-netvor"
INSTANCES = {
    "s1": SimpleNamespace(project="raccoon-beach-survival", hash=unity_hash(MAIN)),
    "s2": SimpleNamespace(project="raccoon-netvor", hash=unity_hash(WORKTREE)),
}


def test_the_hash_matches_one_a_real_editor_reported():
    assert unity_hash(MAIN) == "c89078d8872748ab"


@pytest.mark.parametrize("uri, path", [
    ("file:///C:/DEV/_Raccoon%20Survival/raccoon-beach-survival", MAIN),
    ("file:///C:/DEV/raccoon-netvor/", WORKTREE),
    ("file:///c%3A/DEV/raccoon-netvor", "c:/DEV/raccoon-netvor"),
    ("https://example.com/x", None),
])
def test_root_uris_become_paths(uri, path):
    assert root_uri_to_path(uri) == path


def test_a_root_below_the_project_folder_still_matches_it():
    assert unity_hash(WORKTREE) in project_hashes_for_path(f"{WORKTREE}/Assets/Scripts")


def test_the_drive_letter_case_does_not_matter():
    assert unity_hash(WORKTREE) in project_hashes_for_path("c:/DEV/raccoon-netvor")


def test_select_picks_the_project_that_holds_the_root():
    pairs = [(f"{s.project}@{s.hash}", s.hash) for s in INSTANCES.values()]
    assert select_instance_by_roots([WORKTREE], pairs) == f"raccoon-netvor@{unity_hash(WORKTREE)}"
    assert select_instance_by_roots(["D:/elsewhere"], pairs) is None
    # Roots in two projects are ambiguous.
    assert select_instance_by_roots([MAIN, WORKTREE], pairs) is None


class RootsContext(DummyContext):
    def __init__(self, roots, declares_roots=True, answer_after_s=0.0):
        super().__init__()
        self.asked = 0
        self._roots = roots
        self._delay = answer_after_s
        capabilities = SimpleNamespace(roots=SimpleNamespace() if declares_roots else None)
        self.session = SimpleNamespace(client_params=SimpleNamespace(capabilities=capabilities))

    async def list_roots(self):
        self.asked += 1
        await asyncio.sleep(self._delay)
        return [SimpleNamespace(uri=u) for u in self._roots]


@pytest.fixture
def two_editors(monkeypatch):
    monkeypatch.setattr(config, "transport_mode", "http")
    monkeypatch.setattr(config, "http_remote_hosted", False)
    monkeypatch.setattr(mw.PluginHub, "is_configured", classmethod(lambda cls: True))

    async def sessions(cls, user_id=None):
        return SimpleNamespace(sessions=INSTANCES)

    monkeypatch.setattr(mw.PluginHub, "get_sessions", classmethod(sessions))


@pytest.mark.asyncio
async def test_a_session_gets_the_editor_of_its_root(two_editors):
    middleware = UnityInstanceMiddleware()
    ctx = RootsContext(["file:///C:/DEV/raccoon-netvor"])

    chosen = await middleware._maybe_autoselect_instance(ctx)

    assert chosen == f"raccoon-netvor@{unity_hash(WORKTREE)}"
    assert await middleware.get_active_instance(ctx) == chosen


@pytest.mark.asyncio
async def test_roots_are_asked_once_per_session(two_editors):
    middleware = UnityInstanceMiddleware()
    ctx = RootsContext(["file:///D:/not-a-unity-project"])

    assert await middleware._maybe_autoselect_instance(ctx) is None
    assert await middleware._maybe_autoselect_instance(ctx) is None
    assert ctx.asked == 1


@pytest.mark.asyncio
async def test_a_client_without_roots_is_not_asked(two_editors):
    middleware = UnityInstanceMiddleware()
    ctx = RootsContext(["file:///C:/DEV/raccoon-netvor"], declares_roots=False)

    assert await middleware._maybe_autoselect_instance(ctx) is None
    assert ctx.asked == 0


@pytest.mark.asyncio
async def test_a_slow_client_does_not_hold_the_call(two_editors, monkeypatch):
    monkeypatch.setattr(mw, "_ROOTS_TIMEOUT_S", 0.05)
    middleware = UnityInstanceMiddleware()
    ctx = RootsContext(["file:///C:/DEV/raccoon-netvor"], answer_after_s=5.0)

    assert await middleware._maybe_autoselect_instance(ctx) is None
