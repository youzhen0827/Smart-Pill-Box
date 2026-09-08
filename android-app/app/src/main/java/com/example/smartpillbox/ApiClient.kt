package com.example.smartpillbox

import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

class ApiException(message: String, val statusCode: Int = -1) : Exception(message)

class ApiClient(baseUrl: String, private val token: String) {
    private val apiBase = normalizeApiBase(baseUrl)

    fun health(): JSONObject = request("health/")

    fun reminders(userName: String, date: String): JSONObject {
        val query = "user_name=${encode(userName)}&date=${encode(date)}"
        return request("reminders/?$query")
    }

    fun createReminder(payload: JSONObject): JSONObject = request("reminders/", "POST", payload)

    fun markTaken(id: Int): JSONObject = request("reminders/$id/taken/", "POST", JSONObject())

    fun deleteReminder(id: Int): JSONObject = request("reminders/$id/delete/", "POST", JSONObject())

    fun schedules(userName: String): JSONObject {
        val query = "user_name=${encode(userName)}"
        return request("schedules/?$query")
    }

    fun createSchedule(payload: JSONObject): JSONObject = request("schedules/", "POST", payload)

    fun updateSchedule(id: Int, payload: JSONObject): JSONObject = request("schedules/$id/", "POST", payload)

    fun deleteSchedule(id: Int): JSONObject = request("schedules/$id/delete/", "POST", JSONObject())

    fun askQuestion(payload: JSONObject): JSONObject = request("qa/ask/", "POST", payload)

    fun sendSensorEvent(payload: JSONObject): JSONObject = request("sensors/events/", "POST", payload)

    fun webRoot(): String {
        val marker = "/api/v1/"
        return if (apiBase.contains(marker)) apiBase.substringBefore(marker) + "/" else apiBase
    }

    private fun request(path: String, method: String = "GET", payload: JSONObject? = null): JSONObject {
        var connection: HttpURLConnection? = null
        try {
            connection = URI(apiBase + path.removePrefix("/")).toURL().openConnection() as HttpURLConnection
            connection.requestMethod = method
            connection.connectTimeout = 10_000
            connection.readTimeout = 25_000
            connection.setRequestProperty("Accept", "application/json")
            if (token.isNotBlank()) {
                connection.setRequestProperty("X-Device-Token", token)
            }
            if (payload != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=UTF-8")
                connection.outputStream.bufferedWriter(StandardCharsets.UTF_8).use { writer ->
                    writer.write(payload.toString())
                }
            }

            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val body = stream?.let {
                BufferedReader(InputStreamReader(it, StandardCharsets.UTF_8)).use { reader ->
                    reader.readText()
                }
            }.orEmpty()

            if (status !in 200..299) {
                val message = try {
                    val error = JSONObject(body)
                    error.optString("error", error.optString("detail", body))
                } catch (_: Exception) {
                    body
                }
                throw ApiException("HTTP $status：${message.ifBlank { "伺服器拒絕請求" }}", status)
            }
            return if (body.isBlank()) JSONObject() else JSONObject(body)
        } catch (e: ApiException) {
            throw e
        } catch (e: Exception) {
            throw ApiException("無法連線到 $apiBase：${e.message ?: e.javaClass.simpleName}")
        } finally {
            connection?.disconnect()
        }
    }

    companion object {
        fun normalizeApiBase(value: String): String {
            var normalized = value.trim()
            if (normalized.isBlank()) normalized = "http://10.0.2.2:8000/api/v1/"
            if (!normalized.startsWith("http://") && !normalized.startsWith("https://")) {
                normalized = "http://$normalized"
            }
            if (!normalized.endsWith("/")) normalized += "/"
            return normalized
        }

        private fun encode(value: String): String =
            URLEncoder.encode(value, StandardCharsets.UTF_8.name())
    }
}
