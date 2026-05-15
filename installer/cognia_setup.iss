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
    Parameters: "-NoProfile -Command ""winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent"""; \
    StatusMsg: "Verificando Python..."; \
    Check: NeedsPython; \
    Flags: waituntilterminated runhidden

; Abrir Cognia al terminar (checkbox opcional)
Filename: "powershell.exe"; \
    Parameters: "-ExecutionPolicy Bypass -NoExit -File ""{app}\cognia_launcher.ps1"""; \
    Description: "Iniciar Cognia ahora"; \
    Flags: postinstall nowait skipifsilent

[UninstallRun]
; Notificar al coordinador que el nodo sale y liberar el fragmento
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -Command ""cognia leave"""; \
    Flags: runhidden waituntilterminated

; Desinstalar el paquete Python
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -Command ""pip uninstall cognia-ai -y"""; \
    Flags: runhidden waituntilterminated

[Code]

// ── Buscar python.exe en rutas de instalacion conocidas ───────────────────────
function FindPythonExe(): String;
var
  Versions: TStringList;
  I: Integer;
  PyExe, LocalAppData, AppData: String;
begin
  Result := '';
  LocalAppData := GetEnv('LOCALAPPDATA');
  AppData := GetEnv('APPDATA');
  Versions := TStringList.Create;
  try
    Versions.Add('Python313');
    Versions.Add('Python312');
    Versions.Add('Python311');
    for I := 0 to Versions.Count - 1 do begin
      PyExe := LocalAppData + '\Programs\Python\' + Versions[I] + '\python.exe';
      if FileExists(PyExe) then begin
        Result := PyExe;
        Exit;
      end;
    end;
    // Instalaciones antiguas en AppData\Roaming
    for I := 0 to Versions.Count - 1 do begin
      PyExe := AppData + '\Python\' + Versions[I] + '\python.exe';
      if FileExists(PyExe) then begin
        Result := PyExe;
        Exit;
      end;
    end;
  finally
    Versions.Free;
  end;
end;

// ── Detectar si Python 3.11+ esta disponible ──────────────────────────────────
function NeedsPython: Boolean;
var
  ResultCode: Integer;
begin
  if FindPythonExe() <> '' then begin
    Result := False;
    Exit;
  end;
  // Ultimo recurso: probar el comando generico en PATH
  Result := not Exec('python', '-c "import sys; exit(0 if sys.version_info>=(3,11) else 1)"',
                     '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
            or (ResultCode <> 0);
end;

// ── Agregar directorio al PATH del usuario ────────────────────────────────────
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

// ── Instalar cognia-ai via python -m pip una vez que Python ya esta listo ─────
procedure CurStepChanged(CurStep: TSetupStep);
var
  PyExe, ScriptsDir: String;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    PyExe := FindPythonExe();
    if PyExe = '' then
      PyExe := 'python';  // fallback si esta en PATH del sistema
    Exec(PyExe, '-m pip install cognia-ai --upgrade --quiet',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    // Agregar el directorio Scripts al PATH del usuario
    if PyExe <> 'python' then begin
      ScriptsDir := ExtractFilePath(PyExe) + 'Scripts';
      AddToUserPath(ScriptsDir);
    end;
  end;
end;

// ── PATH del usuario al terminar la instalacion ───────────────────────────────
procedure DeinitializeSetup;
var
  LocalAppData: String;
begin
  LocalAppData := GetEnv('LOCALAPPDATA');
  AddToUserPath(LocalAppData + '\Programs\Python\Python313\Scripts');
  AddToUserPath(LocalAppData + '\Programs\Python\Python312\Scripts');
  AddToUserPath(LocalAppData + '\Programs\Python\Python311\Scripts');
end;
