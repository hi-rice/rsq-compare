#include "..\..\build\windows\version.iss"
[Setup]
AppId={{6A8A59DA-2601-41E3-A85F-8512FA4F719A}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\RSQCompare
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\installer
OutputBaseFilename=RSQCompare-Setup-{#AppVersion}-x64
SetupIconFile=..\..\build\windows\app.ico
UninstallDisplayIcon={app}\RSQCompare.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
[Tasks]
Name: "desktopicon"; Description: "바탕화면 바로가기 만들기"; Flags: checkedonce
[Files]
Source: "..\..\dist\RSQCompare\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\RSQCompare.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\RSQCompare.exe"; Tasks: desktopicon; WorkingDir: "{app}"
[Run]
Filename: "{app}\RSQCompare.exe"; Description: "프로그램 실행"; Flags: nowait postinstall skipifsilent
; 개인 DB/자료/설정/로그에 대한 UninstallDelete 항목을 두지 않는다.
