# Starts all 3 services, each in its own window.
# Run from the project folder: powershell -ExecutionPolicy Bypass -File .\start_all.ps1
$root = $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\task1-knowledge-brain'; .\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000"
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\task2-inbox-agent'; npm run dev -- -p 3456"
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\task3-meeting-to-scope'; .\.venv\Scripts\python.exe -m streamlit run streamlit_app.py --server.port 8501"
Write-Host "Task 1: http://127.0.0.1:8000"
Write-Host "Task 2: http://127.0.0.1:3456"
Write-Host "Task 3: http://127.0.0.1:8501"