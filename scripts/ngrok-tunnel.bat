@echo off
REM Think4U HRMS — 以 ngrok 對外開 HTTPS（手機測試用）
REM 專案伺服器跑在本機 8001（docker 對外埠），故 tunnel 指向 8001。
REM authtoken 已存於 ngrok 設定檔（%LOCALAPPDATA%\ngrok\ngrok.yml），此處不含 token。
REM 固定網域：disgustingly-tendrilly-jacquie.ngrok-free.dev（CSRF_TRUSTED_ORIGINS 已信任 *.ngrok-free.dev）
ngrok http --url=disgustingly-tendrilly-jacquie.ngrok-free.dev 8001
