; Homeboard Windows installer. Built with official portable NSIS; no host installation is required.
Unicode true
RequestExecutionLevel user
ManifestDPIAware true
SetCompressor /SOLID lzma
SetCompressorDictSize 32
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!include "Sections.nsh"

!ifndef APP_VERSION
  !define APP_VERSION "0.2.0-rc.1"
!endif
!ifndef APP_VERSION_QUAD
  !define APP_VERSION_QUAD "0.2.0.1"
!endif
!ifndef BUNDLE_DIR
  !error "Pass /DBUNDLE_DIR=<PyInstaller Homeboard directory>"
!endif
!ifndef OUTPUT_FILE
  !define OUTPUT_FILE "Homeboard-Setup-${APP_VERSION}-windows-x64.exe"
!endif

Name "Homeboard"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\Homeboard"
BrandingText "Homeboard ${APP_VERSION} · release candidate"
ShowInstDetails show
ShowUninstDetails show
VIProductVersion "${APP_VERSION_QUAD}"
VIAddVersionKey /LANG=1033 "ProductName" "Homeboard"
VIAddVersionKey /LANG=1033 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "FileDescription" "Homeboard setup — release candidate"
VIAddVersionKey /LANG=1033 "FileVersion" "${APP_VERSION_QUAD}"
!ifdef APP_ICON
  !define MUI_ICON "${APP_ICON}"
  !define MUI_UNICON "${APP_ICON}"
!endif

!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "A little more together."
!define MUI_WELCOMEPAGE_TEXT "Homeboard brings your family's plans, shopping lists and household tasks into one shared place.$\r$\n$\r$\nThis setup installs for your Windows account. It includes the local server and storage runtime; you do not need Python, Docker or a command prompt.$\r$\n$\r$\nRelease candidate: this build is unsigned and has not completed the public-sale checks."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "Welcome home."
!define MUI_FINISHPAGE_TEXT "Homeboard is installed. Open it to create your household and save your recovery kit.$\r$\n$\r$\nYour household data belongs to this Windows account and is stored separately from the application."
!define MUI_FINISHPAGE_RUN "$INSTDIR\Homeboard.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Open Homeboard and finish setup"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  SetShellVarContext current
  ; This per-user edition deliberately fixes its owned binary directory.
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\Homeboard"
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "This Homeboard build requires 64-bit Windows 10 or Windows 11."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "This Homeboard build requires Windows 10 or Windows 11."
    Abort
  ${EndIf}
FunctionEnd

Function un.onInit
  SetShellVarContext current
  ${If} $INSTDIR != "$LOCALAPPDATA\Programs\Homeboard"
    MessageBox MB_OK|MB_ICONSTOP "Run Uninstall from the installed Homeboard application folder."
    Abort
  ${EndIf}
FunctionEnd

Section "Homeboard application (required)" SEC_APP
  SectionIn RO
  SetShellVarContext current
  IfFileExists "$INSTDIR\Homeboard.exe" 0 files_ready
    DetailPrint "Stopping the existing Homeboard server before updating..."
    ExecWait '"$INSTDIR\Homeboard.exe" --stop' $0
    ${If} $0 != 0
      MessageBox MB_OK|MB_ICONSTOP "Homeboard could not stop safely. Close Homeboard and try the update again. Your household data has not been removed."
      Abort
    ${EndIf}
  files_ready:
  ; Prevent obsolete runtime files surviving an upgrade, after owned-worker stop.
  RMDir /r "$INSTDIR\_internal"
  SetOutPath "$INSTDIR"
  File /r "${BUNDLE_DIR}\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\Homeboard"
  CreateShortcut "$SMPROGRAMS\Homeboard\Homeboard.lnk" "$INSTDIR\Homeboard.exe"
  CreateShortcut "$SMPROGRAMS\Homeboard\Stop Homeboard.lnk" "$INSTDIR\Homeboard.exe" "--stop"
  CreateShortcut "$SMPROGRAMS\Homeboard\Quick start.lnk" "$INSTDIR\Quickstart.txt"
  WriteRegStr HKCU "Software\Homeboard" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Homeboard" "DisplayName" "Homeboard"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Homeboard" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Homeboard" "DisplayIcon" "$INSTDIR\Homeboard.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Homeboard" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Homeboard" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Homeboard" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Homeboard" "NoRepair" 1
SectionEnd

Section "Start Homeboard when I sign in" SEC_STARTUP
  SetShellVarContext current
  CreateShortcut "$SMSTARTUP\Homeboard.lnk" "$INSTDIR\Homeboard.exe" "--background"
SectionEnd

Section "Desktop shortcut" SEC_DESKTOP
  SetShellVarContext current
  CreateShortcut "$DESKTOP\Homeboard.lnk" "$INSTDIR\Homeboard.exe"
SectionEnd

Section -ApplyShortcutChoices
  SectionGetFlags ${SEC_STARTUP} $0
  IntOp $0 $0 & ${SF_SELECTED}
  ${If} $0 == 0
    Delete "$SMSTARTUP\Homeboard.lnk"
  ${EndIf}
  SectionGetFlags ${SEC_DESKTOP} $0
  IntOp $0 $0 & ${SF_SELECTED}
  ${If} $0 == 0
    Delete "$DESKTOP\Homeboard.lnk"
  ${EndIf}
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_APP} "The application and its bundled local server. Your household data is stored separately."
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_STARTUP} "Keep Homeboard available after you sign in to Windows. The PC must stay awake for other devices to connect."
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP} "Add a Homeboard shortcut to this Windows account's desktop."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  SetShellVarContext current
  IfFileExists "$INSTDIR\Homeboard.exe" 0 stopped
    ExecWait '"$INSTDIR\Homeboard.exe" --stop' $0
    ${If} $0 != 0
      MessageBox MB_OK|MB_ICONSTOP "Homeboard is still running. Stop it before uninstalling. Your household data is kept."
      Abort
    ${EndIf}
  stopped:
  Delete "$SMSTARTUP\Homeboard.lnk"
  Delete "$DESKTOP\Homeboard.lnk"
  Delete "$SMPROGRAMS\Homeboard\Homeboard.lnk"
  Delete "$SMPROGRAMS\Homeboard\Stop Homeboard.lnk"
  Delete "$SMPROGRAMS\Homeboard\Quick start.lnk"
  RMDir "$SMPROGRAMS\Homeboard"
  ; Remove only the installer-owned binary tree. No customer data is under it.
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\Homeboard.exe"
  Delete "$INSTDIR\Quickstart.txt"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.md"
  Delete "$INSTDIR\RELEASE_STATUS.txt"
  Delete "$INSTDIR\build-manifest.json"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Homeboard"
  DeleteRegKey HKCU "Software\Homeboard"
  ; Deliberately retain $LOCALAPPDATA\Homeboard (data, configuration, recovery and backups).
SectionEnd
