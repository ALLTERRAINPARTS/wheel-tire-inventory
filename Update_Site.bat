@echo off
:: Navigate to the folder where this batch file is saved
cd /d "%~dp0"

echo ==========================================
echo   STARTING WEBSITE UPDATE
echo ==========================================
echo.

:: 1. Create a permanent backup of the current website
:: This moves the current site to a backup file before we start
if exist index.html (
    move /y index.html index_backup.html
    echo [OK] Current site backed up to index_backup.html
)

:: 2. Prepare the temporary files the script requires
echo Preparing inventory data...
if exist inventory.csv del inventory.csv
copy "Wheel and Tire Inventory.csv" inventory.csv

:: The script needs old.html to keep your product photos
if exist old.html del old.html
copy index_backup.html old.html

:: 3. Run the Python script to update the data
echo Running update script...
python rebuild_script.py

:: 4. Swap the new file into the index.html slot
echo Updating live index.html...
if exist new.html (
    move /y new.html index.html
)

:: 5. Clean up the temporary files
echo Cleaning up...
if exist inventory.csv del inventory.csv
if exist old.html del old.html

echo.
echo ==========================================
echo   PUSHING TO GITHUB
echo ==========================================
echo.

:: 6. Upload the changes to GitHub
git add index.html
git commit -m "Auto-update inventory: %date% %time%"
git push origin main

echo.
echo ==========================================
echo   SUCCESS! YOUR SITE IS UPDATED.
echo ==========================================
echo [Note: index_backup.html contains the previous version]
pause