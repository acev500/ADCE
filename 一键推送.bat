@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 超分辨 · 一键推送到 GitHub
cd /d "%~dp0"

echo ============================================================
echo   超分辨 · 推送到 GitHub
echo ============================================================
echo.
echo 需要两样东西：
echo   1. GitHub 用户名（登录后右上角头像里那个）
echo   2. Personal Access Token（只勾 repo 权限）
echo      生成地址：https://github.com/settings/tokens/new
echo.
echo 注意：token 只显示一次，复制好再粘进来。
echo ============================================================
echo.

set /p GH_USER=GitHub 用户名：
if "%GH_USER%"=="" (
  echo 没填用户名，退出。
  pause & exit /b 1
)

set /p GH_TOKEN=Personal Access Token：
if "%GH_TOKEN%"=="" (
  echo 没填 token，退出。
  pause & exit /b 1
)

set /p REPO=仓库名（回车默认 chaofenbian）：
if "%REPO%"=="" set REPO=chaofenbian

echo.
echo ------------------------------------------------------------
echo   用户名：%GH_USER%
echo   仓库名：%REPO%
echo ------------------------------------------------------------
echo.

echo [1/3] 建仓库...
curl.exe -s -X POST ^
  -H "Authorization: Bearer %GH_TOKEN%" ^
  -H "Accept: application/vnd.github+json" ^
  -H "User-Agent: chaofenbian" ^
  https://api.github.com/user/repos ^
  -d "{\"name\":\"%REPO%\",\"private\":false,\"description\":\"视频超分+补帧+图片超分\"}" > _repo.json
findstr /C:"full_name" _repo.json >nul
if errorlevel 1 (
  findstr /C:"already exists" _repo.json >nul
  if errorlevel 1 (
    echo   建仓库失败，返回内容：
    type _repo.json
    echo.
    echo   常见原因：token 没勾 repo 权限、或者用户名不对。
    del _repo.json 2>nul
    pause & exit /b 1
  ) else (
    echo   仓库已存在，继续。
  )
) else (
  echo   建好了。
)
del _repo.json 2>nul

echo [2/3] 配置 remote...
git remote remove origin >nul 2>&1
git remote add origin https://%GH_USER%:%GH_TOKEN%@github.com/%GH_USER%/%REPO%.git
git branch -M main >nul 2>&1

echo [3/3] 推送...
git push -u origin main
if errorlevel 1 (
  echo.
  echo   推送失败。检查 token 是否有 Contents: Read and write 权限。
  git remote set-url origin https://github.com/%GH_USER%/%REPO%.git
  pause & exit /b 1
)

rem 推完把 token 从 .git/config 里抹掉
git remote set-url origin https://github.com/%GH_USER%/%REPO%.git

echo.
echo ============================================================
echo   完成
echo   仓库：https://github.com/%GH_USER%/%REPO%
echo ============================================================
echo.
echo 别忘了回 GitHub 把这个 token 删掉：
echo   https://github.com/settings/tokens
echo.
pause
