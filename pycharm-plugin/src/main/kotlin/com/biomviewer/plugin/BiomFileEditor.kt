package com.biomviewer.plugin

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.google.gson.JsonPrimitive
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.fileEditor.FileEditor
import com.intellij.openapi.fileEditor.FileEditorLocation
import com.intellij.openapi.fileEditor.FileEditorState
import com.intellij.openapi.util.UserDataHolderBase
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.ui.jcef.JBCefApp
import com.intellij.ui.jcef.JBCefBrowser
import com.intellij.ui.jcef.JBCefBrowserBase
import com.intellij.ui.jcef.JBCefJSQuery
import org.cef.browser.CefBrowser
import org.cef.browser.CefFrame
import org.cef.handler.CefDisplayHandlerAdapter
import org.cef.handler.CefLoadHandlerAdapter
import java.beans.PropertyChangeListener
import javax.swing.JComponent
import javax.swing.JLabel

private const val SERVER_SCRIPT = "$BIOM_VIEWER_REPO_ROOT/pycharm-plugin/backend/server.py"

private const val LOADING_HTML =
    "<html><body style=\"font:13px -apple-system,sans-serif;color:#888;" +
        "display:flex;align-items:center;justify-content:center;height:100vh;margin:0\">" +
        "Loading BIOM table…</body></html>"

private fun errorHtml(message: String): String {
    val escaped = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "<html><body style=\"font:12px ui-monospace,monospace;padding:16px;" +
        "white-space:pre-wrap;color:#c33\">$escaped</body></html>"
}

// The desktop frontend talks to Python as window.pywebview.api.<method>(...),
// so the plugin supplies that exact shape over the JCEF query channel instead
// of the frontend learning a second transport. Every property lookup becomes a
// function, so there is no method list to keep in sync with app.py's Api.
// Dispatched as an event because the frontend waits for 'pywebviewready'
// before its first call -- injection happens at onLoadEnd, after the page's
// inline <script> has already run.
//
// Calls are fire-and-forget: the page keeps its own pending-promise table and
// the Kotlin side settles one later by calling back into __biomSettle. The
// obvious synchronous version -- block the query handler on the backend's
// reply -- stalls whatever CEF thread the handler runs on, and the browser
// then doesn't repaint until the next input event. (Found live: clicking the
// next-page arrow did nothing visible until the mouse moved.)
private fun bridgeJs(query: JBCefJSQuery): String =
    """
    window.__biomPending = {};
    window.__biomNextId = 1;
    window.__biomSettle = function (id, response) {
      var p = window.__biomPending[id];
      if (!p) return;
      delete window.__biomPending[id];
      if (response.ok) p.resolve(response.result); else p.reject(response.error);
    };
    window.pywebview = { api: new Proxy({}, { get: function (_target, name) {
      return function () {
        var args = Array.prototype.slice.call(arguments);
        var id = window.__biomNextId++;
        var payload = JSON.stringify({ id: id, method: String(name), args: args });
        return new Promise(function (resolve, reject) {
          window.__biomPending[id] = { resolve: resolve, reject: reject };
          ${query.inject(
        "payload",
        "function(){}",
        "function(error_code, error_message){ window.__biomSettle(id, {ok:false, error:error_message}); }",
    )}
        });
      };
    }}) };
    window.dispatchEvent(new Event('pywebviewready'));
    """.trimIndent()

private fun errorResponse(cause: Throwable?): JsonObject = JsonObject().apply {
    addProperty("ok", false)
    addProperty("error", cause?.message ?: cause?.toString() ?: "backend request failed")
}

// JSON.parse of a string literal rather than inlining the object literal
// directly: the payload carries arbitrary table content, and a raw paste
// would break on anything the JS parser reads differently from JSON.
private fun settle(cefBrowser: CefBrowser, callId: Int, response: JsonObject) {
    val literal = JsonPrimitive(response.toString()).toString()
    cefBrowser.executeJavaScript(
        "window.__biomSettle($callId, JSON.parse($literal));",
        cefBrowser.url,
        0,
    )
}

class BiomFileEditor(private val file: VirtualFile) : UserDataHolderBase(), FileEditor {

    private var backend: BiomBackendProcess? = null

    // The page is the desktop app's own HTML, fetched from the backend rather
    // than bundled here, so the plugin can't drift from the native viewer.
    // It arrives asynchronously (the backend parses the .biom file first), so
    // the browser shows LOADING_HTML until then -- and onLoadEnd must ignore
    // that first, scriptless load rather than inject a bridge into it.
    @Volatile
    private var appPageLoaded = false

    private val component: JComponent = buildComponent()

    private fun buildComponent(): JComponent {
        if (!JBCefApp.isSupported()) {
            return JLabel("JCEF not supported on this PyCharm install")
        }
        val browser = JBCefBrowser()
        val query = JBCefJSQuery.create(browser as JBCefBrowserBase)
        query.addHandler { requestJson ->
            val request = JsonParser.parseString(requestJson).asJsonObject
            val callId = request["id"].asInt
            val params = JsonObject().apply { add("args", request["args"]) }
            try {
                backend!!.request(request["method"].asString, params)
                    .whenComplete { response, failure ->
                        settle(browser.cefBrowser, callId, response ?: errorResponse(failure))
                    }
            } catch (e: Exception) {
                settle(browser.cefBrowser, callId, errorResponse(e))
            }
            // Answer the query immediately with nothing: the real result comes
            // back later through __biomSettle (see bridgeJs). Closing the query
            // here rather than returning null keeps CEF from holding it open.
            JBCefJSQuery.Response("")
        }

        browser.jbCefClient.addLoadHandler(object : CefLoadHandlerAdapter() {
            override fun onLoadEnd(cefBrowser: CefBrowser, frame: CefFrame, httpStatusCode: Int) {
                if (!appPageLoaded) return
                cefBrowser.executeJavaScript(bridgeJs(query), cefBrowser.url, 0)
            }
        }, browser.cefBrowser)

        // Pipes the page's console into this process's stdout (visible in
        // idea.log) -- the only way to see viewer.html's own errors, since a
        // JCEF page has no user-facing devtools shortcut in production.
        browser.jbCefClient.addDisplayHandler(object : CefDisplayHandlerAdapter() {
            override fun onConsoleMessage(
                cefBrowser: CefBrowser,
                level: org.cef.CefSettings.LogSeverity,
                message: String,
                source: String,
                line: Int,
            ): Boolean {
                println("[viewerJS] $message ($source:$line)")
                return false
            }
        }, browser.cefBrowser)

        val process = BiomBackendProcess(BiomEnvironment.pythonExecutable(), SERVER_SCRIPT, file.path)
        backend = process
        browser.loadHTML(LOADING_HTML)
        process.request("page", JsonObject()).thenAccept { response ->
            val html = if (response["ok"]?.asBoolean == true) {
                response["result"].asString
            } else {
                errorHtml(response["error"]?.asString ?: "backend failed to start")
            }
            ApplicationManager.getApplication().invokeLater {
                appPageLoaded = true
                browser.loadHTML(html)
            }
        }
        return browser.component
    }

    override fun getComponent(): JComponent = component
    override fun getPreferredFocusedComponent(): JComponent = component
    override fun getName() = "BiomViewer"
    override fun setState(state: FileEditorState) {}
    override fun isModified() = false
    override fun isValid() = true
    override fun addPropertyChangeListener(listener: PropertyChangeListener) {}
    override fun removePropertyChangeListener(listener: PropertyChangeListener) {}
    override fun getCurrentLocation(): FileEditorLocation? = null
    override fun dispose() {
        backend?.dispose()
    }
    override fun getFile(): VirtualFile = file
}
