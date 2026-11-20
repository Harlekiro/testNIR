@echo off
chcp 65001 >nul
setlocal
rem ============================================================================================
rem  Установка для рабочего ноутбука — один щелчок (инструкция пользователя, раздел 0).
rem  Ставит в Python библиотеки numpy, pandas, matplotlib, pyyaml и Jupyter и открывает ноутбук.
rem  Сам пакет mixuse ставить не нужно: ноутбук находит папку mixuse рядом с собой.
rem  Если у вас Anaconda — запускать не обязательно: всё нужное в ней уже есть.
rem ============================================================================================
cd /d "%~dp0"
set "PY=%MIXUSE_PY%"
if not defined PY (
  py -3 --version >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Python не найден. Установите Anaconda с сайта anaconda.com или Python 3.10+ с сайта python.org
  echo [при установке Python отметьте «Add python.exe to PATH»] и запустите этот файл снова.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo Нужен Python 3.10 или новее. Установите его с сайта python.org и запустите этот файл снова.
  pause
  exit /b 1
)
echo [1/2] Ставлю библиотеки: numpy, pandas, matplotlib, pyyaml, Jupyter — один раз, несколько минут...
%PY% -m pip install -q numpy pandas matplotlib pyyaml notebook
if errorlevel 1 %PY% -m pip install --user -q numpy pandas matplotlib pyyaml notebook
if errorlevel 1 (
  echo Не удалось поставить библиотеки. Проверьте интернет и запустите этот файл снова.
  pause
  exit /b 1
)
%PY% -c "import numpy, pandas, matplotlib, yaml; print('      библиотеки на месте')" || exit /b 1
if defined MIXUSE_NO_START exit /b 0
echo [2/2] Открываю ноутбук метод_сравнения_вариантов.ipynb в браузере. Закрыть — окно браузера и это окно.
%PY% -m notebook метод_сравнения_вариантов.ipynb
endlocal
