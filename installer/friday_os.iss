; FRIDAY OS — Inno Setup installer script.
;
; Build with (from the project root, on Windows, after the PyInstaller
; step has produced dist/FridayOS/):
;     ISCC installer/friday_os.iss /DAppVersion=0.6.0
;
; Normally you don't run this directly — scripts/build_installer.ps1
; runs the PyInstaller step, reads the version out of app/_version.py,
; and passes it in via /DAppVersion automatically so this file never
; has a version to manually keep in sync.
;
; #AppVersion is a *preprocessor* define (passed via /D on the command
; line), separate from Inno's own AppVersion directive below which reads
; it — if you run ISCC without /DAppVersion, this falls back to "0.0.0-dev"
; rather than failing, so a stray manual test run doesn't hard-crash.

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

#define AppName "FRIDAY OS"
#define AppPublisher "Suraj"
#define AppExeName "FridayOS.exe"
#define SourceDistDir "..\dist\FridayOS"

[Setup]
AppId={{8F3B6C7A-4E2D-4A1F-9B5C-2D8E6F1A3C7B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
; Per-user install (no admin required) is the right default for a
; personal assistant that also registers a per-user (HKCU) startup
; entry -- an admin-elevated machine-wide install would be a mismatch
; with startup_manager.py's deliberately-per-user registration scope.
PrivilegesRequired=lowest
DefaultGroupName={#AppName}
OutputDir=output
OutputBaseFilename=FridayOS-Setup-{#AppVersion}
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
DisableWelcomePage=no
LicenseFile=
; Left blank on purpose -- add a LICENSE.txt here and uncomment the
; line above once this project has a real license file to ship.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "startupicon"; Description: "Start FRIDAY OS automatically when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; The entire PyInstaller onedir output, recursively. This is the one
; line that actually ships the app -- everything else in this script is
; shortcuts, registry, and UI chrome around it.
Source: "{#SourceDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
; Startup-folder shortcut, NOT a registry Run key -- this is the
; installer's one-time default (see the [Tasks] description above); the
; in-app Settings toggle (app/automation/desktop/startup_manager.py)
; uses a separate HKCU Run key at runtime so the user can change their
; mind later without needing to reinstall or touch this shortcut. Note
; the "--startup" argument, matching what main.py checks for to decide
; whether to open the dashboard window immediately or start tray-only.
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Parameters: "--startup"; Tasks: startupicon

[Run]
; Offer to launch immediately after a successful install, same as any
; standard Windows installer -- but skip the --startup flag here since
; a user who just finished installing wants to actually see the app,
; not have it silently start in the tray.
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Deliberately does NOT touch {userappdata}\FridayOS or
; %LOCALAPPDATA%\FridayOS (the user_data_root from app/core/config.py --
; database, memory, notes, portfolio, conversation history, plugins the
; user installed). Uninstalling the application must never silently
; destroy a person's data; if they want that gone too, that's a
; deliberate separate action, not a side effect of "remove this program".
Type: filesandordirs; Name: "{app}"

[Code]
// Runs after a successful uninstall -- tells the person exactly where
// their data still lives, since [UninstallDelete] above intentionally
// leaves it in place. Without this, "where did my data go" is a
// reasonable but wrong question to ask; this answers it proactively.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox(
      'FRIDAY OS has been removed.' + #13#10 + #13#10 +
      'Your data (conversation history, memory, portfolio, plugins) was ' +
      'intentionally left in place at:' + #13#10 +
      ExpandConstant('{localappdata}\FridayOS') + #13#10 + #13#10 +
      'Delete that folder yourself if you want to remove it too.',
      mbInformation, MB_OK
    );
  end;
end;
