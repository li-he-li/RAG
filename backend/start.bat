@echo off
chcp 65001 >nul
echo ==================================================
echo 法律文书相似检索系统 - 启动中...
echo ==================================================
echo.
echo API 地址: http://localhost:8000
echo API 文档: http://localhost:8000/docs
echo 前端页面: frontend/index.html
echo.
echo 首次启动会自动下载模型，请耐心等待...
echo.

cd /d "%~dp0"
conda run -n legal-search python start.py
