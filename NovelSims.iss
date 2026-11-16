; NovelSims 一键安装程序 (Inno Setup 6)
#define MyAppName "NovelSims"
#ifndef MyAppVersion
#define MyAppVersion "0.3.6"
#endif
#define MyAppExe "NovelSims.exe"
#define SrcDir "dist\onedir\NovelSims"

[Setup]
AppId={{FDAC9377-24CB-412C-84B6-B85EEEB8721E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=NovelSims
DefaultDirName={localappdata}\Programs\NovelSims
DefaultGroupName=NovelSims
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=NovelSims_Setup_{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
SetupLogging=yes

[Languages]
Name: "chs"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项："

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 游戏端模组文件 -> 文档\Electronic Arts\The Sims 4\Mods\NovelSims\
Source: "gamemod\NovelSims.package"; DestDir: "{userdocs}\Electronic Arts\The Sims 4\Mods\NovelSims"; Flags: ignoreversion
Source: "gamemod\NovelSims.ts4script"; DestDir: "{userdocs}\Electronic Arts\The Sims 4\Mods\NovelSims"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\NovelSims"; Filename: "{app}\{#MyAppExe}"
Name: "{autoprograms}\NovelSims 诊断模式（启动失败时使用）"; Filename: "{app}\NovelSims_debug.exe"
Name: "{autoprograms}\卸载 NovelSims"; Filename: "{uninstallexe}"
Name: "{autodesktop}\NovelSims"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "立即启动 NovelSims"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#MyAppExe}"; Flags: runhidden; RunOnceId: "KillNovelSims"
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im NovelSims_debug.exe"; Flags: runhidden; RunOnceId: "KillNovelSimsDebug"

[UninstallDelete]
Type: dirifempty; Name: "{userdocs}\Electronic Arts\The Sims 4\Mods\NovelSims"
Type: filesandordirs; Name: "{app}\_internal"

[Code]
function WebView2Installed(): Boolean;
var v: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0'));
end;

procedure CurPageChanged(CurPageID: Integer);
var msg, sims: String;
begin
  if CurPageID = wpFinished then
  begin
    sims := ExpandConstant('{userdocs}\Electronic Arts\The Sims 4');
    msg := 'NovelSims 已安装完成。' + #13#10 + #13#10 +
           '游戏模组已放入：' + #13#10 + sims + '\Mods\NovelSims' + #13#10 + #13#10;
    if FileExists(sims + '\Options.ini') then
      msg := msg + '重要：请进入游戏「选项 → 游戏选项 → 其他」，勾选「启用自定义内容和模组」和「允许脚本模组」，然后重启游戏。' + #13#10 + #13#10
    else
      msg := msg + '提示：未检测到《模拟人生4》的设置文件。请确认游戏至少运行过一次，并在游戏「选项 → 游戏选项 → 其他」中勾选「启用自定义内容和模组」和「允许脚本模组」。' + #13#10 + #13#10;
    if not WebView2Installed() then
      msg := msg + '注意：未检测到 Microsoft Edge WebView2 运行库，NovelSims 窗口可能无法显示。请从微软官网下载安装「WebView2 Runtime」：https://developer.microsoft.com/microsoft-edge/webview2/' + #13#10 + #13#10;
    msg := msg + '建议玩游戏时先打开 NovelSims（桌面图标），再启动游戏。';
    WizardForm.FinishedLabel.Caption := msg;
    WizardForm.FinishedLabel.AutoSize := False;
    WizardForm.FinishedLabel.Height := ScaleY(200);
  end;
end;
