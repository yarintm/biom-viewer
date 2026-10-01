package com.biomviewer.plugin

import com.google.gson.JsonObject
import com.google.gson.JsonParser
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

class BiomFileEditor(private val file: VirtualFile) : UserDataHolderBase(), FileEditor {

    private var backend: BiomBackendProcess? = null
    private val component: JComponent = buildComponent()

    private fun buildComponent(): JComponent {
        if (!JBCefApp.isSupported()) {
            return JLabel("JCEF not supported on this PyCharm install")
        }
        val browser = JBCefBrowser()
        val query = JBCefJSQuery.create(browser as JBCefBrowserBase)
        query.addHandler { requestJson ->
            val request = JsonParser.parseString(requestJson).asJsonObject
            val method = request["method"].asString
            val params = request["params"].asJsonObject
            val response = try {
                backend!!.request(method, params).get()
            } catch (e: Exception) {
                JsonObject().apply {
                    addProperty("ok", false)
                    addProperty("error", e.message ?: e.toString())
                }
            }
            JBCefJSQuery.Response(response.toString())
        }

        browser.jbCefClient.addLoadHandler(object : CefLoadHandlerAdapter() {
            override fun onLoadEnd(cefBrowser: CefBrowser, frame: CefFrame, httpStatusCode: Int) {
                // onLoadEnd fires only after the page's own inline <script> has
                // already run synchronously during parse -- so viewer.html must
                // not call biomRequest at load time, only after hearing this
                // event. (Found live: the page called it immediately and hit
                // "window.biomRequest is not a function" before this ever ran.)
                val bridgeJs = "window.biomRequest = function(payload, onSuccess, onFailure) {" +
                    query.inject(
                        "payload",
                        "function(response){ onSuccess(response); }",
                        "function(error_code, error_message){ onFailure(error_message); }",
                    ) +
                    "};" +
                    "window.dispatchEvent(new Event('biomBridgeReady'));"
                cefBrowser.executeJavaScript(bridgeJs, cefBrowser.url, 0)
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

        backend = BiomBackendProcess(BiomEnvironment.pythonExecutable(), SERVER_SCRIPT, file.path)
        browser.loadHTML(loadViewerHtml())
        return browser.component
    }

    private fun loadViewerHtml(): String =
        javaClass.getResourceAsStream("/web/viewer.html")!!.bufferedReader().readText()

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
