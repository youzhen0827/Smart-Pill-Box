package com.example.smartpillbox.service;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;
import com.example.smartpillbox.utils.TTSManager;

public class MyFirebaseMessagingService extends FirebaseMessagingService {

    @Override
    public void onMessageReceived(RemoteMessage remoteMessage) {
        // 收到 Django Agent 的背景/即時推播
        if (remoteMessage.getData().size() > 0) {
            String alertType = remoteMessage.getData().get("alert_type");
            String voiceText = remoteMessage.getData().get("voice_text");

            // 當收到 AI Agent 的關懷提醒指令時
            if ("AGENT_VOICE_CARE".equals(alertType) && voiceText != null) {
                // 自動發動語音播報
                TTSManager.getInstance(getApplicationContext()).speak(voiceText);

                // TODO: 這裡也可以同步發送 Notification 跳出提示卡片
            }
        }
    }
}