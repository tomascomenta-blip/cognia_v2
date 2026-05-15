; cognia_setup.iss
; Inno Setup 6+ — https://jrsoftware.org/isinfo.php

#define AppName      "Cognia"
#define AppVersion   "3.2.0"
#define AppURL       "https://github.com/tomascomenta-blip/cognia_v2"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisherURL={#AppURL}
DefaultDirName={autopf}\Cognia
DefaultGroupName=Cognia
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=cognia-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "cognia_launcher.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\Cognia"; \
    Filename: "powershell.exe"; \
    Parameters: "-ExecutionPolicy Bypass -NoExit -File ""{app}\cognia_launcher.ps1"""; \
    WorkingDir: "{userdocs}"; \
    Comment: "Iniciar Cognia"

Name: "{autoprograms}\Cognia\Cognia"; \
    Filename: "powershell.exe"; \
    Parameters: "-ExecutionPolicy Bypass -NoExit -File ""{app}\cognia_launcher.ps1"""; \
    WorkingDir: "{userdocs}"; \
    Comment: "Iniciar Cognia"

[Run]
; Instalar Python si falta (via winget, silencioso)
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -Command ""winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements --silent"""; \
    StatusMsg: "Verificando Python..."; \
    Check: NeedsPython; \
    Flags: waituntilterminated runhidden

; Instalar cognia-ai desde PyPI
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -Command ""$env:PATH = [Environment]::GetEnvironmentVariable('PATH','Machine') + ';' + [Environment]::GetEnvironmentVariable('PATH','User'); pip install cognia-ai --upgrade --quiet"""; \
    StatusMsg: "Instalando Cognia (puede tardar 2-3 minutos)..."; \
    Flags: waituntilterminated runhidden

; Abrir Cognia al terminar (checkbox opcional)
Filename: "powershell.exe"; \
    Parameters: "-ExecutionPolicy Bypass -NoExit -File ""{app}\cognia_launcher.ps1"""; \
    Description: "Iniciar Cognia ahora"; \
    Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -Command ""pip uninstall cognia-ai -y"""; \
    Flags: runhidden waituntilterminated

[Code]
function NeedsPython: Boolean;
var
  ResultCode: Integer;
begin
  Result := not Exec('python', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
            or (ResultCode <> 0);
end;

procedure AddToUserPath(Dir: String);
var
  OldPath: String;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'PATH', OldPath) then
    OldPath := '';
  if Pos(LowerCase(Dir), LowerCase(OldPath)) = 0 then begin
    if OldPath = '' then
      RegWriteStringValue(HKCU, 'Environment', 'PATH', Dir)
    else
      RegWriteStringValue(HKCU, 'Environment', 'PATH', OldPath + ';' + Dir);
  end;
end;

procedure DeinitializeSetup;
begin
  AddToUserPath(ExpandConstant('{localappdata}') + '\Programs\Python\Python311\Scripts');
  AddToUserPath(ExpandConstant('{localappdata}') + '\Programs\Python\Python312\Scripts');
end;
