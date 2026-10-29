@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Джарвис Лайт — установка

echo ============================================================
echo   Джарвис Лайт — офлайн голосовой ассистент без ИИ. Установка
echo ============================================================
echo.

rem ---------- 1. Python 3.10-3.12 ----------
set "PY="
for %%V in (3.12 3.11 3.10) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [!] Не найден Python 3.10-3.12. Установи его с https://www.python.org/downloads/
  echo     и отметь галочку "Add python.exe to PATH". Затем запусти install.bat снова.
  pause
  exit /b 1
)
for /f "delims=" %%i in ('%PY% -c "import sys;print(sys.version.split()[0])"') do set PYVER=%%i
echo [OK] Python %PYVER% (%PY%)

rem ---------- 2. Свободное место ----------
for /f "delims=" %%i in ('powershell -NoProfile -Command "[math]::Round((Get-PSDrive -Name ('%~d0'.Substring(0,1))).Free/1GB,1)"') do set FREEGB=%%i
echo [i] Свободно на диске %~d0 : %FREEGB% ГБ
echo     Нужно примерно: Python-пакеты ~0.7 ГБ, Whisper small ~0.5 ГБ, голос Piper ~0.06 ГБ.
echo     Моделей ИИ нет: Джарвис Лайт не скачивает Ollama и языковые модели.
echo.

rem ---------- 3. venv + зависимости ----------
if not exist ".venv\Scripts\python.exe" (
  echo [..] Создаю виртуальное окружение .venv
  %PY% -m venv .venv || (echo [!] Не удалось создать venv & pause & exit /b 1)
)
set "VPY=%~dp0.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip wheel >nul
echo [..] Ставлю зависимости (несколько минут)...
"%VPY%" -m pip install -r requirements.txt || (echo [!] Ошибка установки пакетов & pause & exit /b 1)
echo [OK] Пакеты установлены

rem ---------- 4. Голос Piper + Whisper ----------
echo [..] Скачиваю голос Piper и модель распознавания Whisper
"%VPY%" scripts\download_models.py || echo [!] Часть моделей не скачалась - повтори install.bat позже

rem ---------- 5. Автозагрузка (включена по умолчанию) ----------
"%VPY%" -c "from jarvis.config import load_config, PROJECT_ROOT; from jarvis.platform_utils import set_autostart; c=load_config(); print('[OK] Автозагрузка включена' if c['autostart'].get('enabled', True) and set_autostart(True, PROJECT_ROOT) else '[i] Автозагрузка выключена')"

echo.
echo ============================================================
echo  Готово! Запуск: run.bat  (окно с голограммой + значок в трее)
echo  Текстовый режим: run_text.bat   Проверка: run.bat --check
echo ============================================================
pause
