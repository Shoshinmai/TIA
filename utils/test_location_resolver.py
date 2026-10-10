import asyncio
from pathlib import Path

import pytest

from location_resolver import (
    get_workspace_root,
    resolve_location,
    workspace_scope,
)


def test_workspace_alias_uses_explicit_workspace(tmp_path: Path):
    workspace = tmp_path / "explicit"
    workspace.mkdir()

    resolved = resolve_location(
        "workspace",
        workspace_root=workspace,
    )

    assert resolved == workspace.resolve()


def test_workspace_scope_restores_previous_value(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    assert get_workspace_root() is None

    with workspace_scope(first):
        assert get_workspace_root() == first.resolve()

        with workspace_scope(second):
            assert get_workspace_root() == second.resolve()

        assert get_workspace_root() == first.resolve()

    assert get_workspace_root() is None


@pytest.mark.asyncio
async def test_concurrent_workspace_scopes_are_isolated(tmp_path: Path):
    first = tmp_path / "session_a"
    second = tmp_path / "session_b"
    first.mkdir()
    second.mkdir()

    async def resolve_in_scope(workspace: Path) -> Path:
        with workspace_scope(workspace):
            # The resolver is also used from asyncio.to_thread().
            return await asyncio.to_thread(
                resolve_location,
                "workspace",
            )

    resolved_first, resolved_second = await asyncio.gather(
        resolve_in_scope(first),
        resolve_in_scope(second),
    )

    assert resolved_first == first.resolve()
    assert resolved_second == second.resolve()
    assert get_workspace_root() is None