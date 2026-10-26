"""The server log stays short: tool calls and results cut, a session told once to choose an instance."""
import pytest

from .test_helpers import DummyContext


def test_long_arguments_and_results_are_cut():
    from core.logging_decorator import _short, _MAX_LOGGED_CHARS

    assert _short("short") == "short"
    cut = _short("x" * 5000)
    assert cut.startswith("x" * _MAX_LOGGED_CHARS)
    assert cut.endswith("(5000 chars)")
    assert len(cut) < _MAX_LOGGED_CHARS + 30

    # A failure keeps its error, which comes after a long message.
    failed = "success=False message='" + "m" * 500 + "' error='Unity plugin session x disconnected while awaiting command_result'"
    assert _short(failed) == failed


@pytest.mark.asyncio
async def test_a_session_is_told_once_to_choose_an_instance(monkeypatch):
    # The module's own logger is watched: the server's logging set up by other tests does not
    # propagate to pytest's capture.
    import transport.unity_instance_middleware as module

    said = []
    monkeypatch.setattr(module.logger, "info", lambda msg, *args: said.append(msg % args))
    middleware = module.UnityInstanceMiddleware()
    ctx = DummyContext()
    ids = ["a@1111", "b@2222"]
    await middleware._note_multiple_instances(ctx, ids)
    await middleware._note_multiple_instances(ctx, list(reversed(ids)))
    assert len(said) == 1
    assert "Multiple Unity instances found (2)" in said[0]

    # Another Editor comes: the session is told again.
    await middleware._note_multiple_instances(ctx, ids + ["c@3333"])
    assert len(said) == 2

    # Another session is told too.
    await middleware._note_multiple_instances(DummyContext(), ids)
    assert len(said) == 3
