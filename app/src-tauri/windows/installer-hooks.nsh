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
  ${NSD_CreateDirRequest} 0 32u 78% 13u "$LOCALAPPDATA\ATME"
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
  WriteRegStr HKCU "Software\ATME" "ProjectDataDir" "$AtmeProjectDir"
FunctionEnd

; Exact image names keep this scoped to ATME; a missing process is intentionally harmless.
!macro NSIS_HOOK_PREINSTALL
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /IM "atme-app.exe" /T /F'
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /IM "atme-sidecar.exe" /T /F'
  Sleep 750
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /IM "atme-app.exe" /T /F'
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /IM "atme-sidecar.exe" /T /F'
  Sleep 750
!macroend
