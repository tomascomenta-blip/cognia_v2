# Informe — Apagado automático programado

**Fecha de configuración:** 2026-06-15 23:00 (hora local, UTC−05:00 / SA Pacific)
**Ejecutado por:** sesión manager autónomo
**Script:** `scripts/auto_shutdown.py`

## Qué se configuró exactamente

| Parámetro | Valor |
|---|---|
| Mecanismo nativo | Windows Task Scheduler (cmdlets `*-ScheduledTask*` vía PowerShell) |
| Nombre de la tarea | `CogniaAutoShutdown` |
| Disparador | **Una sola vez** (`MSFT_TaskTimeTrigger`, `-Once`) |
| Próxima ejecución | **2026-06-16 04:30:00** (hora local) |
| Acción | `shutdown.exe /s /t 60 /c "…"` |
| Gracia antes de apagar | **60 s** (aviso al usuario) |
| Forzado de apps | **NO** (sin `/f`): un documento sin guardar **cancela** el apagado |
| Opciones | `AllowStartIfOnBatteries`, `DontStopIfGoingOnBatteries`, `WakeToRun`, `StartWhenAvailable` |
| Principal | Usuario actual, "ejecutar solo si el usuario inició sesión" (sin credenciales almacenadas, sin elevación) |

### Verificación realizada (salida real)
```
State      : Ready
Action     : shutdown.exe /s /t 60 /c "Cognia: apagado automatico programado. Guarda tu trabajo (shutdown /a para cancelar)."
NextRun    : 06/16/2026 04:30:00
Trigger    : MSFT_TaskTimeTrigger
```

## Comportamiento al dispararse
A las 04:30 el sistema lanza `shutdown /s /t 60`: aparece un aviso, espera 60 s y
apaga **con gracia** (cierra sesión normalmente, sin matar procesos a la fuerza).

## Cómo cancelar / cambiar

| Acción | Comando |
|---|---|
| Abortar el apagado ya iniciado (durante los 60 s) | `shutdown /a` |
| Cancelar la tarea (borrarla) | `.\venv312\Scripts\python.exe scripts\auto_shutdown.py --cancel` |
| Verificar el estado | `.\venv312\Scripts\python.exe scripts\auto_shutdown.py --verify` |
| Reprogramar a otra hora | `.\venv312\Scripts\python.exe scripts\auto_shutdown.py --at HH:MM` |
| Hacerlo recurrente cada día | `.\venv312\Scripts\python.exe scripts\auto_shutdown.py --daily` |
| Borrado manual nativo | `schtasks /delete /tn CogniaAutoShutdown /f` |

## Decisiones de diseño (por qué así)
- **Una sola vez, no diario:** acota *esta* sesión nocturna sin sorprender al
  equipo las noches siguientes. Si se quiere recurrente, `--daily`.
- **Sin `/f`:** prioriza no perder trabajo no guardado sobre garantizar el apagado.
- **`WakeToRun`:** si la laptop entra en suspensión, despierta para apagar limpio.
- **Sin elevación:** apagar el equipo local no requiere admin para el usuario interactivo.
- **`Register-ScheduledTask` con `DateTime` real (no `schtasks /sd`):** evita el
  problema de formato de fecha dependiente del locale.
