@echo off
setlocal
set "CDP_URL=%BOSMAX_CDP_URL%"
if not defined CDP_URL set "CDP_URL=http://127.0.0.1:9222"

rem Keep PowerShell out of the MCP stdio chain. It is used only for silent
rem Browser UAT preflight/startup; Node owns stdin/stdout for MCP framing.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0browser-uat-health.ps1" <nul >nul 2>nul
if errorlevel 1 (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-browser-uat.ps1" <nul >nul 2>nul
  if errorlevel 1 exit /b %ERRORLEVEL%
)

set "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS=1"
set "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1"
set "NODE_EXE=%ProgramFiles%\nodejs\node.exe"
set "NPX_EXE=%ProgramFiles%\nodejs\npx.cmd"
set "MCP_ENTRY=%APPDATA%\npm\node_modules\chrome-devtools-mcp\build\src\bin\chrome-devtools-mcp.js"

if exist "%MCP_ENTRY%" (
  "%NODE_EXE%" "%MCP_ENTRY%" "--browser-url=%CDP_URL%" %*
) else (
  call "%NPX_EXE%" --yes --prefer-offline chrome-devtools-mcp@1.8.0 "--browser-url=%CDP_URL%" %*
)
exit /b %ERRORLEVEL%
