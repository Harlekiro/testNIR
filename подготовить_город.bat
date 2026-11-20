@echo off
chcp 65001 >nul
setlocal
rem ============================================================================================
rem  Подготовка данных города для обеспеченности школами и садами (раздел 12 задания).
rem  Делается ОДИН РАЗ на город (и заново — если изменились слои кварталов, зданий или сервисов).
rem
rem  Запуск:   двойной щелчок — настройки последней анкеты ноутбука (configs\анкета_<код>.yaml);
rem            или подготовить_город.bat configs\gatchina_layers.yaml
rem
rem  Что делает:
rem    1) если нет — ставит Python 3.11 и отдельное окружение с blocksnet (%USERPROFILE%\venvs\blocksnet311);
rem    2) берёт файлы регионов OpenStreetMap из data\osm (если их нет — скачивает Петербург и Ленобласть) и строит
rem       матрицу доступности: пешеходный граф — из файлов, без сервера Overpass;
rem    3) считает обеспеченность «как есть» и сохраняет её для оценки вариантов;
rem    4) собирает файл для страницы страница\конструктор.html.
rem  После этого ноутбук и командная строка сами используют blocksnet для вариантов.
rem ============================================================================================
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "CFG=%~1"
rem без аргумента (двойной щелчок) — последние настройки, сохранённые ноутбуком: configs\анкета_<код>.yaml
if "%CFG%"=="" for /f "delims=" %%f in ('dir /b /o:d "configs\анкета_*.yaml" 2^>nul') do set "CFG=configs\%%f"
if "%CFG%"=="" (
  echo Нет настроек города. Заполните анкету ноутбука и выполните его ^(настройки сохранятся в configs^),
  echo или укажите файл настроек:  подготовить_город.bat configs\gatchina_layers.yaml
  pause
  exit /b 1
)
echo Настройки города: %CFG%
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
echo [2/4] Файл OpenStreetMap региона: из анкеты или настроек, иначе из папки data\osm. Для своего города положите
echo      туда файл .osm.pbf [download.openstreetmap.fr, download.geofabrik.de]; если папка пуста — скачаю Петербург и Ленобласть.
"%PY%" -m mixuse osm-download --config "%CFG%" || exit /b 1
echo      Матрица доступности (граф — из файлов data\osm, без сервера Overpass)...
"%PY%" -m mixuse access "%CFG%" --retries 0 || exit /b 1
echo [3/4] Обеспеченность «как есть»...
"%PY%" -m mixuse provision "%CFG%" || exit /b 1
echo [4/4] Файл для страницы...
"%PY%" -m mixuse page "%CFG%" || exit /b 1
echo.
echo Готово. Откройте страница\конструктор.html и загрузите файл results\^<код^>_для_страницы.json.
endlocal
