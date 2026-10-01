package com.biomviewer.plugin

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

// One process per open editor tab, matching the native app's one-Api-per-window
// model -- simpler than multiplexing several files over a shared backend, and
// personal-tool scale (a handful of tabs) never makes that cost matter.
class BiomBackendProcess(pythonExe: String, serverScript: String, biomPath: String) {
    private val process = ProcessBuilder(pythonExe, serverScript, biomPath)
        .redirectErrorStream(false)
        .start()
    private val writer = OutputStreamWriter(process.outputStream)
    private val nextId = AtomicInteger(1)
    private val pending = ConcurrentHashMap<Int, CompletableFuture<JsonObject>>()
    private val readerThread = Thread {
        val reader = BufferedReader(InputStreamReader(process.inputStream))
        reader.forEachLine { line ->
            if (line.isBlank()) return@forEachLine
            val obj = JsonParser.parseString(line).asJsonObject
            val id = obj["id"].asInt
            pending.remove(id)?.complete(obj)
        }
    }.apply { isDaemon = true; start() }

    fun request(method: String, params: JsonObject): CompletableFuture<JsonObject> {
        val id = nextId.getAndIncrement()
        val future = CompletableFuture<JsonObject>()
        pending[id] = future
        val req = JsonObject().apply {
            addProperty("id", id)
            addProperty("method", method)
            add("params", params)
        }
        synchronized(writer) {
            writer.write(req.toString() + "\n")
            writer.flush()
        }
        return future
    }

    fun dispose() {
        process.destroy()
    }
}
