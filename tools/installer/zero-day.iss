; Inno Setup script for the Windows installer (tools/package_desktop.py runs it).
; Installs for the current user only, so it needs no administrator rights.

#ifndef AppVersion
  #define AppVersion "dev"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\Zero Day"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\release"
#endif

[Setup]
AppId={{151601AA-9E27-46DA-B59F-D5F9237BD503}
AppName=Zero Day
AppVersion={#AppVersion}
AppPublisher=Muttakin Rahman Shoscho and Yasar Wajih
AppPublisherURL=https://github.com/shadowfax-505/Zero-Day
DefaultDirName={autopf}\Zero Day
DefaultGroupName=Zero Day
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutputDir}
OutputBaseFilename=ZeroDay-Windows-Setup
SetupIconFile=..\..\assets\icon\icon.ico
UninstallDisplayIcon={app}\Zero Day.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Zero Day"; Filename: "{app}\Zero Day.exe"
Name: "{group}\Uninstall Zero Day"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Zero Day"; Filename: "{app}\Zero Day.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Zero Day.exe"; Description: "Play Zero Day now"; Flags: nowait postinstall skipifsilent
