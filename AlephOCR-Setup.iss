#ifndef ProductVersion
  #error ProductVersion must be supplied by build_release.py
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by build_release.py
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by build_release.py
#endif

[Setup]
AppId={{F85C858F-C425-4FA0-BAE9-E7F22C33943B}
AppName=Aleph OCR
AppVersion={#ProductVersion}
AppVerName=Aleph OCR {#ProductVersion}
AppPublisher=Aleph OCR
AppComments=OCR hébreu et Rachi hors ligne
AppContact=Aleph OCR
DefaultDirName={autopf}\Aleph OCR
DefaultGroupName=Aleph OCR
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
WizardStyle=modern
SetupIconFile={#SourceDir}\_internal\assets\app.ico
UninstallDisplayIcon={app}\AlephOCR.exe
UninstallDisplayName=Aleph OCR
OutputDir={#OutputDir}
OutputBaseFilename=AlephOCR-Setup
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
ChangesAssociations=no
VersionInfoVersion={#ProductVersion}
VersionInfoDescription=Aleph OCR - installation Windows
VersionInfoProductName=Aleph OCR
VersionInfoCompany=Aleph OCR

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
fr.DesktopShortcut=Créer un raccourci sur le Bureau
en.DesktopShortcut=Create a desktop shortcut
fr.KeepSettings=Conserver les préférences Aleph OCR ? Choisissez Non uniquement pour les supprimer.
en.KeepSettings=Keep Aleph OCR preferences? Choose No only to remove them.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopShortcut}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LICENSE.txt"; DestDir: "{app}\Licenses"; Flags: ignoreversion
Source: "THIRD-PARTY.txt"; DestDir: "{app}\Licenses"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Aleph OCR"; Filename: "{app}\AlephOCR.exe"; WorkingDir: "{app}"; IconFilename: "{app}\AlephOCR.exe"; Comment: "OCR hébreu et Rachi hors ligne"
Name: "{autodesktop}\Aleph OCR"; Filename: "{app}\AlephOCR.exe"; WorkingDir: "{app}"; IconFilename: "{app}\AlephOCR.exe"; Comment: "OCR hébreu et Rachi hors ligne"; Tasks: desktopicon

[Run]
Filename: "{app}\AlephOCR.exe"; Description: "{cm:LaunchProgram,Aleph OCR}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    if MsgBox(ExpandConstant('{cm:KeepSettings}'), mbConfirmation, MB_YESNO or MB_DEFBUTTON1) = IDNO then
      RegDeleteKeyIncludingSubkeys(HKEY_CURRENT_USER, 'Software\AlephOCR');
end;
