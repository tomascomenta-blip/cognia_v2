; nsis_check_python.nsh
; Checks that Python 3.11+ is available before completing installation.
; Included by electron-builder.config.js via nsis.include.

!macro customInstall
  nsExec::ExecToStack 'python --version'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONEXCLAMATION \
      "Python 3.11+ no encontrado.$\n$\nCognia requiere Python para ejecutar el modelo de IA.$\nDescargalo en: https://python.org/downloads$\n$\nPuedes continuar la instalacion, pero el wizard de configuracion te lo pedira al iniciar."
  ${EndIf}
!macroend

!macro customUnInstall
!macroend
