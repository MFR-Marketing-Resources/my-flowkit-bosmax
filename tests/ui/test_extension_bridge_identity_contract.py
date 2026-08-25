from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKGROUND = (ROOT / "extension/background.js").read_text(encoding="utf-8")


def _section(start: str, end: str) -> str:
    begin = BACKGROUND.index(start)
    finish = BACKGROUND.index(end, begin)
    return BACKGROUND[begin:finish]


def test_installation_identity_is_persistent_and_session_identity_is_ephemeral():
    startup = _section(
        "const EXTENSION_INSTALLATION_ID_STORAGE_KEY",
        "// ─── Live video-request capture",
    )
    init = _section("async function init()", "// ─── Token Capture")

    assert 'const EXTENSION_INSTALLATION_ID_STORAGE_KEY = "extension_installation_id";' in startup
    assert "async function loadOrCreateInstallationId()" in startup
    assert "chrome.storage.local.get([" in startup
    assert "EXTENSION_INSTALLATION_ID_STORAGE_KEY" in startup
    assert "[EXTENSION_INSTALLATION_ID_STORAGE_KEY]: installationId" in startup
    assert "const EXTENSION_SESSION_ID = (() => {" in startup
    assert "globalThis.crypto?.randomUUID" in startup
    assert "await loadOrCreateInstallationId();" in init
    assert 'chrome.storage.local.remove("callbackSecret")' in init
    assert '"callbackSecret"' not in _section(
        "const data = await chrome.storage.local.get([", "if (data.flowKey)"
    )


def test_extension_ready_and_status_emit_identity_tuple():
    connect = _section("function connectToAgent()", "function scheduleReconnect()")
    owned_reply = _section("const replyToAgent", "const replyAgentError")
    on_open = _section("connectionSocket.onopen", "connectionSocket.onmessage")
    callback_handshake = _section(
        '} else if (msg.type === "callback_secret")',
        '} else if (msg.method === "CHECK_FLOW_COMPOSER_READY")',
    )
    status = _section(
        "function buildBackgroundStatusResponse()", "function buildStageTelemetryPayload"
    )
    challenge = _section(
        "async function handleFlowProviderSessionChallenge",
        "function getKnownContentScriptHealth",
    )
    finalizer = _section("function finalizeMethodPayload", "function promiseWithTimeout")

    assert 'msg.type === "callback_secret"' in connect
    assert "const nextCallbackSecret = String(msg.secret || \"\");" in connect
    assert "const nextConnectionId = String(msg.connection_id || \"\");" in connect
    assert "connectionCallbackSecret = nextCallbackSecret;" in connect
    assert "connectionId = nextConnectionId;" in connect
    assert 'type: "extension_ready"' not in on_open
    assert 'type: "extension_ready"' in callback_handshake
    for field in (
        "installation_id: extensionInstallationId",
        "extension_session_id: EXTENSION_SESSION_ID",
        "connection_id: connectionId",
    ):
        assert field in connect
        assert field.replace("connectionId", "activeConnectionId") in status
        assert field.replace("connectionId", "activeConnectionId") in challenge
    assert "reply.installation_id = extensionInstallationId;" in finalizer
    assert "reply.extension_session_id = EXTENSION_SESSION_ID;" in finalizer
    assert "reply.connection_id = activeConnectionId;" in finalizer
    assert "connection_id: connectionId" in owned_reply
    assert "installation_id: extensionInstallationId" in owned_reply
    assert "extension_session_id: EXTENSION_SESSION_ID" in owned_reply


def test_harvest_returns_actual_handled_tab_and_project():
    harvest = _section("async function handleHarvestVideoUrls", "function normalizeChromeMessageError")
    finalizer = _section("function finalizeMethodPayload", "function promiseWithTimeout")

    for field in (
        "handled_flow_tab_id",
        "handled_flow_url",
        "handled_flow_project_id",
    ):
        assert field in harvest
        assert field in finalizer
    assert "flowUrl: location.href" in harvest
    assert "envelope_flow_tab_id" in finalizer
    assert "envelope_flow_url" in finalizer
    assert "reply.flow_tab_id = payload.handled_flow_tab_id;" in finalizer
    assert "reply.flow_url = payload.handled_flow_url;" in finalizer
    assert "reply.flow_project_id = payload.handled_flow_project_id;" in finalizer


def test_callback_uses_connection_scoped_secret():
    init = _section("async function init()", "// ─── Token Capture")
    connect = _section("function connectToAgent()", "function scheduleReconnect()")
    sender = _section("function sendToAgent", "// ─── reCAPTCHA Solving")

    assert "let connectionCallbackSecret = null;" in connect
    assert "let connectionId = null;" in connect
    assert "callbackSecret: connectionCallbackSecret" in connect
    assert "websocket: connectionSocket" in connect
    assert "connectionCallbackSecret !== nextCallbackSecret" in connect
    assert "connectionId !== nextConnectionId" in connect
    assert 'connectionSocket.close(1008, "callback credential rotation")' in connect
    assert "if (ws !== connectionSocket) return;" in connect
    assert "_callbackSecret = null;" in connect
    assert "activeConnectionId = null;" in connect
    assert "function sendToAgent(msg, transportContext = {})" in sender
    assert "transportContext.callbackSecret" in sender
    assert '"X-Callback-Secret": callbackSecret || ""' in sender
    assert '"websocket"' in sender
    assert "data.callbackSecret" not in init
    assert "chrome.storage.local.set({ callbackSecret" not in init
    assert "chrome.storage.local.set({ callbackSecret" not in connect
