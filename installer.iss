
[Setup]
AppId={{A4BFC2D0-9F71-46D8-BA8B-3FD60F2AD621}
AppName=Lumen Studio
AppVersion=1.0.0
AppPublisher=Lumen Studio
DefaultDirName={localappdata}\Programs\LumenStudio
DefaultGroupName=Lumen Studio
PrivilegesRequired=lowest
OutputDir=release
OutputBaseFilename=LumenStudio-Setup-v1.0.0
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\DesktopAgent.exe

[Files]
Source: "dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Icons]
Name: "{group}\Lumen Studio"; Filename: "{app}\DesktopAgent.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Lumen Studio"; Filename: "{app}\DesktopAgent.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\DesktopAgent.exe"; Description: "启动 Lumen Studio"; Flags: nowait postinstall skipifsilent