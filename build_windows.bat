@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 goto path_error
set "PYTHON=D:\Dev\Environments\NovelSims\Scripts\python.exe"
echo ==============================================
echo NovelSims Windows desktop build
echo ==============================================
if not exist "%PYTHON%" goto python_missing
"%PYTHON%" --version
if errorlevel 1 goto python_error
"%PYTHON%" -m pip check
if errorlevel 1 goto dependency_error
"%PYTHON%" -m PyInstaller --clean --noconfirm "%~dp0NovelSims.spec"
if errorlevel 1 goto build_error
if not exist "%~dp0dist\NovelSims.exe" goto output_missing
echo.
echo BUILD SUCCESS
echo Output: "%~dp0dist\NovelSims.exe"
echo.
pause
popd
exit /b 0
:path_error
echo ERROR: Could not enter the project folder.
goto failed
:python_missing
echo ERROR: Python environment not found:
echo "%PYTHON%"
echo Check that the NovelSims virtual environment exists at the configured path.
goto failed
:python_error
echo ERROR: Python could not start.
goto failed
:dependency_error
echo ERROR: Python package requirements are inconsistent.
goto failed
:build_error
echo ERROR: PyInstaller failed. Read the messages above.
goto failed
:output_missing
echo ERROR: Build ended but dist\NovelSims.exe was not created.
goto failed
:failed
echo.
echo BUILD FAILED
pause
popd
exit /b 1
