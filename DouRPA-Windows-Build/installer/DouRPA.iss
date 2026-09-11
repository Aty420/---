#define MyAppName "DouRPA Pro"
#define MyAppVersion "2.3.0"
#define MyAppPublisher "DouRPA"
#define MyAppExeName "DouRPA.exe"

[Setup]
AppId={{9BA5EBB5-D6D9-4D06-AE6C-12F74DA93D3A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\DouRPA
DefaultGroupName=DouRPA
DisableProgramGroupPage=yes
OutputDir=..\installer-output
OutputBaseFilename=DouRPA_Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\DouRPA.ico
UninstallDisplayIcon={app}\DouRPA.exe
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\DouRPA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\DouRPA Pro"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\DouRPA Pro"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 DouRPA Pro"; Flags: nowait postinstall skipifsilent
