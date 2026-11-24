package com.example.smartpillbox.utils;

import android.content.Context;
import android.speech.tts.TextToSpeech;
import java.util.Locale;

public class TTSManager {
    private static TTSManager instance;
    private TextToSpeech tts;
    private boolean isInitialized = false;

    private TTSManager(Context context) {
        tts = new TextToSpeech(context.getApplicationContext(), status -> {
            if (status == TextToSpeech.SUCCESS) {
                int result = tts.setLanguage(Locale.TAIWAN); // 設定台灣繁體中文
                if (result != TextToSpeech.LANG_MISSING_DATA && result != TextToSpeech.LANG_NOT_SUPPORTED) {
                    isInitialized = true;
                    tts.setSpeechRate(0.85f); // 語速稍微調慢一點，方便長輩聆聽
                }
            }
        });
    }

    public static synchronized TTSManager getInstance(Context context) {
        if (instance == null) {
            instance = new TTSManager(context);
        }
        return instance;
    }

    public void speak(String text) {
        if (isInitialized && tts != null) {
            tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "AgentVoiceUtterance");
        }
    }

    public void stop() {
        if (tts != null) {
            tts.stop();
        }
    }
}