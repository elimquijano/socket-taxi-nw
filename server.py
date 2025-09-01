"""
Servidor principal del sistema de taxi en tiempo real.
"""

import asyncio
import os
import signal
import sys
from typing import Optional
import websockets
from dotenv import load_dotenv
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Importar módulos locales
from api_client import ApiClient
from connection_manager import ConnectionManager
from vehicle_manager import VehicleManager

# Configurar uvloop para mejor rendimiento (solo en Linux/macOS)
try:
    import uvloop

    uvloop.install()
    logger.info("uvloop instalado para mejor rendimiento")
except ImportError:
    logger.info("uvloop no disponible, usando asyncio estándar")


class TaxiServer:
    """Servidor principal que orquesta todos los componentes."""

    def __init__(self):
        """Inicializa el servidor."""
        self.api_client: Optional[ApiClient] = None
        self.connection_manager: Optional[ConnectionManager] = None
        self.vehicle_manager: Optional[VehicleManager] = None
        self.server: Optional[websockets.WebSocketServer] = None
        self.running = False

        # Cargar configuración desde variables de entorno
        self._load_config()

        logger.info("TaxiServer inicializado")

    def _load_config(self):
        """Carga la configuración desde variables de entorno."""
        # Cargar archivo .env
        load_dotenv()

        # Configuración del servidor WebSocket
        self.ws_host = os.getenv("WS_HOST", "localhost")
        self.ws_port = int(os.getenv("WS_PORT", 8765))

        # URLs de APIs
        self.api_base_url = os.getenv("API_BASE_URL")
        self.external_ws_url = os.getenv("EXTERNAL_WS_URL")

        # Clave de API para pasajeros
        self.passenger_api_key = os.getenv("PASSENGER_API_KEY")

        

        # Validar configuración crítica
        if not self.api_base_url:
            logger.error("API_BASE_URL no configurada")
            sys.exit(1)

        if not self.external_ws_url:
            logger.error("EXTERNAL_WS_URL no configurada")
            sys.exit(1)

        if not self.passenger_api_key:
            logger.error("PASSENGER_API_KEY no configurada")
            sys.exit(1)

        logger.info(f"Configuración cargada: WS={self.ws_host}:{self.ws_port}")

    async def _initialize_components(self):
        """Inicializa todos los componentes del servidor."""
        try:
            # Inicializar cliente API
            self.api_client = ApiClient(self.api_base_url)
            await self.api_client.start()

            # Verificar conectividad con la API
            if not await self.api_client.health_check():
                logger.warning(
                    "La API no responde al health check, continuando de todas formas..."
                )

            # Inicializar gestor de conexiones
            self.connection_manager = ConnectionManager(
                self.api_client, self.passenger_api_key
            )

            # Inicializar gestor de vehículos
            self.vehicle_manager = VehicleManager()
            self.vehicle_manager.set_connection_manager(self.connection_manager)

            logger.info("Todos los componentes inicializados correctamente")

        except Exception as e:
            logger.error(f"Error inicializando componentes: {e}")
            raise

    async def _handle_websocket_connection(
        self, websocket: websockets.WebSocketServerProtocol
    ):
        """
        Maneja una nueva conexión WebSocket.

        Args:
            websocket: Conexión WebSocket del cliente
        """
        client_address = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.debug(f"Nueva conexión WebSocket desde {client_address}")

        try:
            # Delegar el manejo al ConnectionManager
            await self.connection_manager.handle_connection(websocket)

        except Exception as e:
            logger.error(
                f"Error manejando conexión WebSocket desde {client_address}: {e}"
            )
        finally:
            logger.debug(f"Conexión WebSocket desde {client_address} finalizada")

    async def start(self):
        """Inicia el servidor y todos sus componentes."""
        try:
            logger.info("Iniciando servidor de taxi en tiempo real...")

            # Inicializar componentes
            await self._initialize_components()

            # Iniciar servidor WebSocket
            self.server = await websockets.serve(
                self._handle_websocket_connection,
                self.ws_host,
                self.ws_port,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=10,
                max_size=1024 * 1024,  # 1MB max message size
                max_queue=32,  # Max queued messages per connection
            )

            logger.info(
                f"Servidor WebSocket iniciado en ws://{self.ws_host}:{self.ws_port}"
            )

            # Iniciar gestor de vehículos en segundo plano
            vehicle_task = asyncio.create_task(
                self.vehicle_manager.start(self.external_ws_url)
            )

            logger.info("Gestor de vehículos iniciado")

            self.running = True

            # Registrar manejadores de señales para cierre graceful
            self._setup_signal_handlers()

            logger.info("🚖 Servidor de taxi en tiempo real completamente iniciado")
            logger.info(f"📡 Conectándose a servicio externo: {self.external_ws_url}")
            logger.info(
                f"🌐 Escuchando conexiones WebSocket en: ws://{self.ws_host}:{self.ws_port}"
            )

            # Estadísticas periódicas
            stats_task = asyncio.create_task(self._log_periodic_stats())

            # Esperar hasta que se solicite el cierre
            try:
                await asyncio.gather(vehicle_task, stats_task, return_exceptions=True)
            except asyncio.CancelledError:
                logger.info("Tareas principales canceladas")

        except Exception as e:
            logger.error(f"Error iniciando servidor: {e}")
            raise

    async def stop(self):
        """Detiene el servidor y todos sus componentes de forma graceful."""
        if not self.running:
            return

        logger.info("🛑 Iniciando cierre graceful del servidor...")
        self.running = False

        try:
            # Detener gestor de vehículos
            if self.vehicle_manager:
                await self.vehicle_manager.stop()

            # Cerrar servidor WebSocket
            if self.server:
                logger.info("Cerrando servidor WebSocket...")
                self.server.close()
                await self.server.wait_closed()

            # Cerrar cliente API
            if self.api_client:
                await self.api_client.close()

            logger.info("✅ Servidor cerrado correctamente")

        except Exception as e:
            logger.error(f"Error durante el cierre del servidor: {e}")

    def _setup_signal_handlers(self):
        """Configura manejadores de señales para cierre graceful."""

        def signal_handler(signum, frame):
            logger.info(f"Señal {signum} recibida, iniciando cierre graceful...")
            # Crear tarea de cierre en el event loop
            asyncio.create_task(self.stop())

        # Registrar manejadores solo en sistemas Unix
        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
        else:
            # En Windows, solo manejar Ctrl+C
            signal.signal(signal.SIGINT, signal_handler)

    async def _log_periodic_stats(self):
        """Registra estadísticas periódicamente."""
        while self.running:
            try:
                await asyncio.sleep(60)  # Cada minuto

                if self.connection_manager and self.vehicle_manager:
                    conn_stats = self.connection_manager.get_connection_stats()
                    vehicle_count = self.vehicle_manager.get_vehicles_count()
                    is_connected = self.vehicle_manager.is_connected()

                    logger.info(
                        f"📊 Estadísticas: "
                        f"Conductores={conn_stats['total_drivers']}, "
                        f"Pasajeros={conn_stats['total_passengers']}, "
                        f"Vehículos_rastreados={vehicle_count}, "
                        f"Servicio_externo={'✅' if is_connected else '❌'}"
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error en estadísticas periódicas: {e}")
                continue


async def main():
    """Función principal del servidor."""
    server = TaxiServer()

    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Interrupción de teclado recibida")
    except Exception as e:
        logger.error(f"Error fatal en el servidor: {e}")
        return 1
    finally:
        await server.stop()

    return 0


if __name__ == "__main__":
    try:
        # Ejecutar el servidor
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Servidor interrumpido por el usuario")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error ejecutando servidor: {e}")
        sys.exit(1)
