@echo off
chcp 65001 >nul
setlocal
rem ============================================================================================
rem  Подготовка данных города для обеспеченности школами и садами (раздел 12 задания).
rem  Делается ОДИН РАЗ на город (и заново — если изменились слои кварталов, зданий или сервисов).
rem
rem  Запуск:   подготовить_город.bat configs\gatchina_layers.yaml
rem
rem  Что делает:
rem    1) если нет — ставит Python 3.11 и отдельное окружение с blocksnet (%USERPROFILE%\venvs\blocksnet311);
rem    2) строит матрицу доступности (пешеходный граф из OpenStreetMap; сервер бывает перегружен —
rem       программа ждёт и продолжает с места обрыва, скачанные части сохраняются);
rem    3) считает обеспеченность «как есть» и сохраняет её для оценки вариантов;
rem    4) собирает файл для страницы страница\конструктор.html.
rem  После этого ноутбук и командная строка сами используют blocksnet для вариантов.
rem ============================================================================================
if "%~1"=="" (
  echo Укажите файл настроек города, например:  подготовить_город.bat configs\gatchina_layers.yaml
  exit /b 1
)
set "ROOT=%~dp0"
set "VENV=%USERPROFILE%\venvs\blocksnet311"
set "PY=%VENV%\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"

if not exist "%PY%" (
  echo [1/4] Ставлю Python 3.11 и окружение с blocksnet — один раз, несколько минут...
  py -V:3.11 --version >nul 2>&1 || py install 3.11 || (echo Не удалось поставить Python 3.11. Установите его с python.org и запустите снова. & exit /b 1)
  py -V:3.11 -m venv "%VENV%" || exit /b 1
  "%PY%" -m pip install -q --upgrade pip
  "%PY%" -m pip install -q -e "%ROOT:~0,-1%[blocksnet]" || (echo Не удалось установить blocksnet. & exit /b 1)
) else (
  echo [1/4] Окружение с blocksnet уже есть: %VENV%
)

cd /d "%ROOT%"
echo [2/4] Матрица доступности (может занять от минут до часов для большого города)...
"%PY%" -m mixuse access "%~1" --retries 0 || exit /b 1
echo [3/4] Обеспеченность «как есть»...
"%PY%" -m mixuse provision "%~1" || exit /b 1
echo [4/4] Файл для страницы...
"%PY%" -m mixuse page "%~1" || exit /b 1
echo.
echo Готово. Откройте страница\конструктор.html и загрузите файл results\^<код^>_для_страницы.json.
endlocal
