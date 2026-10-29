; Джарвис Лайт — установщик (Inno Setup 6). Сборка: scripts/build_installer.sh (или ISCC installer\jarvis.iss)
; Стадия сборки: build\stage\ = исходники + python\ (embeddable Python 3.11.9 с включённым site)
; Отдельная программа: свой AppId, своя папка, свои ярлыки, автозапуск и данные — не мешает полному Джарвису.
#define AppName "Джарвис Лайт"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define Stage "..\build\stage"

[Setup]
; AppId must never change (upgrades install in place). It differs from the full Jarvis's AppId on purpose.
AppId={{30DEBE63-2EE7-4820-91E6-23822AA8E88D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=kravakos13
AppPublisherURL=https://github.com/kravakos13/jarvis-lite
AppUpdatesURL=https://github.com/kravakos13/jarvis-lite/releases
DefaultDirName={localappdata}\Programs\JarvisLite
DisableDirPage=auto
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build\out
OutputBaseFilename=JarvisLiteSetup
SetupIconFile=..\assets\jarvis-lite.ico
UninstallDisplayIcon={app}\assets\jarvis-lite.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
UsePreviousTasks=yes
MinVersion=10.0

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Messages]
ru.WelcomeLabel2=Сейчас на компьютер установится Джарвис Лайт — лёгкий голосовой помощник без ИИ.%n%nОн почти не нагружает компьютер: нет нейросети, видеокарта не используется.%nПрава администратора не нужны. Установщик сам скачает голос и распознавание речи (около 1 ГБ вместе с программами). Обычно это 3–10 минут.%n%nЕсли у тебя уже стоит полный Джарвис — ничего страшного, они не мешают друг другу (но лучше запускать только один).%n%nНажми «Далее».
ru.FinishedLabel=Готово! Джарвис Лайт запускается: справа внизу, возле часов, появится мятный значок с буквой L (если не видно — нажми стрелочку ^ возле часов).%n%nПроверка: скажи «Джарвис, привет».%nИнструкция: Пуск → Джарвис Лайт → Инструкция.

[CustomMessages]
ru.Autostart=Запускать Джарвиса Лайт вместе с Windows
ru.Desktop=Ярлык на рабочем столе
ru.Deps=Скачать голос и распознавание речи (нужен интернет, около 1 ГБ). Оставь галочку — без этого голосовой режим не заработает
ru.DepsStatus=Скачиваю компоненты Джарвиса Лайт (окно консоли покажет прогресс, обычно 3–10 минут)...
ru.Launch=Запустить Джарвиса Лайт

[Tasks]
Name: "desktopicon"; Description: "{cm:Desktop}"
Name: "autostart"; Description: "{cm:Autostart}"
Name: "deps"; Description: "{cm:Deps}"

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Excludes: "\settings.local.yaml,\aliases.yaml,\devices.yaml,\commands.yaml,\logs\*,\models\*,\cache\*,*.pyc,__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs
; user-editable files: never overwrite on upgrade
Source: "{#Stage}\aliases.yaml"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#Stage}\devices.yaml"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Dirs]
Name: "{app}\logs"
Name: "{app}\models"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m jarvis.watchdog"; WorkingDir: "{app}"; IconFilename: "{app}\assets\jarvis-lite.ico"
Name: "{group}\{#AppName} (текстовый режим)"; Filename: "{app}\python\python.exe"; Parameters: "-m jarvis --text"; WorkingDir: "{app}"; IconFilename: "{app}\assets\jarvis-lite.ico"
Name: "{group}\Самопроверка"; Filename: "{app}\python\python.exe"; Parameters: "-m jarvis --check"; WorkingDir: "{app}"; IconFilename: "{app}\assets\jarvis-lite.ico"
Name: "{group}\Инструкция"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m jarvis.manual --open"; WorkingDir: "{app}"; IconFilename: "{app}\assets\jarvis-lite.ico"
Name: "{group}\Докачать компоненты"; Filename: "{app}\python\python.exe"; Parameters: "installer\postinstall.py"; WorkingDir: "{app}"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m jarvis.watchdog"; WorkingDir: "{app}"; IconFilename: "{app}\assets\jarvis-lite.ico"; Tasks: desktopicon

[Registry]
; same value name/format as jarvis.platform_utils.set_autostart (so the Settings checkbox stays in sync).
; "JarvisLite" — not "Jarvis" (that one belongs to the full Jarvis)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "JarvisLite"; ValueData: """{sys}\wscript.exe"" ""{app}\JarvisLite.vbs"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\python\python.exe"; Parameters: "installer\postinstall.py {code:PauseArg}"; WorkingDir: "{app}"; StatusMsg: "{cm:DepsStatus}"; Tasks: deps; Check: not SkipDeps
Filename: "{app}\python\pythonw.exe"; Parameters: "-m jarvis.watchdog"; WorkingDir: "{app}"; Description: "{cm:Launch}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; window titles of Jarvis Lite start with "Jarvis Lite" (the full Jarvis's start with «Джарвис») — only ours are closed
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /FI ""IMAGENAME eq pythonw.exe"" /FI ""WINDOWTITLE eq Jarvis Lite*"""; Flags: runhidden; RunOnceId: "KillJarvisLite"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\jarvis"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\voices"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}\wheels"
Type: files; Name: "{app}\settings.local.yaml.broken"

[Code]
function PauseArg(Param: String): String;
begin
  { interactive install: on download problems the console waits, so the user can read what went wrong }
  if WizardSilent then Result := '' else Result := '--pause-on-error';
end;

function SkipDeps: Boolean;
begin
  { /SKIPDEPS=1 — used by tests and by updates when components are already installed }
  Result := ExpandConstant('{param:SKIPDEPS|0}') = '1';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { personal data of Jarvis Lite only: %LOCALAPPDATA%\JarvisLite (the full Jarvis keeps its own elsewhere) }
    Data := ExpandConstant('{localappdata}\JarvisLite');
    if DirExists(Data) and not UninstallSilent then
      if MsgBox('Удалить также личные данные Джарвиса Лайт (заметки, задачи, память, бэкапы) из папки' + #13#10 +
                Data + ' ?' + #13#10#13#10 + 'Нажми «Нет», чтобы сохранить их (рекомендуется).',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Data, True, True, True);
    if (not UninstallSilent) and (MsgBox('Удалить также ваши настройки (settings.local.yaml, aliases.yaml, devices.yaml, commands.yaml)?',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
    begin
      DeleteFile(ExpandConstant('{app}\settings.local.yaml'));
      DeleteFile(ExpandConstant('{app}\aliases.yaml'));
      DeleteFile(ExpandConstant('{app}\devices.yaml'));
      DeleteFile(ExpandConstant('{app}\commands.yaml'));
    end;
    RemoveDir(ExpandConstant('{app}'));
  end;
end;
