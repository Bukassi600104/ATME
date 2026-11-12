; Release file locks held by a running ATME desktop process or an orphaned sidecar.
!include nsDialogs.nsh
!include LogicLib.nsh
Var AtmeProjectDir
Var AtmeProjectDirControl
Page custom AtmeProjectDirectoryPage AtmeProjectDirectoryLeave

Function AtmeProjectDirectoryPage
  nsDialogs::Create 1018
  Pop $0
  ${NSD_CreateLabel} 0 0 100% 24u "Choose where ATME will store projects, source copies, revisions and renders."
  Pop $0
  ReadRegStr $0 HKCU "Software\ATME" "ProjectDataDir"
  ${If} $0 == ""
    StrCpy $0 "$LOCALAPPDATA\ATME"
  ${EndIf}
  ${NSD_CreateDirRequest} 0 32u 78% 13u "$0"
  Pop $AtmeProjectDirControl
  ${NSD_CreateBrowseButton} 81% 32u 19% 13u "Browse..."
  Pop $1
  ${NSD_OnClick} $1 AtmeBrowseProjectDirectory
  nsDialogs::Show
FunctionEnd
Function AtmeBrowseProjectDirectory
  ${NSD_GetText} $AtmeProjectDirControl $AtmeProjectDir
  nsDialogs::SelectFolderDialog "Select ATME project storage" "$AtmeProjectDir"
  Pop $AtmeProjectDir
  ${If} $AtmeProjectDir != "error"
    ${NSD_SetText} $AtmeProjectDirControl "$AtmeProjectDir"
  ${EndIf}
FunctionEnd
Function AtmeProjectDirectoryLeave
  ${NSD_GetText} $AtmeProjectDirControl $AtmeProjectDir
  ${If} $AtmeProjectDir == ""
    MessageBox MB_ICONEXCLAMATION "Choose a project storage folder."
    Abort
  ${EndIf}
  CreateDirectory "$AtmeProjectDir"
FunctionEnd

!macro NSIS_HOOK_POSTINSTALL
  ${If} $AtmeProjectDir != ""
    WriteRegStr HKCU "Software\ATME" "ProjectDataDir" "$AtmeProjectDir"
  ${EndIf}
!macroend

; Tauri calls this for installation and removal. Its default checks image names only.
!define ATME_CLOSE_HELPER "${__FILEDIR__}\close-installed-atme.ps1"
!macroundef CheckIfAppIsRunning
!macro CheckIfAppIsRunning executableName productName
  InitPluginsDir
  File "/oname=$PLUGINSDIR\close-installed-atme.ps1" "${ATME_CLOSE_HELPER}"
  StrCpy $R2 "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe"
  IfFileExists "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" 0 +2
    StrCpy $R2 "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  nsExec::ExecToStack '"$R2" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\close-installed-atme.ps1" -InstallDir "$INSTDIR"'
  Pop $R0
  Pop $R1
  ${If} $R0 != 0
    DetailPrint "$R1"
    Abort "ATME could not close the running copy in $INSTDIR. Close that copy and retry."
  ${EndIf}
!macroend
