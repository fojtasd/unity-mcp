"""A read-only command caught by a domain reload is sent once more to the reconnected session."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from transport.plugin_hub import PluginDisconnectedError, PluginHub

DROPPED = {
    "success": False,
    "error": "Unity plugin session old disconnected while awaiting command_result",
    "hint": "retry",
    "data": {"reason": "plugin_disconnected"},
}
DONE = {"success": True, "data": {"status": "succeeded"}}


@pytest.fixture
def hub(monkeypatch):
    """PluginHub with sessions resolved to fresh ids and no readiness probe; returns the resolve mock."""
    monkeypatch.setenv("UNITY_MCP_SESSION_READY_WAIT_SECONDS", "0")
    resolve = AsyncMock(side_effect=["sess-before-reload", "sess-after-reload", "sess-third"])
    monkeypatch.setattr(PluginHub, "_resolve_session_id", resolve)
    monkeypatch.setattr(PluginHub, "_ensure_live_connection", AsyncMock(return_value=True))
    return resolve


def _unity(monkeypatch, *replies):
    send = AsyncMock(side_effect=list(replies))
    monkeypatch.setattr(PluginHub, "send_command", send)
    return send


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["get_test_job", "read_console", "get_editor_state"])
async def test_a_read_only_command_dropped_by_a_reload_is_sent_again(hub, monkeypatch, command):
    send = _unity(monkeypatch, DROPPED, DONE)

    result = await PluginHub.send_command_for_instance("Project@hash", command, {"job_id": "j1"})

    assert result == DONE
    assert [c.args[0] for c in send.await_args_list] == ["sess-before-reload", "sess-after-reload"]
    assert all(c.args[1:] == (command, {"job_id": "j1"}) for c in send.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["run_tests", "refresh_unity", "execute_code", "manage_scene"])
async def test_a_command_that_changes_the_project_is_never_repeated(hub, monkeypatch, command):
    send = _unity(monkeypatch, DROPPED, DONE)

    result = await PluginHub.send_command_for_instance("Project@hash", command, {})

    assert result == DROPPED
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_it_is_sent_again_only_once(hub, monkeypatch):
    send = _unity(monkeypatch, DROPPED, DROPPED, DONE)

    result = await PluginHub.send_command_for_instance("Project@hash", "get_test_job", {})

    assert result == DROPPED
    assert send.await_count == 2


@pytest.mark.asyncio
async def test_no_retry_when_the_caller_opts_out_of_reload_waits(hub, monkeypatch):
    send = _unity(monkeypatch, DROPPED, DONE)

    result = await PluginHub.send_command_for_instance(
        "Project@hash", "get_test_job", {}, retry_on_reload=False)

    assert result == DROPPED
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_other_failures_are_not_retried(hub, monkeypatch):
    timed_out = {"success": False, "error": "Unity did not respond", "hint": "retry", "data": None}
    send = _unity(monkeypatch, timed_out, DONE)

    result = await PluginHub.send_command_for_instance("Project@hash", "read_console", {})

    assert result == timed_out
    assert send.await_count == 1


def test_send_command_marks_a_dropped_session():
    async def exercise():
        websocket = MagicMock()

        async def send_json(message):
            PluginHub._pending[message["id"]]["future"].set_exception(
                PluginDisconnectedError("Unity plugin session s1 disconnected while awaiting command_result"))

        websocket.send_json = AsyncMock(side_effect=send_json)
        with patch.object(PluginHub, "_get_connection", AsyncMock(return_value=websocket)), \
             patch.object(PluginHub, "_lock", asyncio.Lock()), \
             patch.object(PluginHub, "_pending", {}):
            return await PluginHub.send_command("s1", "get_test_job", {})

    result = asyncio.run(exercise())
    assert result["success"] is False
    assert result["hint"] == "retry"
    assert result["data"] == {"reason": "plugin_disconnected"}
    assert PluginHub._is_plugin_disconnect(result)
