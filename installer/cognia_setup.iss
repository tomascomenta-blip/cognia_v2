; cognia_setup.iss
; Inno Setup script — builds cognia-setup.exe
; Requires: Inno Setup 6+ (https://jrsoftware.org/isinfo.php)

#define AppName      "Cognia"
#define AppVersion   "3.2.0"
#define AppPublisher "Cognia AI"
#define AppURL       "https://github.com/tomascomenta-blip/cognia_v2"
#define PythonURL    "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
#define PythonVer    "3.11"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\Cognia
DefaultGroupName=Cognia
AllowNoIcons=yes
LicenseFile=
OutputDir=dist
OutputBaseFilename=cognia-setup
SetupIconFile=
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
Name: "{autoprograms}\Cognia"; \
    Filename: "powershell.exe"; \
    Parameters: "-ExecutionPolicy Bypass -WindowStyle Normal -NoExit -File ""{app}\cognia_launcher.ps1"""; \
    WorkingDir: "{userdocs}"; \
    Comment: "Iniciar Cognia"

Name: "{autodesktop}\Cognia"; \
    Filename: "powershell.exe"; \
    Parameters: "-ExecutionPolicy Bypass -WindowStyle Normal -NoExit -File ""{app}\cognia_launcher.ps1"""; \
    WorkingDir: "{userdocs}"; \
    Comment: "Iniciar Cognia"

[Run]
; Instalar Python si no esta disponible
Filename: "{tmp}\python-installer.exe"; \
    Parameters: "InstallAllUsers=0 PrependPath=1 Include_test=0 SimpleInstall=1 /quiet"; \
    StatusMsg: "Instalando Python 3.11..."; \
    Check: NeedsPython; \
    Flags: waituntilterminated

; Instalar cognia-ai desde PyPI
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -Command ""pip install cognia-ai --upgrade --quiet"""; \
    StatusMsg: "Instalando Cognia (puede tardar 2-3 minutos)..."; \
    Flags: waituntilterminated runhidden

; Abrir Cognia al terminar (opcional)
Filename: "powershell.exe"; \
    Parameters: "-ExecutionPolicy Bypass -NoExit -File ""{app}\cognia_launcher.ps1"""; \
    Description: "Iniciar Cognia ahora"; \
    Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -Command ""pip uninstall cognia-ai -y"""; \
    Flags: runhidden waituntilterminated

[Code]

var
  PythonInstallerDownloaded: Boolean;

// Detecta si Python 3.11+ esta instalado y en PATH
function PythonInPath: Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('python', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
            and (ResultCode = 0);
end;

function NeedsPython: Boolean;
begin
  Result := not PythonInPath;
end;

// Descarga el instalador de Python antes de instalar
procedure DownloadPythonInstaller;
var
  ErrorCode: Integer;
begin
  if NeedsPython and not PythonInstallerDownloaded then begin
    WizardForm.StatusLabel.Caption := 'Descargando Python 3.11 (~25 MB)...';
    if not DownloadTemporaryFile(
      '{#PythonURL}',
      'python-installer.exe',
      '',
      nil
    ) then begin
      MsgBox(
        'No se pudo descargar Python. Verifica tu conexion a internet e intenta de nuevo.',
        mbError, MB_OK
      );
      exit;
    end;
    PythonInstallerDownloaded := True;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    DownloadPythonInstaller;
end;

// Agregar Python Scripts al PATH del usuario si no esta
procedure AddToUserPath(Dir: String);
var
  OldPath: String;
begin
  RegQueryStringValue(HKCU, 'Environment', 'PATH', OldPath);
  if Pos(LowerCase(Dir), LowerCase(OldPath)) = 0 then begin
    if OldPath = '' then
      RegWriteStringValue(HKCU, 'Environment', 'PATH', Dir)
    else
      RegWriteStringValue(HKCU, 'Environment', 'PATH', OldPath + ';' + Dir);
  end;
end;

procedure CurInstallProgressChanged(CurProgress, MaxProgress: Integer);
begin
  // no-op
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
end;

procedure DeinitializeSetup;
var
  PythonScripts: String;
begin
  // Asegura que la carpeta Scripts de pip este en PATH
  PythonScripts := ExpandConstant('{localappdata}') + '\Programs\Python\Python311\Scripts';
  AddToUserPath(PythonScripts);

  PythonScripts := GetEnv('USERPROFILE') + '\AppData\Local\Programs\Python\Python311\Scripts';
  AddToUserPath(PythonScripts);
end;
