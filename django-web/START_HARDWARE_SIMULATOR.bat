@echo off
chcp 65001 >nul
title Smart Pill Box Hardware Simulator
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0esp32_usb\simulated_device.ps1"
pause
