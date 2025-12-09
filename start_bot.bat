@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "REPO_ROOT=%~dp0"
pushd "%REPO_ROOT%" >nul 2>&1

set "VENV_DIR=%REPO_ROOT%venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_PYW=%VENV_DIR%\Scripts\pythonw.exe"
set "VENV_ACTIVATE=%VENV_DIR%\Scripts\activate.bat"

if exist "%VENV_PY%" (
	echo [INFO] Found existing virtual environment in %VENV_DIR%.
) else (
	echo [INFO] Creating virtual environment in %VENV_DIR%...
	py -3 -m venv "%VENV_DIR%"
	if errorlevel 1 (
		echo [ERROR] Failed to create virtual environment.
		goto :error
	)
)

if exist "%VENV_ACTIVATE%" (
	echo [INFO] Activating virtual environment.
	call "%VENV_ACTIVATE%"
) else (
	echo [ERROR] Could not find activate.bat at %VENV_ACTIVATE%.
	goto :error
)

echo [INFO] Running dependency check (check_requirements.py)...
python "%REPO_ROOT%check_requirements.py"
if errorlevel 1 (
	echo [ERROR] Dependency check failed.
	goto :error
)

set "ENV_PATH=%REPO_ROOT%.env"
if exist "%ENV_PATH%" (
	echo [INFO] .env already exists at %ENV_PATH%.
) else (
	echo [INFO] Creating template .env at %ENV_PATH%.
	(
		echo TWITCH_CLIENT_ID=
		echo TWITCH_APP_SECRET=
		echo BOT_ID=
		echo OWNER_ID=
		echo ELEVENLABS_API_KEY=
		echo OPENAI_API_KEY=
		echo AZURE_TTS_KEY=
		echo AZURE_TTS_REGION=
		echo DISCORD_TOKEN=
	)>"%ENV_PATH%"
)

call :LoadEnvVars

set "HAS_ERRORS="

if "!TWITCH_CLIENT_ID!"=="" (
	echo [ERROR] Missing TWITCH_CLIENT_ID in %ENV_PATH%.
	echo 	Follow the OAuth setup steps in readme.txt to populate this value.
	set "HAS_ERRORS=1"
)

if "!TWITCH_APP_SECRET!"=="" (
	echo [ERROR] Missing TWITCH_APP_SECRET in %ENV_PATH%.
	echo 	Follow the OAuth setup steps in readme.txt to populate this value.
	set "HAS_ERRORS=1"
)

if "!ELEVENLABS_API_KEY!"=="" (
	echo [ERROR] Missing ELEVENLABS_API_KEY in %ENV_PATH%.
	set "HAS_ERRORS=1"
)

if "!OPENAI_API_KEY!"=="" (
	echo [ERROR] Missing OPENAI_API_KEY in %ENV_PATH%.
	set "HAS_ERRORS=1"
)

if "!AZURE_TTS_KEY!"=="" (
	echo [ERROR] Missing AZURE_TTS_KEY in %ENV_PATH%.
	set "HAS_ERRORS=1"
)

if "!AZURE_TTS_REGION!"=="" (
	echo [ERROR] Missing AZURE_TTS_REGION in %ENV_PATH%.
	set "HAS_ERRORS=1"
)

if defined HAS_ERRORS (
	goto :error
)

if "!DISCORD_TOKEN!"=="" (
	echo [WARN] DISCORD_TOKEN is empty. Discord announcements will remain disabled.
)

set "NEED_IDS="
if "!BOT_ID!"=="" set "NEED_IDS=1"
if "!OWNER_ID!"=="" set "NEED_IDS=1"

if defined NEED_IDS (
	echo [INFO] BOT_ID or OWNER_ID missing. Launching tools\fetch_ids.py...
	python "%REPO_ROOT%tools\fetch_ids.py"
	if errorlevel 1 (
		echo [ERROR] Unable to populate Twitch IDs via tools\fetch_ids.py.
		goto :error
	)
	call :LoadEnvVars
)

if "!BOT_ID!"=="" (
	echo [ERROR] BOT_ID is still empty in %ENV_PATH%. Rerun tools\fetch_ids.py after providing the Twitch usernames.
	goto :error
)

if "!OWNER_ID!"=="" (
	echo [ERROR] OWNER_ID is still empty in %ENV_PATH%. Rerun tools\fetch_ids.py after providing the Twitch usernames.
	goto :error
)

if exist "%VENV_PYW%" (
	set "GUI_PYTHON=%VENV_PYW%"
) else (
	set "GUI_PYTHON=%VENV_PY%"
)

echo [INFO] Launching gui_main.py...
start "" "%GUI_PYTHON%" "%REPO_ROOT%gui_main.py"
if errorlevel 1 (
	echo [ERROR] Unable to launch gui_main.py.
	goto :error
)

echo [SUCCESS] MaddiePly GUI launched. You can close this window.
popd >nul 2>&1
exit /b 0

:error
popd >nul 2>&1
echo [FAIL] Setup aborted due to previous errors.
exit /b 1

:LoadEnvVars
for %%V in (TWITCH_CLIENT_ID TWITCH_APP_SECRET BOT_ID OWNER_ID ELEVENLABS_API_KEY OPENAI_API_KEY AZURE_TTS_KEY AZURE_TTS_REGION DISCORD_TOKEN) do set "%%V="
if not exist "%ENV_PATH%" exit /b 0
for /f "usebackq tokens=1* delims==" %%A in ("%ENV_PATH%") do (
	set "rawKey=%%A"
	set "rawKey=!rawKey: =!"
	if not "!rawKey!"=="" if not "!rawKey:~0,1!"=="#" (
		set "rawValue=%%B"
		if defined rawValue (
			for /f "tokens=* delims=" %%C in ("!rawValue!") do set "rawValue=%%C"
		)
		if /i "!rawKey!"=="TWITCH_CLIENT_ID" set "TWITCH_CLIENT_ID=!rawValue!"
		if /i "!rawKey!"=="TWITCH_APP_SECRET" set "TWITCH_APP_SECRET=!rawValue!"
		if /i "!rawKey!"=="BOT_ID" set "BOT_ID=!rawValue!"
		if /i "!rawKey!"=="OWNER_ID" set "OWNER_ID=!rawValue!"
		if /i "!rawKey!"=="ELEVENLABS_API_KEY" set "ELEVENLABS_API_KEY=!rawValue!"
		if /i "!rawKey!"=="OPENAI_API_KEY" set "OPENAI_API_KEY=!rawValue!"
		if /i "!rawKey!"=="AZURE_TTS_KEY" set "AZURE_TTS_KEY=!rawValue!"
		if /i "!rawKey!"=="AZURE_TTS_REGION" set "AZURE_TTS_REGION=!rawValue!"
		if /i "!rawKey!"=="DISCORD_TOKEN" set "DISCORD_TOKEN=!rawValue!"
	)
)
exit /b 0
