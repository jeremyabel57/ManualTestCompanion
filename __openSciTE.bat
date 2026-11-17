@echo off
setlocal

set "scite=C:\Program Files (x86)\AutoIt3\SciTE\SciTE.exe"
set "ecwd=%CD%"
set "ecwd=%ecwd:\=\\%"

echo.
echo.
echo.
echo.
echo SCITE = %scite%
echo \\CWD = %ecwd%
echo.

start "" "%scite%" "-loadsession:%ecwd%\\SciTE.session"

endlocal
