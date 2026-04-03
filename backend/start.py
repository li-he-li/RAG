"""
Quick-start script for the Legal Similarity Evidence Search system.
Usage: conda run -n legal-search python start.py
"""

import subprocess
import sys
import os

# Ensure we're in the backend directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("=" * 60)
    print("法律文书相似检索系统 - 启动中...")
    print("=" * 60)
    print()
    print("API 地址: http://localhost:8000")
    print("API 文档: http://localhost:8000/docs")
    print("前端请打开: frontend/index.html")
    print()
    print("首次启动会自动下载模型，请耐心等待...")
    print()

    subprocess.run(
        [
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload",
        ]
    )
