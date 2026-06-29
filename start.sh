#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -d .venv ] && source .venv/bin/activate
echo "Telefon/boshqa qurilma uchun: http://<KOMPYUTER_IP>:8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
