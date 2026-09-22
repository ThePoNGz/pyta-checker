import sys
from collections.abc import AsyncGenerator

import pytest
import pytest_lsp
from lsprotocol import types
from pytest_lsp import ClientServerConfig, LanguageClient

from .conftest import FIXTURES


@pytest_lsp.fixture(config=ClientServerConfig(server_command=[sys.executable, "-m", "pyta_lsp"]))
async def client(lsp_client: LanguageClient) -> AsyncGenerator[None, None]:
    result = await lsp_client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            root_uri=FIXTURES.as_uri(),
            initialization_options={"runOnOpen": True, "runOnSave": True, "configPath": ""},
        )
    )
    lsp_client.server_capabilities = result.capabilities  # type: ignore[attr-defined]
    yield
    await lsp_client.shutdown_session()


@pytest_lsp.fixture(config=ClientServerConfig(server_command=[sys.executable, "-m", "pyta_lsp"]))
async def quiet_client(lsp_client: LanguageClient) -> AsyncGenerator[None, None]:
    await lsp_client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            root_uri=FIXTURES.as_uri(),
            initialization_options={"runOnOpen": False, "runOnSave": True, "configPath": ""},
        )
    )
    yield
    await lsp_client.shutdown_session()


def _open(client: LanguageClient, name: str) -> str:
    path = FIXTURES / name
    uri = path.as_uri()
    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(
                uri=uri, language_id="python", version=1, text=path.read_text(encoding="utf-8")
            )
        )
    )
    return uri


async def test_open_publishes_diagnostics_honoring_embedded_config(client: LanguageClient) -> None:
    uri = _open(client, "course_style.py")
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    diagnostics = client.diagnostics[uri]
    codes = {d.code for d in diagnostics}
    assert "E9989" in codes
    assert "E9999" not in codes
    assert all(d.source == "PythonTA" for d in diagnostics)
    pep8 = next(d for d in diagnostics if d.code == "E9989")
    assert pep8.range.start == types.Position(line=11, character=9)
    assert pep8.range.end == types.Position(line=11, character=len("    total=0"))
    assert pep8.code_description is not None
    assert pep8.code_description.href.endswith("#e9989")


async def test_close_clears_diagnostics(client: LanguageClient) -> None:
    uri = _open(client, "no_config.py")
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    assert client.diagnostics[uri]
    client.text_document_did_close(
        types.DidCloseTextDocumentParams(text_document=types.TextDocumentIdentifier(uri=uri))
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    assert list(client.diagnostics[uri]) == []


async def test_syntax_error_is_reported(client: LanguageClient) -> None:
    uri = _open(client, "syntax_error.py")
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    codes = [d.code for d in client.diagnostics[uri]]
    assert codes == ["E0001"]
    assert client.diagnostics[uri][0].range.start.line == 3


async def test_execute_command_checks_a_document(client: LanguageClient) -> None:
    uri = (FIXTURES / "no_config.py").as_uri()
    # Registers the notification future now, before the request that triggers the publish is sent.
    published = client.protocol.wait_for_notification_async(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    await client.workspace_execute_command_async(
        types.ExecuteCommandParams(command="pyta.check", arguments=[uri])
    )
    await published
    codes = {d.code for d in client.diagnostics[uri]}
    assert "E9999" in codes


async def test_server_advertises_check_command(client: LanguageClient) -> None:
    provider = client.server_capabilities.execute_command_provider  # type: ignore[attr-defined]
    assert provider is not None
    assert "pyta.check" in provider.commands


async def test_run_on_open_false_publishes_nothing(quiet_client: LanguageClient) -> None:
    import asyncio

    uri = _open(quiet_client, "no_config.py")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            quiet_client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS), timeout=8
        )
    assert uri not in quiet_client.diagnostics or list(quiet_client.diagnostics[uri]) == []


async def test_precheck_failure_is_published_as_pyta_error(client: LanguageClient) -> None:
    uri = _open(client, "pylint_comment.py")
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    diagnostics = list(client.diagnostics[uri])
    assert [d.code for d in diagnostics] == ["pyta-error"]
    assert diagnostics[0].range.start.line == 0
    assert "pylint:" in diagnostics[0].message
