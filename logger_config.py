
import logging
import sys
import os

def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    """
    Configura y devuelve un logger.
    """
    # Determinar el nivel de logging
    log_level = os.getenv("LOG_LEVEL", level).upper()
    numeric_level = getattr(logging, log_level, logging.INFO)

    # Crear el logger
    logger = logging.getLogger(name)
    logger.setLevel(numeric_level)
    logger.propagate = False  # Evitar que los logs se propaguen al logger raíz

    # Limpiar handlers existentes para evitar duplicados
    if logger.hasHandlers():
        logger.handlers.clear()

    # Crear un handler para la salida estándar (stderr)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(numeric_level)

    # Crear un formato para los logs
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Asignar el formato al handler
    handler.setFormatter(formatter)

    # Añadir el handler al logger
    logger.addHandler(handler)

    return logger
