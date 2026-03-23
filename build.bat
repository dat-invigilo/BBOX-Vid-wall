# @echo off
REM Video Wall Build Script for Windows

setlocal enabledelayedexpansion

echo ======================================
echo Video Wall Build Script (Windows)
echo ======================================

set IMAGE_NAME=bbox-video-wall
set IMAGE_TAG=latest
set REGISTRY=%1

if not "%REGISTRY%"=="" (
    echo Registry: %REGISTRY%
)

echo [1/3] Building Docker image...
docker build -t %IMAGE_NAME%:%IMAGE_TAG% .

if not "%REGISTRY%"=="" (
    echo [2/3] Tagging for registry...
    docker tag %IMAGE_NAME%:%IMAGE_TAG% %REGISTRY%/%IMAGE_NAME%:%IMAGE_TAG%
    
    echo [3/3] Pushing to registry...
    docker push %REGISTRY%/%IMAGE_NAME%:%IMAGE_TAG%
    echo √ Pushed: %REGISTRY%/%IMAGE_NAME%:%IMAGE_TAG%
) else (
    echo [2/3] Skipping registry operations
    echo [3/3] Done
)

echo.
echo ======================================
echo Build complete!
echo ======================================
echo.
echo To run the application:
echo   docker-compose up -d
echo.
echo Or with direct docker run:
echo   docker run -it bbox-video-wall:latest
echo.

endlocal
