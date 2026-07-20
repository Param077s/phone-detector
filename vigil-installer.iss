; ============================================================================
;  Vigil — Windows installer (Inno Setup 6, https://jrsoftware.org/isinfo.php)
;
;  Built by build-windows.bat, which passes the version:
;      iscc /DAppVersion=1.1.6 vigil-installer.iss
;
;  Installs per-user (no admin prompt — the VS Code / Discord pattern),
;  creates the Start Menu entry, an optional desktop shortcut, and the
;  standard "Apps > Installed apps" uninstall entry.
; ============================================================================

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7E1B9C7A-9D4C-4C1E-B4F1-6A1D2E8F0A21}
AppName=Vigil
AppVersion={#AppVersion}
AppVerName=Vigil {#AppVersion}
AppPublisher=Vigil
AppPublisherURL=https://github.com/Param077s/phone-detector
DefaultDirName={autopf}\Vigil
DefaultGroupName=Vigil
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=Vigil-Setup-{#AppVersion}
SetupIconFile=build\vigil.ico
UninstallDisplayIcon={app}\Vigil.exe
UninstallDisplayName=Vigil
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
  GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole PyInstaller output folder (server + AI engine + UI, self-contained)
Source: "dist\Vigil\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Vigil"; Filename: "{app}\Vigil.exe"
Name: "{autodesktop}\Vigil"; Filename: "{app}\Vigil.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Vigil.exe"; Description: "{cm:LaunchProgram,Vigil}"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The app itself never writes into {app}; user data lives in %APPDATA%\Vigil
; and is deliberately KEPT on uninstall (evidence is the user's record).
Type: filesandordirs; Name: "{app}\__pycache__"
