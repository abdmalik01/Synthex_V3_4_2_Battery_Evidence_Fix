python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Write-Host "Copy .env.example to .env and add GEMINI_API_KEY (and SERPER_API_KEY for paper search)."
