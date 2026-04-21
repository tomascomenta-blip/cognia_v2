# test_logs.py
from logger_config import get_logger, safe_execute, log_slow, log_db_error
import time

logger = get_logger(__name__)

# 1. Niveles básicos
logger.debug("debug message", extra={"op": "test.debug", "context": "prueba"})
logger.info("info message", extra={"op": "test.info", "context": "prueba"})
logger.warning("warning message", extra={"op": "test.warning", "context": "prueba"})
logger.error("error message", extra={"op": "test.error", "context": "prueba"})

# 2. safe_execute con fallo
result = safe_execute(
    lambda: 1 / 0,
    context="test.division",
    fallback="FALLBACK_VALUE",
    logger=logger,
)
print("Resultado fallback:", result)

# 3. log_slow
t0 = time.perf_counter()
time.sleep(0.3)  # simular operación lenta
log_slow(logger, "test.operacion_lenta", t0, threshold_ms=100)

# 4. log_db_error
import sqlite3
try:
    sqlite3.connect("/ruta/inexistente/x/y/z.db").execute("SELECT 1")
except Exception as e:
    log_db_error(logger, "test.db_error", e, extra_ctx="tabla=episodic_memory")