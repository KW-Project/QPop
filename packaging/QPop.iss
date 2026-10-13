; Inno Setup script for QPop. Built by build.bat, which passes /DAppVersion=x.y.z.
; Installs per-user (no admin prompt) to %LOCALAPPDATA%\Programs\QPop.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change AppId: it's how Windows knows a new version is an upgrade of the same app.
AppId={{7F3C2B9E-4A1D-4E8B-9C6F-2D5A8B1E0F37}
AppName=QPop
AppVersion={#AppVersion}
AppVerName=QPop {#AppVersion}
AppPublisher=QPop
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\QPop
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=QPop-Setup-{#AppVersion}
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\QPop.exe
UninstallDisplayName=QPop
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
; We stop QPop ourselves (see [Code]) - it's a tray app, so Restart Manager can't close it nicely.
CloseApplications=no

[Tasks]
Name: "autostart"; Description: "Start QPop when Windows starts (recommended)"

[Files]
Source: "..\dist\QPop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\QPop"; Filename: "{app}\QPop.exe"; Parameters: "--show"
Name: "{userstartup}\QPop"; Filename: "{app}\QPop.exe"; Tasks: autostart

[Run]
Filename: "{app}\QPop.exe"; Parameters: "--show --replace"; Description: "Open QPop now"; Flags: nowait postinstall

[UninstallRun]
Filename: "{app}\QPop.exe"; Parameters: "--stop"; RunOnceId: "StopQPop"; Flags: runhidden waituntilterminated

[UninstallDelete]
; "Start with Windows" can also be turned on from inside the app, which makes this same shortcut.
Type: files; Name: "{userstartup}\QPop.lnk"

[Code]
// Upgrading: stop the running copy first so its files aren't locked.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  if FileExists(ExpandConstant('{app}\QPop.exe')) then
    Exec(ExpandConstant('{app}\QPop.exe'), '--stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    if MsgBox('Also delete your QPop settings?' #13#10#13#10
              'Say No if you plan to reinstall: your phone will keep working with the same topic.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{userappdata}\QPop'), True, True, True);
end;
