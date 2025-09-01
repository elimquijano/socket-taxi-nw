"""
Gestor de vehículos que se conecta al servicio WebSocket externo.
"""

import asyncio
import json
import websockets
from typing import Dict, Any, Optional
from logger_config import get_logger

logger = get_logger(__name__)


class VehicleManager:
    """Maneja la conexión con el servicio WebSocket externo de vehículos."""

    def __init__(self):
        """Inicializa el gestor de vehículos."""
        self.vehicle_data_store: Dict[str, Dict[str, Any]] = {}
        self.connection: Optional[websockets.WebSocketServerProtocol] = None
        self.is_running = False
        self.reconnect_delay = 5  # Segundos
        self.max_reconnect_attempts = 5
        self.connection_manager = None
        logger.info("VehicleManager inicializado")

    def set_connection_manager(self, connection_manager):
        """
        Establece la referencia al ConnectionManager.

        Args:
            connection_manager: Instancia del ConnectionManager
        """
        self.connection_manager = connection_manager
        logger.debug("ConnectionManager configurado en VehicleManager")

    async def start(self, uri: str):
        """
        Inicia la conexión con el servicio WebSocket externo.

        Args:
            uri: URI del servicio WebSocket externo
        """
        self.is_running = True
        reconnect_attempts = 0

        logger.info(f"Iniciando conexión a servicio externo: {uri}")

        while self.is_running and reconnect_attempts < self.max_reconnect_attempts:
            try:
                await self._connect_and_listen(uri)
                reconnect_attempts = 0  # Reset counter on successful connection

            except websockets.exceptions.ConnectionClosed:
                logger.warning("Conexión cerrada por el servidor externo")
                reconnect_attempts += 1

            except websockets.exceptions.InvalidURI:
                logger.error(f"URI inválida: {uri}")
                break

            except Exception as e:
                logger.error(f"Error en conexión con servicio externo: {e}")
                reconnect_attempts += 1

            if self.is_running and reconnect_attempts < self.max_reconnect_attempts:
                logger.info(
                    f"Reintentando conexión en {self.reconnect_delay} segundos... (Intento {reconnect_attempts}/{self.max_reconnect_attempts})"
                )
                await asyncio.sleep(self.reconnect_delay)
                # Incrementar delay exponencialmente
                self.reconnect_delay = min(self.reconnect_delay * 2, 60)
            elif reconnect_attempts >= self.max_reconnect_attempts:
                logger.error("Máximo número de intentos de reconexión alcanzado")
                break

    async def _connect_and_listen(self, uri: str):
        """
        Establece la conexión y escucha mensajes del servicio externo.

        Args:
            uri: URI del servicio WebSocket externo
        """
        try:
            async with websockets.connect(
                uri, ping_interval=30, ping_timeout=10, close_timeout=10
            ) as websocket:
                self.connection = websocket
                self.reconnect_delay = 5  # Reset delay on successful connection

                logger.info("Conexión establecida con servicio externo")

                async for message in websocket:
                    if not self.is_running:
                        break

                    try:
                        await self._process_message(message)
                    except Exception as e:
                        logger.error(
                            f"Error procesando mensaje del servicio externo: {e}"
                        )
                        continue

        except websockets.exceptions.ConnectionClosed:
            logger.warning("Conexión con servicio externo cerrada")
            self.connection = None
            raise
        except Exception as e:
            logger.error(f"Error en _connect_and_listen: {e}")
            self.connection = None
            raise

    async def _process_message(self, message: str):
        """
        Procesa un mensaje recibido del servicio externo.

        Args:
            message: Mensaje JSON recibido
        """
        try:
            data = json.loads(message)

            # Log del mensaje recibido (solo en debug)
            logger.debug(f"Mensaje recibido: {len(message)} caracteres")

            # Extraer la lista de dispositivos/vehículos
            devices = data.get("devices", [])

            if not devices:
                logger.warning("No hay dispositivos en el mensaje recibido")
                return

            # Actualizar el almacén de datos
            updated_vehicles = await self._update_vehicle_store(devices)

            if updated_vehicles and self.connection_manager:
                # Notificar a los clientes conectados
                await self._notify_clients(updated_vehicles)

        except json.JSONDecodeError as e:
            logger.error(f"Error decodificando JSON del servicio externo: {e}")
        except Exception as e:
            logger.error(f"Error procesando mensaje: {e}")

    async def _update_vehicle_store(self, devices: list) -> list:
        """
        Actualiza el almacén de datos de vehículos.

        Args:
            devices: Lista de dispositivos recibidos

        Returns:
            Lista de vehículos que han sido actualizados
        """
        updated_vehicles = []

        for device in devices:
            try:
                # Usar 'name' como identificador único (matrícula)
                vehicle_id = device.get("name")

                if not vehicle_id:
                    logger.warning("Dispositivo sin 'name' ignorado")
                    continue

                self.vehicle_data_store[vehicle_id] = device
                updated_vehicles.append(device)
                logger.debug(f"Vehículo actualizado: {vehicle_id}")

            except Exception as e:
                logger.error(f"Error actualizando vehículo: {e}")
                continue

        if updated_vehicles:
            logger.debug(f"Se actualizaron {len(updated_vehicles)} vehículos")

        return updated_vehicles

    async def _notify_clients(self, updated_vehicles: list):
        """
        Notifica a los clientes sobre las actualizaciones de vehículos.

        Args:
            updated_vehicles: Lista de vehículos actualizados
        """
        logger.debug(
            f"Notificando a clientes sobre {len(updated_vehicles)} vehículos actualizados."
        )
        try:
            # Notificar a conductores
            await self.connection_manager.broadcast_to_drivers(updated_vehicles)

            # Notificar a pasajeros
            await self.connection_manager.broadcast_to_passengers(updated_vehicles)

        except Exception as e:
            logger.error(f"Error notificando a clientes: {e}")

    async def stop(self):
        """Detiene el gestor de vehículos."""
        logger.info("Deteniendo VehicleManager...")
        self.is_running = False

        if self.connection:
            try:
                await self.connection.close()
            except Exception as e:
                logger.error(f"Error cerrando conexión: {e}")

        logger.info("VehicleManager detenido")

    def get_vehicle_data(self, vehicle_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene los datos de un vehículo específico.

        Args:
            vehicle_id: ID del vehículo

        Returns:
            Dict con los datos del vehículo o None si no existe
        """
        return self.vehicle_data_store.get(vehicle_id)

    def get_all_vehicles(self) -> Dict[str, Dict[str, Any]]:
        """
        Obtiene todos los datos de vehículos.

        Returns:
            Dict con todos los vehículos
        """
        return self.vehicle_data_store.copy()

    def get_vehicles_count(self) -> int:
        """
        Obtiene el número total de vehículos en el almacén.

        Returns:
            int: Número de vehículos
        """
        return len(self.vehicle_data_store)

    def is_connected(self) -> bool:
        """
        Verifica si está conectado al servicio externo.

        Returns:
            bool: True si está conectado
        """
        return self.connection is not None and not self.connection.closed
