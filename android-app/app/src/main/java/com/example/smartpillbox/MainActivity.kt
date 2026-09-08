@file:Suppress("DEPRECATION")

package com.example.smartpillbox

import android.Manifest
import android.app.AlertDialog
import android.app.DatePickerDialog
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import android.view.Gravity
import android.view.View
import android.widget.ArrayAdapter
import android.widget.AdapterView
import android.widget.Button
import android.widget.EditText
import android.widget.Spinner
import android.widget.TabHost
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity(), TextToSpeech.OnInitListener {

    companion object {
        private const val PREFS_NAME = "smart_medicine_box_api"
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_API_TOKEN = "api_token"
        private const val KEY_USER_NAME = "user_name"
        private const val KEY_USER_AGE = "user_age"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_ADD_MEDICINE = "add_medicine"
        private const val KEY_ADD_DOSE = "add_dose"
        private const val KEY_ADD_HINT = "add_hint"
        private const val KEY_ADD_DATE = "add_date"
        private const val KEY_ADD_TIME = "add_time"
        private const val KEY_ADD_SLOT = "add_slot"
        private const val KEY_SCHEDULE_MEDICINE = "schedule_medicine"
        private const val KEY_SCHEDULE_DOSE = "schedule_dose"
        private const val KEY_SCHEDULE_HINT = "schedule_hint"
        private const val KEY_SCHEDULE_TIME = "schedule_time"
        private const val KEY_SCHEDULE_SLOT = "schedule_slot"
        private const val KEY_SCHEDULE_WEEKDAYS = "schedule_weekdays"

        private const val DEFAULT_BASE_URL = "http://10.0.2.2:8000/api/v1/"
        private const val DEFAULT_TOKEN = "smartpill-dev-token"
        private const val DEFAULT_DEVICE = "pillbox-01"
        private const val REQUIRED_UI_REVISION = 6

        private const val REQUEST_SPEECH = 1201
        private const val REQUEST_RECORD_AUDIO = 1202
    }

    private lateinit var prefs: SharedPreferences
    private val executor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val selectedDate: Calendar = Calendar.getInstance()

    private lateinit var tabHost: TabHost
    private lateinit var tvHeaderTime: TextView
    private lateinit var tvHeaderConnection: TextView

    private lateinit var tvStatTotal: TextView
    private lateinit var tvStatTaken: TextView
    private lateinit var tvStatPending: TextView
    private lateinit var tvStatMissed: TextView
    private lateinit var tvTodayStatus: TextView
    private lateinit var recyclerView: RecyclerView
    private lateinit var adapter: ReminderAdapter
    private lateinit var slotViews: List<TextView>
    private lateinit var tvAgentStatus: TextView
    private lateinit var recyclerAgentList: RecyclerView
    private lateinit var agentAdapter: ReminderAdapter

    private lateinit var editAddUserName: EditText
    private lateinit var editAddAge: EditText
    private lateinit var editAddMedicine: EditText
    private lateinit var btnVoiceAddMedicine: Button
    private lateinit var editAddDate: EditText
    private lateinit var editAddTime: EditText
    private lateinit var editAddDose: EditText
    private lateinit var editAddHint: EditText
    private lateinit var btnVoiceAddHint: Button
    private lateinit var btnPickAddDate: Button
    private lateinit var btnPickAddTime: Button
    private lateinit var btnPickAddSlot: Button
    private lateinit var editAddDeviceId: EditText
    private lateinit var btnCreateReminder: Button
    private lateinit var tvCreateStatus: TextView

    private lateinit var editScheduleUserName: EditText
    private lateinit var editScheduleAge: EditText
    private lateinit var editScheduleMedicine: EditText
    private lateinit var btnVoiceScheduleMedicine: Button
    private lateinit var editScheduleTime: EditText
    private lateinit var btnPickScheduleTime: Button
    private lateinit var btnPickScheduleSlot: Button
    private lateinit var btnPickScheduleWeekdays: Button
    private lateinit var editScheduleDose: EditText
    private lateinit var editScheduleHint: EditText
    private lateinit var btnVoiceScheduleHint: Button
    private lateinit var editScheduleDeviceId: EditText
    private lateinit var btnSaveSchedule: Button
    private lateinit var btnClearSchedule: Button
    private lateinit var btnReloadSchedules: Button
    private lateinit var tvScheduleStatus: TextView
    private lateinit var recyclerScheduleList: RecyclerView
    private lateinit var scheduleAdapter: ScheduleAdapter

    private lateinit var editQaDrug: EditText
    private lateinit var editQaQuestion: EditText
    private lateinit var spinnerQaPrompt: Spinner
    private lateinit var spinnerQaLanguage: Spinner
    private lateinit var btnAskQa: Button
    private lateinit var btnSpeakAnswer: Button
    private lateinit var tvQaStatus: TextView
    private lateinit var tvQaAnswer: TextView
    private lateinit var tvQaEvidence: TextView

    private lateinit var editBaseUrl: EditText
    private lateinit var editApiToken: EditText
    private lateinit var editDefaultUser: EditText
    private lateinit var editDefaultDevice: EditText
    private lateinit var tvSettingsStatus: TextView
    private lateinit var spinnerSensorSlot: Spinner
    private lateinit var tvSensorStatus: TextView

    private var tts: TextToSpeech? = null
    private lateinit var medicationEducationAgent: StandaloneMedicationAgent
    private var ttsReady = false
    private var latestAnswer = ""
    private var selectedAddHour = 8
    private var selectedAddMinute = 0
    private var selectedAddSlot = 1
    private var selectedScheduleHour = 8
    private var selectedScheduleMinute = 0
    private var selectedScheduleSlot = 1
    private var selectedScheduleWeekdays = linkedSetOf(1, 2, 3, 4, 5, 6, 7)
    private var editingScheduleId: Int? = null
    private var pendingSpeechTarget = SpeechTarget.QA_QUESTION

    private enum class SpeechTarget {
        QA_QUESTION,
        ADD_MEDICINE,
        ADD_HINT,
        SCHEDULE_MEDICINE,
        SCHEDULE_HINT
    }

    private val clockRunnable = object : Runnable {
        override fun run() {
            updateHeaderClock()
            mainHandler.postDelayed(this, 1_000L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        medicationEducationAgent = StandaloneMedicationAgent(applicationContext)
        bindViews()
        setupTabs()
        setupSpinners()
        setupReminderList()
        loadSavedSettings()
        setupDateTimeFields()
        setupActions()

        tts = TextToSpeech(this, this)
        mainHandler.post(clockRunnable)
        testConnection()
        loadTodayReminders()
        loadSchedules()
    }

    private fun bindViews() {
        tabHost = findViewById(android.R.id.tabhost)
        tvHeaderTime = findViewById(R.id.tvHeaderTime)
        tvHeaderConnection = findViewById(R.id.tvHeaderConnection)

        tvStatTotal = findViewById(R.id.tvStatTotal)
        tvStatTaken = findViewById(R.id.tvStatTaken)
        tvStatPending = findViewById(R.id.tvStatPending)
        tvStatMissed = findViewById(R.id.tvStatMissed)
        tvTodayStatus = findViewById(R.id.tvTodayStatus)
        recyclerView = findViewById(R.id.recyclerReminderList)
        slotViews = listOf(
            findViewById(R.id.tvSlot1), findViewById(R.id.tvSlot2),
            findViewById(R.id.tvSlot3)
        )
        tvAgentStatus = findViewById(R.id.tvAgentStatus)
        recyclerAgentList = findViewById(R.id.recyclerAgentList)

        editAddUserName = findViewById(R.id.editAddUserName)
        editAddAge = findViewById(R.id.editAddAge)
        editAddMedicine = findViewById(R.id.editAddMedicine)
        btnVoiceAddMedicine = findViewById(R.id.btnVoiceAddMedicine)
        editAddDate = findViewById(R.id.editAddDate)
        editAddTime = findViewById(R.id.editAddTime)
        editAddDose = findViewById(R.id.editAddDose)
        editAddHint = findViewById(R.id.editAddHint)
        btnVoiceAddHint = findViewById(R.id.btnVoiceAddHint)
        btnPickAddDate = findViewById(R.id.btnPickAddDate)
        btnPickAddTime = findViewById(R.id.btnPickAddTime)
        btnPickAddSlot = findViewById(R.id.btnPickAddSlot)
        editAddDeviceId = findViewById(R.id.editAddDeviceId)
        btnCreateReminder = findViewById(R.id.btnCreateReminder)
        tvCreateStatus = findViewById(R.id.tvCreateStatus)

        editScheduleUserName = findViewById(R.id.editScheduleUserName)
        editScheduleAge = findViewById(R.id.editScheduleAge)
        editScheduleMedicine = findViewById(R.id.editScheduleMedicine)
        btnVoiceScheduleMedicine = findViewById(R.id.btnVoiceScheduleMedicine)
        editScheduleTime = findViewById(R.id.editScheduleTime)
        btnPickScheduleTime = findViewById(R.id.btnPickScheduleTime)
        btnPickScheduleSlot = findViewById(R.id.btnPickScheduleSlot)
        btnPickScheduleWeekdays = findViewById(R.id.btnPickScheduleWeekdays)
        editScheduleDose = findViewById(R.id.editScheduleDose)
        editScheduleHint = findViewById(R.id.editScheduleHint)
        btnVoiceScheduleHint = findViewById(R.id.btnVoiceScheduleHint)
        editScheduleDeviceId = findViewById(R.id.editScheduleDeviceId)
        btnSaveSchedule = findViewById(R.id.btnSaveSchedule)
        btnClearSchedule = findViewById(R.id.btnClearSchedule)
        btnReloadSchedules = findViewById(R.id.btnReloadSchedules)
        tvScheduleStatus = findViewById(R.id.tvScheduleStatus)
        recyclerScheduleList = findViewById(R.id.recyclerScheduleList)

        editQaDrug = findViewById(R.id.editQaDrug)
        editQaQuestion = findViewById(R.id.editQaQuestion)
        spinnerQaPrompt = findViewById(R.id.spinnerQaPrompt)
        spinnerQaLanguage = findViewById(R.id.spinnerQaLanguage)
        btnAskQa = findViewById(R.id.btnAskQa)
        btnSpeakAnswer = findViewById(R.id.btnSpeakAnswer)
        tvQaStatus = findViewById(R.id.tvQaStatus)
        tvQaAnswer = findViewById(R.id.tvQaAnswer)
        tvQaEvidence = findViewById(R.id.tvQaEvidence)

        editBaseUrl = findViewById(R.id.editBaseUrl)
        editApiToken = findViewById(R.id.editApiToken)
        editDefaultUser = findViewById(R.id.editDefaultUser)
        editDefaultDevice = findViewById(R.id.editDefaultDevice)
        tvSettingsStatus = findViewById(R.id.tvSettingsStatus)
        spinnerSensorSlot = findViewById(R.id.spinnerSensorSlot)
        tvSensorStatus = findViewById(R.id.tvSensorStatus)
    }

    private fun setupTabs() {
        tabHost.setup()
        addTab("today", "今日任務", R.id.tabToday)
        addTab("add", "臨時服藥", R.id.tabAdd)
        addTab("schedule", "固定排程", R.id.tabSchedule)
        addTab("agent", "Agent 追蹤", R.id.tabAgent)
        addTab("qa", "語音衛教", R.id.tabQa)
        addTab("settings", "連線設定", R.id.tabSettings)
        tabHost.currentTab = 0
        styleTabs()
        tabHost.setOnTabChangedListener {
            styleTabs()
            if (it == "today") loadTodayReminders()
            if (it == "schedule") loadSchedules()
            if (it == "agent") loadAgentTracking()
        }
    }

    private fun addTab(tag: String, label: String, contentId: Int) {
        val indicator = TextView(this).apply {
            text = label
            gravity = Gravity.CENTER
            setPadding(dp(18), dp(14), dp(18), dp(14))
            setTextColor(ContextCompat.getColor(this@MainActivity, R.color.topbar_blue))
            textSize = 14f
            minWidth = dp(94)
        }
        tabHost.addTab(tabHost.newTabSpec(tag).setIndicator(indicator).setContent(contentId))
    }

    private fun styleTabs() {
        for (i in 0 until tabHost.tabWidget.tabCount) {
            val selected = i == tabHost.currentTab
            val child = tabHost.tabWidget.getChildAt(i)
            val palette = intArrayOf(
                R.color.palette_mint,
                R.color.palette_blue,
                R.color.palette_aqua,
                R.color.palette_sage,
                R.color.palette_plum
            )
            child.setBackgroundColor(
                ContextCompat.getColor(this, if (selected) R.color.palette_plum else palette[i % palette.size])
            )
            (child as? TextView)?.setTextColor(
                ContextCompat.getColor(this, if (selected) android.R.color.white else R.color.text_primary)
            )
            child.alpha = 1f
        }
    }

    private fun setupSpinners() {
        val slotLabels = SlotLabels.optionLabels()
        spinnerSensorSlot.adapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_item,
            slotLabels
        ).apply { setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }

        val languages = listOf(
            "淺白繁體中文語音",
            "台語語音偏好（不支援時改用繁中）"
        )
        spinnerQaLanguage.adapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_item,
            languages
        ).apply { setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }

        val commonQuestions = listOf(
            "選擇常見問題",
            "這顆藥是做什麼的？",
            "這顆藥有哪些副作用？",
            "這顆藥要怎麼吃？劑量是多少？",
            "這顆藥可以和其他藥一起吃嗎？",
            "吃這顆藥有哪些事情要注意？",
            "忘記吃這顆藥時該怎麼辦？"
        )
        spinnerQaPrompt.adapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_item,
            commonQuestions
        ).apply { setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }
        spinnerQaPrompt.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (position > 0) editQaQuestion.setText(commonQuestions[position])
            }

            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
        }
    }

    private fun setupReminderList() {
        adapter = ReminderAdapter(
            onTaken = { reminder -> confirmTaken(reminder) },
            onDelete = { reminder -> confirmDelete(reminder) }
        )
        recyclerView.layoutManager = LinearLayoutManager(this)
        recyclerView.adapter = adapter

        agentAdapter = ReminderAdapter(
            onTaken = { reminder -> confirmTaken(reminder) },
            onDelete = { reminder -> confirmDelete(reminder) }
        )
        recyclerAgentList.layoutManager = LinearLayoutManager(this)
        recyclerAgentList.adapter = agentAdapter

        scheduleAdapter = ScheduleAdapter(
            onEdit = { schedule -> editSchedule(schedule) },
            onDelete = { schedule -> confirmDeleteSchedule(schedule) }
        )
        recyclerScheduleList.layoutManager = LinearLayoutManager(this)
        recyclerScheduleList.adapter = scheduleAdapter
    }

    private fun loadSavedSettings() {
        val baseUrl = prefs.getString(KEY_BASE_URL, DEFAULT_BASE_URL) ?: DEFAULT_BASE_URL
        val token = prefs.getString(KEY_API_TOKEN, DEFAULT_TOKEN) ?: DEFAULT_TOKEN
        val userName = prefs.getString(KEY_USER_NAME, "") ?: ""
        val age = prefs.getString(KEY_USER_AGE, "") ?: ""
        val deviceId = prefs.getString(KEY_DEVICE_ID, DEFAULT_DEVICE) ?: DEFAULT_DEVICE

        editBaseUrl.setText(baseUrl)
        editApiToken.setText(token)
        editDefaultUser.setText(userName)
        editDefaultDevice.setText(deviceId)

        editAddUserName.setText(userName)
        editAddAge.setText(age)
        editAddDeviceId.setText(deviceId)
        editAddMedicine.setText(prefs.getString(KEY_ADD_MEDICINE, "") ?: "")
        editAddDose.setText(prefs.getString(KEY_ADD_DOSE, "1") ?: "1")
        editAddHint.setText(prefs.getString(KEY_ADD_HINT, "記得吃藥喔！") ?: "記得吃藥喔！")

        editScheduleUserName.setText(userName)
        editScheduleAge.setText(age)
        editScheduleDeviceId.setText(deviceId)
        editScheduleMedicine.setText(prefs.getString(KEY_SCHEDULE_MEDICINE, "") ?: "")
        editScheduleDose.setText(prefs.getString(KEY_SCHEDULE_DOSE, "1") ?: "1")
        editScheduleHint.setText(prefs.getString(KEY_SCHEDULE_HINT, "飯後服用") ?: "飯後服用")
    }

    private fun setupDateTimeFields() {
        selectedDate.time = Date()
        val savedDate = prefs.getString(KEY_ADD_DATE, "") ?: ""
        if (savedDate.isNotBlank()) {
            try {
                selectedDate.time = SimpleDateFormat("yyyy-MM-dd", Locale.US).parse(savedDate) ?: Date()
            } catch (_: Exception) {
                selectedDate.time = Date()
            }
        }
        val now = Calendar.getInstance()
        val addTime = prefs.getString(KEY_ADD_TIME, "") ?: ""
        val scheduleTime = prefs.getString(KEY_SCHEDULE_TIME, "") ?: ""
        setTimeFromText(addTime, isSchedule = false, defaultHour = now.get(Calendar.HOUR_OF_DAY), defaultMinute = now.get(Calendar.MINUTE))
        setTimeFromText(scheduleTime, isSchedule = true, defaultHour = 8, defaultMinute = 0)
        selectedAddSlot = prefs.getInt(KEY_ADD_SLOT, 1).coerceIn(1, SlotLabels.SLOT_COUNT)
        selectedScheduleSlot = prefs.getInt(KEY_SCHEDULE_SLOT, 1).coerceIn(1, SlotLabels.SLOT_COUNT)
        selectedScheduleWeekdays = parseWeekdays(prefs.getString(KEY_SCHEDULE_WEEKDAYS, "1,2,3,4,5,6,7") ?: "1,2,3,4,5,6,7")

        updateDateField()
        updateTimeFields()
        updateSlotButtons()
        updateWeekdayButton()

        editAddDate.setOnClickListener {
            showDateChoices()
        }
        btnPickAddDate.setOnClickListener { showDateChoices() }
        editAddTime.setOnClickListener { showTimeChoices(isSchedule = false) }
        btnPickAddTime.setOnClickListener { showTimeChoices(isSchedule = false) }
        btnPickAddSlot.setOnClickListener { showSlotChoices(isSchedule = false) }
        editScheduleTime.setOnClickListener { showTimeChoices(isSchedule = true) }
        btnPickScheduleTime.setOnClickListener { showTimeChoices(isSchedule = true) }
        btnPickScheduleSlot.setOnClickListener { showSlotChoices(isSchedule = true) }
        btnPickScheduleWeekdays.setOnClickListener { showWeekdayChoices() }
    }

    private fun setupActions() {
        findViewById<Button>(R.id.btnRefresh).setOnClickListener { loadTodayReminders() }
        btnCreateReminder.setOnClickListener { createReminder() }
        btnSaveSchedule.setOnClickListener { saveSchedule() }
        btnClearSchedule.setOnClickListener { clearScheduleForm() }
        btnReloadSchedules.setOnClickListener { loadSchedules() }

        btnVoiceAddMedicine.setOnClickListener { requestSpeechInput(SpeechTarget.ADD_MEDICINE) }
        btnVoiceAddHint.setOnClickListener { requestSpeechInput(SpeechTarget.ADD_HINT) }
        btnVoiceScheduleMedicine.setOnClickListener { requestSpeechInput(SpeechTarget.SCHEDULE_MEDICINE) }
        btnVoiceScheduleHint.setOnClickListener { requestSpeechInput(SpeechTarget.SCHEDULE_HINT) }
        findViewById<Button>(R.id.btnSpeechInput).setOnClickListener { requestSpeechInput(SpeechTarget.QA_QUESTION) }
        btnAskQa.setOnClickListener { askMedicationQuestion() }
        btnSpeakAnswer.setOnClickListener { speakLatestAnswer() }

        findViewById<Button>(R.id.btnSaveSettings).setOnClickListener {
            saveSettings()
            toast("連線設定已儲存")
        }
        findViewById<Button>(R.id.btnTestConnection).setOnClickListener { testConnection() }
        findViewById<Button>(R.id.btnOpenRegister).setOnClickListener { openAccountPage("register/") }
        findViewById<Button>(R.id.btnOpenLogin).setOnClickListener { openAccountPage("accounts/login/") }
        findViewById<Button>(R.id.btnForgotPassword).setOnClickListener {
            openAccountPage("accounts/password_reset/")
        }
        findViewById<Button>(R.id.btnSendSensorOpen).setOnClickListener { sendSensorOpenEvent() }
    }

    private fun openAccountPage(path: String) {
        saveSettings()
        val url = apiClient().webRoot() + path.removePrefix("/")
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (_: Exception) {
            toast("無法開啟網頁，請確認連線網址。")
        }
    }

    private fun saveSettings() {
        val normalizedBase = ApiClient.normalizeApiBase(editBaseUrl.text.toString())
        val userName = editDefaultUser.text.toString().trim()
        val deviceId = editDefaultDevice.text.toString().trim().ifBlank { DEFAULT_DEVICE }
        editBaseUrl.setText(normalizedBase)
        editDefaultDevice.setText(deviceId)

        prefs.edit()
            .putString(KEY_BASE_URL, normalizedBase)
            .putString(KEY_API_TOKEN, editApiToken.text.toString().trim())
            .putString(KEY_USER_NAME, userName)
            .putString(KEY_USER_AGE, editAddAge.text.toString().trim().ifBlank { editScheduleAge.text.toString().trim() })
            .putString(KEY_DEVICE_ID, deviceId)
            .apply()

        if (editAddUserName.text.toString().isBlank()) editAddUserName.setText(userName)
        if (editAddDeviceId.text.toString().isBlank()) editAddDeviceId.setText(deviceId)
        if (editScheduleUserName.text.toString().isBlank()) editScheduleUserName.setText(userName)
        if (editScheduleDeviceId.text.toString().isBlank()) editScheduleDeviceId.setText(deviceId)
    }

    private fun apiClient(): ApiClient = ApiClient(
        editBaseUrl.text.toString(),
        editApiToken.text.toString().trim()
    )

    private fun loadTodayReminders() {
        val userName = editDefaultUser.text.toString().trim()
            .ifBlank { editAddUserName.text.toString().trim() }
        if (userName.isBlank()) {
            tvTodayStatus.text = "請先到「連線設定」填入預設長輩姓名。"
            adapter.submitList(emptyList())
            updateDashboard(emptyList())
            return
        }

        val date = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        tvTodayStatus.text = "正在讀取 Django 今日服藥任務…"
        executeApi(
            task = { apiClient().reminders(userName, date) },
            onSuccess = { response ->
                val items = parseReminderArray(response.optJSONArray("results"))
                adapter.submitList(items)
                updateDashboard(items)
                tvTodayStatus.text = if (items.isEmpty()) {
                    "$userName 今天尚無服藥任務。可由 App 新增臨時服藥，或建立固定排程。"
                } else {
                    "已同步 ${items.size} 筆；資料來源為 Django API。"
                }
                tvHeaderConnection.text = "Django API：已連線 · $userName"
            },
            onError = { message ->
                adapter.submitList(emptyList())
                updateDashboard(emptyList())
                tvTodayStatus.text = connectionMessage(message)
                tvHeaderConnection.text = "Django API：連線失敗"
            }
        )
    }

    private fun parseReminderArray(array: JSONArray?): List<ReminderItem> {
        if (array == null) return emptyList()
        val result = mutableListOf<ReminderItem>()
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val parsed = ReminderItem.fromJson(item)
            if (parsed.slot == null || SlotLabels.isValid(parsed.slot)) result.add(parsed)
        }
        return result
    }

    private fun loadAgentTracking() {
        val userName = editDefaultUser.text.toString().trim()
            .ifBlank { editAddUserName.text.toString().trim() }
        if (userName.isBlank()) {
            tvAgentStatus.text = "請先到連線設定填入照護對象姓名。"
            agentAdapter.submitList(emptyList())
            return
        }
        val date = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        tvAgentStatus.text = "正在讀取今天的 Agent 追蹤進度…"
        executeApi(
            task = { apiClient().reminders(userName, date) },
            onSuccess = { response ->
                val items = parseReminderArray(response.optJSONArray("results"))
                    .filter { it.agentState in setOf("waiting_sensor", "intervened", "missed") }
                agentAdapter.submitList(items)
                tvAgentStatus.text = if (items.isEmpty()) {
                    "今天沒有等待開盒、再次提醒或需要人工確認的任務。"
                } else {
                    "共有 ${items.size} 筆需要追蹤；請查看每筆的追蹤進度與確認依據。"
                }
            },
            onError = { message ->
                agentAdapter.submitList(emptyList())
                tvAgentStatus.text = connectionMessage(message)
            }
        )
    }

    private fun updateDashboard(items: List<ReminderItem>) {
        val taken = items.count { it.status == "已服藥" }
        val missed = items.count { it.status == "漏服" }
        val pending = items.size - taken - missed
        tvStatTotal.text = "${items.size}\n今日任務"
        tvStatTaken.text = "$taken\n已完成"
        tvStatPending.text = "$pending\n追蹤中"
        tvStatMissed.text = "$missed\n需要確認"

        for (slot in 1..SlotLabels.SLOT_COUNT) {
            val slotItems = items.filter { it.slot == slot }
            val view = slotViews[slot - 1]
            if (slotItems.isEmpty()) {
                view.text = SlotLabels.withStatus(slot, "未排程")
                view.setBackgroundResource(R.drawable.pill_box_unknown)
                continue
            }

            val displayStatus = when {
                slotItems.any { it.status == "漏服" } -> "需要確認"
                slotItems.any { it.status != "已服藥" } -> "待確認"
                else -> "已完成"
            }
            view.text = "${SlotLabels.label(slot)}\n$displayStatus\n${slotItems.size} 筆"
            view.setBackgroundResource(
                when (displayStatus) {
                    "已完成" -> R.drawable.pill_box_taken
                    "需要確認" -> R.drawable.pill_box_missed
                    else -> R.drawable.pill_box_pending
                }
            )
        }
    }

    private fun createReminder() {
        val userName = editAddUserName.text.toString().trim()
        val age = editAddAge.text.toString().trim()
        val medicine = editAddMedicine.text.toString().trim()
        val date = editAddDate.text.toString().trim()
        val deviceId = editAddDeviceId.text.toString().trim().ifBlank { DEFAULT_DEVICE }

        if (userName.isBlank() || medicine.isBlank() || date.isBlank()) {
            tvCreateStatus.text = "姓名、藥品名稱與日期為必填。"
            return
        }

        val hour = selectedAddHour
        val minute = selectedAddMinute
        val scheduledDateTime = String.format(Locale.US, "%sT%02d:%02d:00", date, hour, minute)
        val twelveHour = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, hour)
            set(Calendar.MINUTE, minute)
        }
        val scheduledTime = SimpleDateFormat("hh:mm a", Locale.US).format(twelveHour.time)

        val payload = JSONObject()
            .put("user_name", userName)
            .put("user_age", age)
            .put("medicine_name", medicine)
            .put("scheduled_datetime", scheduledDateTime)
            .put("scheduled_time", scheduledTime)
            .put("dose_count", editAddDose.text.toString().trim().ifBlank { "1" })
            .put("reminder_hint", editAddHint.text.toString().trim().ifBlank { "記得吃藥喔！" })
            .put("slot", selectedAddSlot)
            .put("device_id", deviceId)

        btnCreateReminder.isEnabled = false
        tvCreateStatus.text = "正在寫入 Django…"
        saveFormDrafts()
        executeApi(
            task = { apiClient().createReminder(payload) },
            onSuccess = { response ->
                btnCreateReminder.isEnabled = true
                val id = response.optInt("id")
                tvCreateStatus.text = "建立成功，Django 紀錄 ID：$id。"
                prefs.edit()
                    .putString(KEY_USER_NAME, userName)
                    .putString(KEY_USER_AGE, age)
                    .putString(KEY_DEVICE_ID, deviceId)
                    .apply()
                editDefaultUser.setText(userName)
                editDefaultDevice.setText(deviceId)
                tabHost.currentTab = 0
                loadTodayReminders()
            },
            onError = { message ->
                btnCreateReminder.isEnabled = true
                tvCreateStatus.text = message
            }
        )
    }

    private fun loadSchedules() {
        val userName = editScheduleUserName.text.toString().trim()
            .ifBlank { editDefaultUser.text.toString().trim() }
            .ifBlank { editAddUserName.text.toString().trim() }
        if (userName.isBlank()) {
            tvScheduleStatus.text = "請先輸入長輩姓名。"
            scheduleAdapter.submitList(emptyList())
            return
        }
        tvScheduleStatus.text = "正在載入固定排程…"
        executeApi(
            task = { apiClient().schedules(userName) },
            onSuccess = { response ->
                val items = parseScheduleArray(response.optJSONArray("results"))
                scheduleAdapter.submitList(items)
                tvScheduleStatus.text = if (items.isEmpty()) "尚無固定排程。" else "已載入 ${items.size} 筆固定排程。"
            },
            onError = { message ->
                scheduleAdapter.submitList(emptyList())
                tvScheduleStatus.text = message
            }
        )
    }

    private fun parseScheduleArray(array: JSONArray?): List<ScheduleItem> {
        if (array == null) return emptyList()
        val result = mutableListOf<ScheduleItem>()
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val parsed = ScheduleItem.fromJson(item)
            if (SlotLabels.isValid(parsed.slot)) result.add(parsed)
        }
        return result
    }

    private fun saveSchedule() {
        val userName = editScheduleUserName.text.toString().trim()
        val age = editScheduleAge.text.toString().trim()
        val medicine = editScheduleMedicine.text.toString().trim()
        val deviceId = editScheduleDeviceId.text.toString().trim().ifBlank { DEFAULT_DEVICE }
        if (userName.isBlank() || medicine.isBlank()) {
            tvScheduleStatus.text = "長輩姓名與藥品名稱為必填。"
            return
        }

        val payload = JSONObject()
            .put("user_name", userName)
            .put("user_age", age)
            .put("medicine_name", medicine)
            .put("scheduled_time", String.format(Locale.US, "%02d:%02d", selectedScheduleHour, selectedScheduleMinute))
            .put("dose_count", editScheduleDose.text.toString().trim().ifBlank { "1" })
            .put("reminder_hint", editScheduleHint.text.toString().trim().ifBlank { "飯後服用" })
            .put("slot", selectedScheduleSlot)
            .put("period", SlotLabels.period(selectedScheduleSlot))
            .put("weekdays", selectedScheduleWeekdays.joinToString(","))
            .put("device_id", deviceId)
            .put("is_active", true)

        btnSaveSchedule.isEnabled = false
        tvScheduleStatus.text = "正在儲存固定排程…"
        saveFormDrafts()
        val editingId = editingScheduleId
        executeApi(
            task = {
                if (editingId == null) apiClient().createSchedule(payload)
                else apiClient().updateSchedule(editingId, payload)
            },
            onSuccess = {
                btnSaveSchedule.isEnabled = true
                tvScheduleStatus.text = if (editingId == null) "固定排程已新增。" else "固定排程已更新。"
                editingScheduleId = null
                btnSaveSchedule.text = "儲存固定排程"
                editDefaultUser.setText(userName)
                editDefaultDevice.setText(deviceId)
                loadSchedules()
            },
            onError = { message ->
                btnSaveSchedule.isEnabled = true
                tvScheduleStatus.text = message
            }
        )
    }

    private fun editSchedule(schedule: ScheduleItem) {
        editingScheduleId = schedule.id
        editScheduleUserName.setText(schedule.elderName)
        editScheduleAge.setText(if (schedule.elderAge > 0) schedule.elderAge.toString() else "")
        editScheduleMedicine.setText(schedule.medicineName)
        editScheduleDose.setText(schedule.doseCount)
        editScheduleHint.setText(schedule.reminderHint)
        editScheduleDeviceId.setText(schedule.deviceId.ifBlank { DEFAULT_DEVICE })
        selectedScheduleSlot = schedule.slot.coerceIn(1, SlotLabels.SLOT_COUNT)
        selectedScheduleWeekdays = parseWeekdays(schedule.weekdays)
        setTimeFromText(schedule.scheduledTime, isSchedule = true, defaultHour = 8, defaultMinute = 0)
        updateTimeFields()
        updateSlotButtons()
        updateWeekdayButton()
        btnSaveSchedule.text = "更新固定排程"
        tvScheduleStatus.text = "正在編輯 #${schedule.id}。"
    }

    private fun clearScheduleForm() {
        editingScheduleId = null
        btnSaveSchedule.text = "儲存固定排程"
        editScheduleMedicine.setText("")
        editScheduleDose.setText("1")
        editScheduleHint.setText("飯後服用")
        selectedScheduleSlot = 1
        selectedScheduleWeekdays = linkedSetOf(1, 2, 3, 4, 5, 6, 7)
        setTimeFromText("08:00", isSchedule = true, defaultHour = 8, defaultMinute = 0)
        updateTimeFields()
        updateSlotButtons()
        updateWeekdayButton()
        tvScheduleStatus.text = "已切換為新增排程。"
    }

    private fun confirmDeleteSchedule(schedule: ScheduleItem) {
        AlertDialog.Builder(this)
            .setTitle("刪除固定排程")
            .setMessage("確定刪除「${schedule.medicineName}」這筆固定排程？")
            .setNegativeButton("取消", null)
            .setPositiveButton("刪除") { _, _ ->
                tvScheduleStatus.text = "正在刪除固定排程…"
                executeApi(
                    task = { apiClient().deleteSchedule(schedule.id) },
                    onSuccess = { loadSchedules() },
                    onError = { tvScheduleStatus.text = it }
                )
            }
            .show()
    }

    private fun confirmTaken(reminder: ReminderItem) {
        tvTodayStatus.text = "正在更新「${reminder.medicineName}」…"
        executeApi(
            task = { apiClient().markTaken(reminder.id) },
            onSuccess = {
                toast("已同步服藥確認")
                loadTodayReminders()
            },
            onError = { tvTodayStatus.text = it }
        )
    }

    private fun confirmDelete(reminder: ReminderItem) {
        AlertDialog.Builder(this)
            .setTitle("刪除提醒")
            .setMessage("確定刪除「${reminder.medicineName}」這筆 Django 紀錄？")
            .setNegativeButton("取消", null)
            .setPositiveButton("刪除") { _, _ ->
                tvTodayStatus.text = "正在刪除…"
                executeApi(
                    task = { apiClient().deleteReminder(reminder.id) },
                    onSuccess = { loadTodayReminders() },
                    onError = { tvTodayStatus.text = it }
                )
            }
            .show()
    }

    private fun testConnection() {
        saveSettings()
        tvSettingsStatus.text = "正在測試 Django API…"
        executeApi(
            task = { apiClient().health() },
            onSuccess = { response ->
                val count = response.optInt("dataset_documents")
                val service = response.optString("service", "smart-medicine-box")
                val slotCount = response.optInt("slot_count", -1)
                val slots = response.optJSONArray("slots")
                val layout = response.optString("pillbox_layout")
                val uiRevision = response.optInt("ui_revision", -1)
                if (!SlotLabels.healthContractIsThreeSlot(slotCount, slots)
                    || layout != "early-noon-evening-3-slot"
                    || uiRevision != REQUIRED_UI_REVISION
                ) {
                    tvSettingsStatus.text = "後端版本不符：請啟動 6_workflow_smart_medicine_box_Django_re，並確認 API 版本為 6。"
                    tvHeaderConnection.text = "Django API：版本不符（需要第 6 版）"
                    return@executeApi
                }
                tvSettingsStatus.text = "連線成功：$service；第 6 版早／中／晚三格 API 已確認；資料文件 $count 筆。"
                tvHeaderConnection.text = "Django API：已連線 · 第 6 版"
            },
            onError = { message ->
                tvSettingsStatus.text = connectionMessage(message)
                tvHeaderConnection.text = "Django API：連線失敗"
            }
        )
    }

    private fun askMedicationQuestion() {
        val drug = editQaDrug.text.toString().trim()
        val question = editQaQuestion.text.toString().trim()
        if (drug.isBlank() || question.isBlank()) {
            tvQaStatus.text = "藥品名稱與問題都必須填寫。"
            return
        }

        btnAskQa.isEnabled = false
        btnSpeakAnswer.isEnabled = false
        tvQaStatus.text = "APP 正在直接查詢 FDA 公開藥品資料…"
        tvQaAnswer.text = "查詢中…"
        tvQaEvidence.text = "資料證據：查詢中"

        executor.execute {
            try {
                val draft = medicationEducationAgent.fetchDraft(drug, question)
                mainHandler.post {
                    medicationEducationAgent.answerInChinese(
                        draft = draft,
                        onPreparingModel = {
                            tvQaStatus.text = "正在準備手機內中文翻譯模型；第一次使用可能需要一些時間…"
                        },
                        onSuccess = { result ->
                            btnAskQa.isEnabled = true
                            latestAnswer = result.answer
                            tvQaAnswer.text = latestAnswer
                            tvQaEvidence.text = result.evidence
                            btnSpeakAnswer.isEnabled = latestAnswer.isNotBlank()
                            tvQaStatus.text = buildString {
                                append("回答完成；問題類型：${result.questionLabel}")
                                append(if (result.qualityPassed) "；Agent 合理性檢查：通過" else "；Agent 合理性檢查：已攔截")
                                append("；由 APP 直接查詢 FDA")
                                if (result.usedDownloadedModel) append("；已在手機內翻成中文")
                                if (result.fromCache) append("；使用先前儲存的資料")
                            }
                            speakLatestAnswer()
                        },
                        onFailure = { message ->
                            btnAskQa.isEnabled = true
                            tvQaStatus.text = message
                            tvQaAnswer.text = "目前無法取得中文衛教回答。"
                            tvQaEvidence.text = "資料證據：無"
                        }
                    )
                }
            } catch (error: Exception) {
                mainHandler.post {
                    val message = error.message ?: "APP 無法取得藥物資料，請稍後再試。"
                    btnAskQa.isEnabled = true
                    tvQaStatus.text = message
                    tvQaAnswer.text = "查詢失敗。"
                    tvQaEvidence.text = "資料證據：無"
                }
            }
        }
    }

    private fun formatEvidence(array: JSONArray?): String {
        if (array == null || array.length() == 0) {
            return "資料證據：目前不足。請以醫師、藥師或正式藥袋資訊為準。"
        }
        val lines = mutableListOf<String>()
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val source = item.optString("source_label", item.optString("source_type"))
            val drug = item.optString("brand_name").ifBlank { item.optString("generic_name") }
            val ndc = item.optString("product_ndc")
            val section = item.optString("section_label", item.optString("section"))
            val url = item.optString("source_url")
            val identity = listOf(drug, if (ndc.isNotBlank()) "NDC $ndc" else "")
                .filter { it.isNotBlank() }
                .joinToString(" / ")
            lines.add("${i + 1}. $source｜$identity｜$section\n$url")
        }
        return "資料證據（可追溯）：\n" + lines.joinToString("\n\n")
    }

    private fun connectionMessage(message: String): String {
        val base = ApiClient.normalizeApiBase(editBaseUrl.text.toString())
        val hint = if (base.contains("10.0.2.2")) {
            "請確認 Django 已在電腦啟動，Android 模擬器使用 10.0.2.2。"
        } else {
            "實體手機需與電腦連到同一個 Wi-Fi，網址要填電腦的區域網路 IP。"
        }
        return "$message\n$hint"
    }

    private fun showDateChoices() {
        val today = Calendar.getInstance()
        val tomorrow = Calendar.getInstance().apply { add(Calendar.DAY_OF_MONTH, 1) }
        val afterTomorrow = Calendar.getInstance().apply { add(Calendar.DAY_OF_MONTH, 2) }
        val labels = arrayOf(
            "今天 ${formatDate(today)}",
            "明天 ${formatDate(tomorrow)}",
            "後天 ${formatDate(afterTomorrow)}",
            "開啟日曆選擇"
        )
        AlertDialog.Builder(this)
            .setTitle("選擇服藥日期")
            .setItems(labels) { _, which ->
                when (which) {
                    0 -> selectedDate.time = today.time
                    1 -> selectedDate.time = tomorrow.time
                    2 -> selectedDate.time = afterTomorrow.time
                    else -> showCalendarPicker()
                }
                if (which != 3) updateDateField()
            }
            .show()
    }

    private fun showCalendarPicker() {
        DatePickerDialog(
            this,
            { _, year, month, day ->
                selectedDate.set(Calendar.YEAR, year)
                selectedDate.set(Calendar.MONTH, month)
                selectedDate.set(Calendar.DAY_OF_MONTH, day)
                updateDateField()
            },
            selectedDate.get(Calendar.YEAR),
            selectedDate.get(Calendar.MONTH),
            selectedDate.get(Calendar.DAY_OF_MONTH)
        ).show()
    }

    private fun showTimeChoices(isSchedule: Boolean) {
        val labels = arrayOf(
            "08:00 早格",
            "12:00 中格",
            "18:00 晚格",
            "自訂輸入 HH:mm"
        )
        val values = listOf("08:00", "12:00", "18:00")
        AlertDialog.Builder(this)
            .setTitle("選擇服藥時間")
            .setItems(labels) { _, which ->
                if (which < values.size) {
                    setTimeFromText(values[which], isSchedule, 8, 0)
                    updateTimeFields()
                } else {
                    showManualTimeDialog(isSchedule)
                }
            }
            .show()
    }

    private fun showManualTimeDialog(isSchedule: Boolean) {
        val input = EditText(this).apply {
            hint = "例如 08:30"
            setText(if (isSchedule) editScheduleTime.text else editAddTime.text)
            setSingleLine(true)
        }
        AlertDialog.Builder(this)
            .setTitle("輸入服藥時間")
            .setView(input)
            .setNegativeButton("取消", null)
            .setPositiveButton("確定") { _, _ ->
                if (setTimeFromText(input.text.toString(), isSchedule, 8, 0)) {
                    updateTimeFields()
                } else {
                    toast("時間格式請用 HH:mm")
                }
            }
            .show()
    }

    private fun showSlotChoices(isSchedule: Boolean) {
        val labels = SlotLabels.optionLabels().toTypedArray()
        AlertDialog.Builder(this)
            .setTitle("選擇藥盒時段")
            .setItems(labels) { _, which ->
                if (isSchedule) selectedScheduleSlot = which + 1 else selectedAddSlot = which + 1
                updateSlotButtons()
            }
            .show()
    }

    private fun showWeekdayChoices() {
        val labels = arrayOf("1 週一", "2 週二", "3 週三", "4 週四", "5 週五", "6 週六", "7 週日")
        val checked = BooleanArray(7) { selectedScheduleWeekdays.contains(it + 1) }
        AlertDialog.Builder(this)
            .setTitle("選擇執行星期")
            .setMultiChoiceItems(labels, checked) { _, which, isChecked ->
                if (isChecked) selectedScheduleWeekdays.add(which + 1) else selectedScheduleWeekdays.remove(which + 1)
            }
            .setPositiveButton("確定") { _, _ ->
                if (selectedScheduleWeekdays.isEmpty()) selectedScheduleWeekdays.addAll(1..7)
                updateWeekdayButton()
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun setTimeFromText(
        value: String,
        isSchedule: Boolean,
        defaultHour: Int,
        defaultMinute: Int
    ): Boolean {
        val text = value.trim()
        val parts = text.split(":")
        val hour = parts.getOrNull(0)?.toIntOrNull()
        val minute = parts.getOrNull(1)?.take(2)?.toIntOrNull()
        val parsed = hour != null && minute != null && hour in 0..23 && minute in 0..59
        val finalHour = if (parsed) hour ?: defaultHour else defaultHour
        val finalMinute = if (parsed) minute ?: defaultMinute else defaultMinute
        if (isSchedule) {
            selectedScheduleHour = finalHour
            selectedScheduleMinute = finalMinute
        } else {
            selectedAddHour = finalHour
            selectedAddMinute = finalMinute
        }
        return parsed || text.isBlank()
    }

    private fun parseWeekdays(value: String): LinkedHashSet<Int> {
        val days = value.split(",")
            .mapNotNull { it.trim().toIntOrNull() }
            .filter { it in 1..7 }
            .toCollection(linkedSetOf())
        return if (days.isEmpty()) linkedSetOf(1, 2, 3, 4, 5, 6, 7) else days
    }

    private fun updateTimeFields() {
        editAddTime.setText(String.format(Locale.US, "%02d:%02d", selectedAddHour, selectedAddMinute))
        editScheduleTime.setText(String.format(Locale.US, "%02d:%02d", selectedScheduleHour, selectedScheduleMinute))
    }

    private fun updateSlotButtons() {
        btnPickAddSlot.text = SlotLabels.optionLabels()[selectedAddSlot - 1]
        btnPickScheduleSlot.text = SlotLabels.optionLabels()[selectedScheduleSlot - 1]
    }

    private fun updateWeekdayButton() {
        val label = selectedScheduleWeekdays.sorted().joinToString(",")
        btnPickScheduleWeekdays.text = "星期 $label"
    }

    private fun saveFormDrafts() {
        prefs.edit()
            .putString(KEY_USER_NAME, editDefaultUser.text.toString().trim().ifBlank { editAddUserName.text.toString().trim() })
            .putString(KEY_USER_AGE, editAddAge.text.toString().trim().ifBlank { editScheduleAge.text.toString().trim() })
            .putString(KEY_DEVICE_ID, editDefaultDevice.text.toString().trim().ifBlank { editAddDeviceId.text.toString().trim().ifBlank { DEFAULT_DEVICE } })
            .putString(KEY_ADD_MEDICINE, editAddMedicine.text.toString().trim())
            .putString(KEY_ADD_DOSE, editAddDose.text.toString().trim())
            .putString(KEY_ADD_HINT, editAddHint.text.toString().trim())
            .putString(KEY_ADD_DATE, editAddDate.text.toString().trim())
            .putString(KEY_ADD_TIME, editAddTime.text.toString().trim())
            .putInt(KEY_ADD_SLOT, selectedAddSlot)
            .putString(KEY_SCHEDULE_MEDICINE, editScheduleMedicine.text.toString().trim())
            .putString(KEY_SCHEDULE_DOSE, editScheduleDose.text.toString().trim())
            .putString(KEY_SCHEDULE_HINT, editScheduleHint.text.toString().trim())
            .putString(KEY_SCHEDULE_TIME, editScheduleTime.text.toString().trim())
            .putInt(KEY_SCHEDULE_SLOT, selectedScheduleSlot)
            .putString(KEY_SCHEDULE_WEEKDAYS, selectedScheduleWeekdays.sorted().joinToString(","))
            .apply()
    }

    private fun formatDate(calendar: Calendar): String =
        SimpleDateFormat("yyyy-MM-dd", Locale.US).format(calendar.time)

    private fun requestSpeechInput(target: SpeechTarget) {
        pendingSpeechTarget = target
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.RECORD_AUDIO),
                REQUEST_RECORD_AUDIO
            )
            return
        }
        launchSpeechRecognizer()
    }

    private fun launchSpeechRecognizer() {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-TW")
            putExtra(RecognizerIntent.EXTRA_PROMPT, speechPrompt())
        }
        try {
            startActivityForResult(intent, REQUEST_SPEECH)
        } catch (_: Exception) {
            tvQaStatus.text = "此裝置沒有可用的語音辨識服務；可直接打字，或使用 Raspberry Pi 的本機 faster-whisper。"
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_SPEECH && resultCode == RESULT_OK) {
            val results = data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
            val text = results?.firstOrNull().orEmpty()
            if (text.isNotBlank()) {
                applySpeechText(text)
            }
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_RECORD_AUDIO) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
                launchSpeechRecognizer()
            } else {
                tvQaStatus.text = "未授權麥克風，因此無法使用手機語音輸入。"
            }
        }
    }

    private fun speechPrompt(): String = when (pendingSpeechTarget) {
        SpeechTarget.ADD_MEDICINE,
        SpeechTarget.SCHEDULE_MEDICINE -> "請說出藥品名稱"
        SpeechTarget.ADD_HINT,
        SpeechTarget.SCHEDULE_HINT -> "請說出提醒內容，例如飯後服用"
        SpeechTarget.QA_QUESTION -> "請說出你的藥物問題"
    }

    private fun applySpeechText(text: String) {
        when (pendingSpeechTarget) {
            SpeechTarget.ADD_MEDICINE -> {
                editAddMedicine.setText(text)
                tvCreateStatus.text = "語音已填入藥品名稱。"
            }
            SpeechTarget.ADD_HINT -> {
                editAddHint.setText(text)
                tvCreateStatus.text = "語音已填入提醒內容。"
            }
            SpeechTarget.SCHEDULE_MEDICINE -> {
                editScheduleMedicine.setText(text)
                tvScheduleStatus.text = "語音已填入藥品名稱。"
            }
            SpeechTarget.SCHEDULE_HINT -> {
                editScheduleHint.setText(text)
                tvScheduleStatus.text = "語音已填入提醒內容。"
            }
            SpeechTarget.QA_QUESTION -> {
                editQaQuestion.setText(text)
                tvQaStatus.text = "語音已轉為文字，請確認後送出。"
            }
        }
        saveFormDrafts()
    }

    override fun onInit(status: Int) {
        ttsReady = status == TextToSpeech.SUCCESS
        if (ttsReady) {
            tts?.setSpeechRate(0.88f)
            tts?.setPitch(1.0f)
        }
    }

    private fun speakLatestAnswer() {
        if (latestAnswer.isBlank()) return
        if (!ttsReady) {
            tvQaStatus.text = "手機 TTS 尚未就緒。回答文字仍可正常閱讀。"
            return
        }

        val preferTaiwanese = spinnerQaLanguage.selectedItemPosition == 1
        var locale = if (preferTaiwanese) Locale("nan", "TW") else Locale.TRADITIONAL_CHINESE
        var result = tts?.setLanguage(locale) ?: TextToSpeech.LANG_NOT_SUPPORTED
        if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
            locale = Locale.TRADITIONAL_CHINESE
            result = tts?.setLanguage(locale) ?: TextToSpeech.LANG_NOT_SUPPORTED
            if (preferTaiwanese) {
                tvQaStatus.text = "此手機 TTS 沒有台語語音，已改用繁體中文朗讀。"
            }
        }
        if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
            tvQaStatus.text = "此裝置沒有可用的繁體中文／台語 TTS 語音資料。"
            return
        }
        tts?.speak(latestAnswer, TextToSpeech.QUEUE_FLUSH, null, "qa-answer")
    }

    private fun sendSensorOpenEvent() {
        val userName = editDefaultUser.text.toString().trim()
        val deviceId = editDefaultDevice.text.toString().trim().ifBlank { DEFAULT_DEVICE }
        if (userName.isBlank()) {
            tvSensorStatus.text = "請先設定長輩姓名。"
            return
        }

        val payload = JSONObject()
            .put("device_id", deviceId)
            .put("user_name", userName)
            .put("slot", spinnerSensorSlot.selectedItemPosition + 1)
            .put("event_type", "opened")
            .put("detected_at", SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).format(Date()))
            .put("source", "android_manual_test")

        tvSensorStatus.text = "正在送出感測器事件…"
        executeApi(
            task = { apiClient().sendSensorEvent(payload) },
            onSuccess = { response ->
                val matched = response.optJSONObject("matched_reminder")
                tvSensorStatus.text = if (matched == null) {
                    "事件已寫入 Django，但目前沒有符合裝置、時段與時間的未完成提醒。"
                } else {
                    "事件已配對紀錄 #${matched.optInt("id")}：${matched.optString("medicine_name")}，狀態已改為已服藥。"
                }
                loadTodayReminders()
            },
            onError = { tvSensorStatus.text = it }
        )
    }

    private fun updateHeaderClock() {
        tvHeaderTime.text = SimpleDateFormat(
            "yyyy年M月d日 EEEE HH:mm:ss",
            Locale.TAIWAN
        ).format(Date())
    }

    private fun updateDateField() {
        editAddDate.setText(SimpleDateFormat("yyyy-MM-dd", Locale.US).format(selectedDate.time))
    }

    private fun <T> executeApi(
        task: () -> T,
        onSuccess: (T) -> Unit,
        onError: (String) -> Unit
    ) {
        executor.execute {
            try {
                val result = task()
                mainHandler.post { onSuccess(result) }
            } catch (e: Exception) {
                val message = when (e) {
                    is ApiException -> e.message ?: "API 請求失敗"
                    else -> e.message ?: e.javaClass.simpleName
                }
                mainHandler.post { onError(message) }
            }
        }
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    override fun onPause() {
        saveFormDrafts()
        super.onPause()
    }

    override fun onDestroy() {
        mainHandler.removeCallbacks(clockRunnable)
        executor.shutdownNow()
        medicationEducationAgent.close()
        tts?.stop()
        tts?.shutdown()
        super.onDestroy()
    }
}
