#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef StageDir
  #error StageDir is required
#endif
#ifndef ArtDir
  #error ArtDir is required
#endif

[Setup]
AppId={{7A299DDE-FA63-4A6C-A257-C9EF9894F35C}
AppName=Mayotter
AppVersion={#AppVersion}
AppPublisher=Mayotter
DefaultDirName={localappdata}\Programs\Mayotter
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\Mayotter.exe
OutputBaseFilename=Mayotter_Setup_v{#AppVersion}_Windows_x64
SetupIconFile={#ArtDir}\mayotter.ico
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern dark polar
WizardBackColor=#0b111f
WizardImageBackColor=#0b111f
WizardSmallImageBackColor=#0b111f
WizardImageFile={#ArtDir}\wizard.png
WizardSmallImageFile={#ArtDir}\logo_small.png
WizardSizePercent=110
DisableWelcomePage=no
DisableDirPage=no
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=no
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage
AppMutex=Local\Mayotter.Installed
SetupMutex=Mayotter.Setup
CloseApplications=no
RestartApplications=no
Uninstallable=yes
UsePreviousTasks=yes
UsePreviousAppDir=yes
UninstallDisplayName=Mayotter

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[LangOptions]
japanese.DialogFontName=Yu Gothic UI
japanese.WelcomeFontName=Yu Gothic UI
chinesesimplified.DialogFontName=Microsoft YaHei UI
chinesesimplified.WelcomeFontName=Microsoft YaHei UI

[Messages]
english.ConfirmUninstall=Are you sure you want to completely remove %1%nand all of its components?
japanese.ConfirmUninstall=%1とその関連コンポーネントを%nすべて削除します。よろしいですか？
chinesesimplified.ConfirmUninstall=您确认要完全移除 %1%n及其所有组件吗？

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[CustomMessages]
english.SeparateData=Choose a program folder outside %1. This folder is reserved for your settings, profiles, and recordings.
japanese.SeparateData=%1 は設定・プロファイル・録音の保存専用です。プログラムの保存先には別のフォルダを選択してください。
english.UnsafeDirectory=Choose an empty program folder, or the registered Mayotter installation. Development folders, user data, system folders and linked paths cannot be used.
japanese.UnsafeDirectory=空のプログラム用フォルダ、または登録済みのMayotterインストール先を選んでください。開発フォルダ・ユーザーデータ・システムフォルダ・リンクされたパスは使用できません。
english.OpenUserDataFolder=Open folder
japanese.OpenUserDataFolder=フォルダを開く
chinesesimplified.OpenUserDataFolder=打开文件夹
english.UserDataTitle=Mayotter user data
japanese.UserDataTitle=Mayotter のユーザーデータ
english.KeepUserData=Keep user data (recommended)
japanese.KeepUserData=ユーザーデータを保持する（推奨）
english.DeleteUserData=Delete user data too
japanese.DeleteUserData=ユーザーデータも削除する
english.UserDataDetails=Keeping your data lets you use your accounts and settings after reinstalling.%n%nDeletion permanently removes accounts, Cookies, profiles, settings, cache, recordings and images stored in %1.%n%nIf you need any of this data, save it before uninstalling.%n%nNote: Portable (ZIP) data and files saved elsewhere are not removed.
japanese.UserDataDetails=保持すると、再インストール後も以前のアカウントや設定を利用できます。%n%n削除すると、%1 に保存されているアカウント・Cookie・プロファイル・設定・キャッシュ・録音・画像が完全に削除されます。%n%n必要なデータがある場合は、保存してからアンインストールしてください。%n%n※ZIP版や別の場所に保存したファイルは削除しません。
english.ConfirmUserData=Delete all Mayotter user data in this folder?%n%n%1%n%nDeleted data cannot be recovered.%n%nChoose No to cancel uninstallation.
japanese.ConfirmUserData=次のフォルダ内のMayotterユーザーデータをすべて削除しますか？%n%n%1%n%n削除したデータは元に戻せません。%n%n『いいえ』を選ぶとアンインストールを中止します。
english.UnsafeUserData=Uninstallation was cancelled because the data folder could not be safely deleted. Another installation may use it, or it may contain a link or development files. Choose Keep user data to uninstall the program only.
japanese.UnsafeUserData=データ保存先を安全に削除できないため、アンインストールを中止しました。別のインストールによる利用、リンク、開発用ファイルなどがないか確認してください。本体だけを削除する場合は「ユーザーデータを保持する」を選んでください。
english.UserDataDeleteFailed=User data could not be completely deleted. Uninstallation was stopped and the program remains installed. Some data may already have been deleted. Close Mayotter and other programs using the folder, check access permissions, and try again.%n%n%1
japanese.UserDataDeleteFailed=ユーザーデータを完全に削除できませんでした。アンインストールを中止し、本体は残しています。一部のデータは既に削除されている可能性があります。Mayotterや保存先を使用するソフトを終了し、アクセス権を確認して再試行してください。%n%n%1

chinesesimplified.SeparateData=%1 仅用于保存设置、配置文件和录音。请为程序选择其他文件夹。
chinesesimplified.UnsafeDirectory=请选择空的程序文件夹，或已注册的 Mayotter 安装位置。开发文件夹、用户数据、系统文件夹和链接路径无法使用。
chinesesimplified.UserDataTitle=Mayotter 用户数据
chinesesimplified.KeepUserData=保留用户数据（推荐）
chinesesimplified.DeleteUserData=同时删除用户数据
chinesesimplified.UserDataDetails=保留数据后，重新安装时可继续使用以前的账号和设置。%n%n选择删除将永久移除 %1 中保存的账号、Cookie、配置文件、设置、缓存、录音和图片。%n%n如有需要的数据，请先保存再卸载。%n%n注：ZIP 版或保存在其他位置的文件不会被删除。
chinesesimplified.ConfirmUserData=要删除此文件夹中的所有 Mayotter 用户数据吗？%n%n%1%n%n删除的数据将无法恢复。%n%n选择“否”将取消卸载。
chinesesimplified.UnsafeUserData=无法安全删除数据文件夹，已取消卸载。其他安装可能正在使用该文件夹，或其中包含链接或开发用文件。若只想删除程序，请选择“保留用户数据”。
chinesesimplified.UserDataDeleteFailed=无法完全删除用户数据，已停止卸载并保留程序。部分数据可能已被删除。请关闭 Mayotter 及使用该文件夹的软件，检查访问权限后重试。%n%n%1

[Registry]
Root: HKCU64; Subkey: "Software\Mayotter\InstalledCopies"; ValueType: string; ValueName: "{code:InstallCopyKey}"; ValueData: "{app}"; Flags: uninsdeletevalue uninsdeletekeyifempty

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "mayotter-installed.ini"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
; QtWebEngine may create this empty directory after installation.
Name: "{app}\_internal\PySide6\resources\locales"

[Icons]
Name: "{userprograms}\Mayotter"; Filename: "{app}\Mayotter.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\Mayotter"; Filename: "{app}\Mayotter.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Mayotter.exe"; Description: "{cm:LaunchProgram,Mayotter}"; Flags: nowait postinstall skipifsilent

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7A299DDE-FA63-4A6C-A257-C9EF9894F35C}_is1';
  InstalledCopiesKey = 'Software\Mayotter\InstalledCopies';

function NormalPath(Path: String): String;
begin
  Result := RemoveBackslashUnlessRoot(ExpandFileName(Path));
end;

function InstallCopyKey(Param: String): String;
begin
  Result := GetSHA256OfString(Lowercase(NormalPath(ExpandConstant('{app}'))));
end;

function GetFileAttributesW(lpFileName: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function LinkedPath(Path: String): Boolean;
var Attributes: LongWord; Parent: String;
begin
  Result := False;
  while Length(Path) > 3 do begin
    Attributes := GetFileAttributesW(Path);
    if (Attributes <> $FFFFFFFF) and ((Attributes and $400) <> 0) then begin
      Result := True;
      Exit;
    end;
    Parent := ExtractFileDir(Path);
    if Parent = Path then Exit;
    Path := Parent;
  end;
end;

function SafeTree(Path: String): Boolean;
var Find: TFindRec;
begin
  Result := False;
  if LinkedPath(Path) then Exit;
  if FindFirst(AddBackslash(Path) + '*', Find) then begin
    try
      repeat
        if (Find.Name <> '.') and (Find.Name <> '..') then begin
          if (Find.Attributes and $400) <> 0 then Exit;
          if (Find.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
            if not SafeTree(AddBackslash(Path) + Find.Name) then Exit;
        end;
      until not FindNext(Find);
    finally
      FindClose(Find);
    end;
  end;
  Result := True;
end;

function WithinPath(Path, Base: String): Boolean;
begin
  Result := Pos(Lowercase(AddBackslash(Base)), Lowercase(AddBackslash(Path))) = 1;
end;

function SafeProgramDirectory(Path: String): Boolean;
var Parent, Previous, Name: String; Find: TFindRec;
begin
  Result := False;
  Path := RemoveBackslashUnlessRoot(ExpandFileName(Path));
  if (Length(Path) <= 3) or (Copy(Path, 2, 2) <> ':\') or LinkedPath(Path) then Exit;
  if WithinPath(Path, ExpandConstant('{win}')) or WithinPath(Path, ExpandConstant('{commonpf}')) or
     WithinPath(Path, ExpandConstant('{commonpf32}')) or
     WithinPath(Path, ExpandConstant('{commonappdata}')) or
     WithinPath(Path, ExpandConstant('{localappdata}\Mayotter')) or
     (CompareText(Path, ExpandConstant('{userdocs}\Mayotter')) = 0) then Exit;
  Parent := Path;
  while Length(Parent) > 3 do begin
    if DirExists(AddBackslash(Parent) + '.git') or FileExists(AddBackslash(Parent) + '.git') or
       FileExists(AddBackslash(Parent) + 'pyproject.toml') then Exit;
    Name := Lowercase(ExtractFileName(Parent));
    if (Name = 'data') or (Name = 'data_dev') or (Name = 'profiles') or
       (Name = 'recordings') or (Name = 'audio_visual') or (Name = 'audio_visual_dev') then Exit;
    Parent := ExtractFileDir(Parent);
  end;
  if DirExists(Path + '\src') or DirExists(Path + '\data') or DirExists(Path + '\data_dev') or
     DirExists(Path + '\profiles') or DirExists(Path + '\recordings') or
     DirExists(Path + '\audio_visual') or DirExists(Path + '\config') then Exit;
  Previous := '';
  RegQueryStringValue(HKCU64, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7A299DDE-FA63-4A6C-A257-C9EF9894F35C}_is1',
                      'InstallLocation', Previous);
  if (Previous <> '') and (CompareText(RemoveBackslashUnlessRoot(Previous), Path) = 0) then begin
    if not FileExists(Path + '\Mayotter.exe') or not FileExists(Path + '\mayotter-installed.ini') then Exit;
    if FindFirst(Path + '\*.exe', Find) then begin
      try
        repeat
          Name := Lowercase(Find.Name);
          if (Name <> 'mayotter.exe') and (Name <> 'unins000.exe') then Exit;
        until not FindNext(Find);
      finally
        FindClose(Find);
      end;
    end;
    Result := SafeTree(Path);
    Exit;
  end;
  if DirExists(Path) and FindFirst(Path + '\*', Find) then begin
    try
      repeat
        if (Find.Name <> '.') and (Find.Name <> '..') then Exit;
      until not FindNext(Find);
    finally
      FindClose(Find);
    end;
  end;
  Result := True;
end;

function ChooseSetupLanguage(): String;
var Form: TSetupForm; Prompt: TNewStaticText; Box: TNewComboBox; Ok, Cancel: TNewButton; Ui: Integer;
begin
  { Own language dialog: the built-in one focuses the combo box, whose blue selection bar and focus underline spill
    out of the frame in the dark style. Here the OK button has the focus, so the combo box is drawn plainly. }
  Result := '';
  Form := CreateCustomForm(ScaleX(380), ScaleY(150), False, True);
  try
    Form.Caption := 'Language / ' + #$8A00 + #$8A9E + ' / ' + #$8BED + #$8A00;
    Prompt := TNewStaticText.Create(Form);
    Prompt.Parent := Form;
    Prompt.AutoSize := False;
    Prompt.WordWrap := True;
    Prompt.SetBounds(ScaleX(20), ScaleY(16), ScaleX(340), ScaleY(40));
    Prompt.Caption := 'Select the language to use during setup.';
    Box := TNewComboBox.Create(Form);
    Box.Parent := Form;
    Box.Style := csDropDownList;
    Box.SetBounds(ScaleX(20), ScaleY(60), ScaleX(340), ScaleY(24));
    Box.Items.Add('English');
    Box.Items.Add(#$65E5 + #$672C + #$8A9E);
    Box.Items.Add(#$7B80 + #$4F53 + #$4E2D + #$6587);
    Ui := GetUILanguage and $3FF;
    if Ui = $11 then Box.ItemIndex := 1
    else if Ui = $04 then Box.ItemIndex := 2
    else Box.ItemIndex := 0;
    Ok := TNewButton.Create(Form);
    Ok.Parent := Form;
    Ok.SetBounds(ScaleX(172), ScaleY(110), ScaleX(92), ScaleY(26));
    Ok.Caption := SetupMessage(msgButtonOK);
    Ok.Default := True;
    Ok.ModalResult := mrOK;
    Cancel := TNewButton.Create(Form);
    Cancel.Parent := Form;
    Cancel.SetBounds(ScaleX(268), ScaleY(110), ScaleX(92), ScaleY(26));
    Cancel.Caption := SetupMessage(msgButtonCancel);
    Cancel.Cancel := True;
    Cancel.ModalResult := mrCancel;
    Form.ActiveControl := Ok;
    if Form.ShowModal = mrOK then
      case Box.ItemIndex of
        1: Result := 'japanese';
        2: Result := 'chinesesimplified';
      else
        Result := 'english';
      end;
  finally
    Form.Free;
  end;
end;

function InitializeSetup(): Boolean;
var Language: String; ErrorCode: Integer;
begin
  Result := True;
  { Silent installs (including automatic updates) and an explicit /LANG never show the dialog. }
  if WizardSilent or (ExpandConstant('{param:LANG|}') <> '') then Exit;
  Language := ChooseSetupLanguage();
  Result := False;
  if Language = '' then Exit;
  { The language is fixed when Setup starts, so start Setup again with it. The short delay lets this instance
    release the Setup mutex first. }
  Exec(ExpandConstant('{cmd}'), '/c ping -n 2 127.0.0.1 >nul & start "" "' + ExpandConstant('{srcexe}') + '" ' +
    GetCmdTail + ' /LANG=' + Language, '', SW_HIDE, ewNoWait, ErrorCode);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then begin
    Result := SafeProgramDirectory(WizardDirValue);
    if not Result then MsgBox(CustomMessage('UnsafeDirectory'), mbError, MB_OK);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  DataRoot, ProgramRoot: String;
begin
  Result := '';
  if not SafeProgramDirectory(ExpandConstant('{app}')) then begin
    Result := CustomMessage('UnsafeDirectory');
    Exit;
  end;
  DataRoot := Lowercase(AddBackslash(ExpandConstant('{localappdata}\Mayotter')));
  ProgramRoot := Lowercase(AddBackslash(ExpandConstant('{app}')));
  if Pos(DataRoot, ProgramRoot) = 1 then begin
    Result := FmtMessage(CustomMessage('SeparateData'), [ExpandConstant('{localappdata}\Mayotter')]);
    Exit;
  end;
  if CheckForMutexes('Local\Mayotter.Installed') then
    Result := FmtMessage(SetupMessage(msgSetupAppRunningError), ['Mayotter']);
end;

function InitializeUninstall(): Boolean;
begin
  Result := SafeProgramDirectory(ExpandConstant('{app}'));
  if not Result then MsgBox(CustomMessage('UnsafeDirectory'), mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Previous: String;
begin
  { Keep a record of a previous location before Inno replaces its registration. }
  if CurStep = ssInstall then
    if RegQueryStringValue(HKCU64, UninstallKey, 'InstallLocation', Previous) then
      if (Previous <> '') and
         (CompareText(NormalPath(Previous), NormalPath(ExpandConstant('{app}'))) <> 0) and
         FileExists(AddBackslash(Previous) + 'mayotter-installed.ini') then
        if not RegWriteStringValue(HKCU64, InstalledCopiesKey,
            GetSHA256OfString(Lowercase(NormalPath(Previous))), Previous) then
          RaiseException(CustomMessage('UnsafeUserData'));
end;

function ExclusiveUserData(): Boolean;
var Names: TArrayOfString; I, Root: Integer; Path, App: String;
begin
  Result := False;
  App := NormalPath(ExpandConstant('{app}'));
  if not RegQueryStringValue(HKCU64, InstalledCopiesKey, InstallCopyKey(''), Path) then Exit;
  if CompareText(NormalPath(Path), App) <> 0 then Exit;
  if not RegGetValueNames(HKCU64, InstalledCopiesKey, Names) then Exit;
  for I := 0 to GetArrayLength(Names) - 1 do begin
    if not RegQueryStringValue(HKCU64, InstalledCopiesKey, Names[I], Path) then Exit;
    { Unknown/offline copies are retained as consumers, without searching disks. }
    if (Path = '') or (CompareText(NormalPath(Path), App) <> 0) then Exit;
  end;
  for I := 0 to 3 do begin
    case I of
      0: Root := HKCU64;
      1: Root := HKCU32;
      2: Root := HKLM64;
      3: Root := HKLM32;
    end;
    if RegKeyExists(Root, UninstallKey) then begin
      if not RegQueryStringValue(Root, UninstallKey, 'InstallLocation', Path) then Exit;
      if (Path = '') or (CompareText(NormalPath(Path), App) <> 0) then Exit;
    end;
  end;
  Result := True;
end;

function SafeUserData(Path: String): Boolean;
var Parent: String;
begin
  Result := False;
  Path := NormalPath(Path);
  if (Length(Path) <= 3) or (Copy(Path, 2, 2) <> ':\') or
     (CompareText(Path, NormalPath(ExpandConstant('{localappdata}\Mayotter'))) <> 0) or
     WithinPath(Path, NormalPath(ExpandConstant('{app}'))) or
     WithinPath(Path, ExpandConstant('{userdocs}\Mayotter')) or
     FileExists(Path) or not SafeTree(Path) then Exit;
  Parent := Path;
  while Length(Parent) > 3 do begin
    if DirExists(Parent + '\.git') or FileExists(Parent + '\.git') or
       FileExists(Parent + '\pyproject.toml') or DirExists(Parent + '\src') or
       DirExists(Parent + '\data_dev') then Exit;
    Parent := ExtractFileDir(Parent);
  end;
  Result := ExclusiveUserData() and not CheckForMutexes('Local\Mayotter.Installed');
end;

var UserDataFolder: String;

procedure OpenUserDataFolderClick(Sender: TObject);
var ErrorCode: Integer;
begin
  { Opens exactly the folder shown in this dialog (the deletion target). }
  ShellExec('open', UserDataFolder, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

function ChooseUserDataRemoval(Path: String): Boolean;
var Form: TSetupForm; KeepData, DeleteData: TNewRadioButton;
    Details: TNewStaticText; Proceed, Cancel, OpenFolder: TNewButton;
begin
  Result := False;
  Form := CreateCustomForm(ScaleX(560), ScaleY(320), True, True);
  try
    Form.Caption := CustomMessage('UserDataTitle');
    KeepData := TNewRadioButton.Create(Form);
    KeepData.Parent := Form;
    KeepData.SetBounds(ScaleX(20), ScaleY(16), ScaleX(520), ScaleY(24));
    KeepData.Caption := CustomMessage('KeepUserData');
    KeepData.Checked := True;
    DeleteData := TNewRadioButton.Create(Form);
    DeleteData.Parent := Form;
    DeleteData.SetBounds(ScaleX(20), ScaleY(48), ScaleX(520), ScaleY(24));
    DeleteData.Caption := CustomMessage('DeleteUserData');
    Details := TNewStaticText.Create(Form);
    Details.Parent := Form;
    Details.AutoSize := False;
    Details.WordWrap := True;
    Details.SetBounds(ScaleX(20), ScaleY(88), ScaleX(520), ScaleY(176));
    Details.Caption := FmtMessage(CustomMessage('UserDataDetails'), [Path]);
    Proceed := TNewButton.Create(Form);
    Proceed.Parent := Form;
    Proceed.SetBounds(ScaleX(344), ScaleY(280), ScaleX(92), ScaleY(26));
    Proceed.Caption := SetupMessage(msgButtonOK);
    Proceed.Default := True;
    Proceed.ModalResult := mrOK;
    Cancel := TNewButton.Create(Form);
    Cancel.Parent := Form;
    Cancel.SetBounds(ScaleX(448), ScaleY(280), ScaleX(92), ScaleY(26));
    Cancel.Caption := SetupMessage(msgButtonCancel);
    Cancel.Cancel := True;
    Cancel.ModalResult := mrCancel;
    UserDataFolder := Path;
    OpenFolder := TNewButton.Create(Form);
    OpenFolder.Parent := Form;
    OpenFolder.SetBounds(ScaleX(20), ScaleY(280), ScaleX(140), ScaleY(26));
    OpenFolder.Caption := CustomMessage('OpenUserDataFolder');
    OpenFolder.OnClick := @OpenUserDataFolderClick;
    OpenFolder.Enabled := DirExists(Path);
    Form.ActiveControl := KeepData;
    if Form.ShowModal <> mrOK then Abort;
    Result := DeleteData.Checked;
  finally
    Form.Free;
  end;
end;

procedure CurUninstallStepChanged(CurStep: TUninstallStep);
var Path: String; ErrorCode: LongWord;
begin
  if (CurStep <> usUninstall) or UninstallSilent then Exit;
  Path := NormalPath(ExpandConstant('{localappdata}\Mayotter'));
  if not ChooseUserDataRemoval(Path) then Exit;
  if MsgBox(FmtMessage(CustomMessage('ConfirmUserData'), [Path]), mbConfirmation,
      MB_YESNO or MB_DEFBUTTON2) <> IDYES then Abort;
  if not SafeUserData(Path) then begin
    MsgBox(CustomMessage('UnsafeUserData'), mbError, MB_OK);
    Abort;
  end;
  if GetFileAttributesW(Path) = $FFFFFFFF then begin
    ErrorCode := DLLGetLastError;
    { DelTree reports failure for an already absent directory. }
    if (ErrorCode = 2) or (ErrorCode = 3) then Exit;
  end;
  { usPostUninstall errors are nonfatal in Inno. Fail before its normal removal
    starts so a data deletion error cannot be followed by a success message. }
  if not DelTree(Path, True, True, True) or DirExists(Path) or FileExists(Path) then begin
    MsgBox(FmtMessage(CustomMessage('UserDataDeleteFailed'), [Path]), mbError, MB_OK);
    Abort;
  end;
  Log('Mayotter installed user data removed: ' + Path);
end;

