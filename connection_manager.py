"""
Gestor de conexiones WebSocket para conductores y pasajeros.
"""

import asyncio
import json
import websockets
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse, parse_qs
from utils import (
    filter_vehicles_by_proximity,
    validate_coordinates,
    create_error_message,
    create_success_message,
)

from logger_config import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """Maneja todas las conexiones WebSocket de conductores y pasajeros."""

    def __init__(self, api_client, passenger_api_key: str):
        """
        Inicializa el gestor de conexiones.

        Args:
            api_client: Cliente para la API REST
            passenger_api_key: Clave de API válida para pasajeros
        """
        self.api_client = api_client
        self.passenger_api_key = passenger_api_key

        # Registro de conductores: {license_plate: websocket}
        self.drivers: Dict[str, websockets.WebSocketServerProtocol] = {}

        # Registro de pasajeros: {websocket: {lat, lng, zoom}}
        self.passengers: Dict[websockets.WebSocketServerProtocol, Dict[str, Any]] = {}

        # Mapping adicional para debugging
        self.connection_info: Dict[
            websockets.WebSocketServerProtocol, Dict[str, Any]
        ] = {}

        logger.info("ConnectionManager inicializado")

    async def handle_connection(self, websocket: websockets.WebSocketServerProtocol):
        """
        Maneja una nueva conexión WebSocket.

        Args:
            websocket: Conexión WebSocket del cliente
        """
        client_address = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"Nueva conexión desde {client_address}")

        try:
            # Obtener parámetros de la URL de conexión
            parsed_url = urlparse(websocket.path)
            query_params = parse_qs(parsed_url.query)

            # Verificar si es conductor (con token Bearer)
            token = query_params.get("token", [None])[0]

            # Verificar si es pasajero (con api_key y coordenadas)
            api_key = query_params.get("api_key", [None])[0]
            lat = query_params.get("lat", [None])[0]
            lng = query_params.get("lng", [None])[0]
            zoom = query_params.get("zoom", [1000])[0]  # Default zoom 1000 metros

            if token:
                # Manejar conexión de conductor
                await self._handle_driver_connection(websocket, token, client_address)
            elif api_key and lat and lng:
                # Manejar conexión de pasajero
                await self._handle_passenger_connection(
                    websocket, api_key, lat, lng, zoom, client_address
                )
            else:
                # Parámetros insuficientes
                error_msg = create_error_message(
                    "Parámetros de autenticación insuficientes. "
                    "Conductor: requiere 'token'. Pasajero: requiere 'api_key', 'lat', 'lng'",
                    "AUTH_ERROR",
                )
                await self._send_message(websocket, error_msg)
                await websocket.close(code=1008, reason="Parámetros insuficientes")

        except Exception as e:
            logger.error(f"Error manejando conexión desde {client_address}: {e}")
            error_msg = create_error_message(
                f"Error interno del servidor: {e}", "SERVER_ERROR"
            )
            try:
                await self._send_message(websocket, error_msg)
                await websocket.close(code=1011, reason="Error interno")
            except:
                pass

    async def _handle_driver_connection(
        self,
        websocket: websockets.WebSocketServerProtocol,
        token: str,
        client_address: str,
    ):
        """
        Maneja la conexión de un conductor.

        Args:
            websocket: Conexión WebSocket del conductor
            token: Token Bearer del conductor
            client_address: Dirección del cliente
        """
        try:
            # Validar token y obtener perfil
            user_profile = await self.api_client.get_user_profile(token)

            if not user_profile:
                error_msg = create_error_message(
                    "Token inválido o expirado", "AUTH_ERROR"
                )
                await self._send_message(websocket, error_msg)
                await websocket.close(code=1008, reason="Token inválido")
                return

            # Obtener vehículos del conductor
            vehicles = await self.api_client.get_vehicles(token)

            if not vehicles:
                error_msg = create_error_message(
                    "No se encontraron vehículos asociados", "NO_VEHICLES"
                )
                await self._send_message(websocket, error_msg)
                await websocket.close(code=1008, reason="Sin vehículos")
                return

            # Registrar conductor por cada vehículo
            registered_plates = []
            for vehicle in vehicles:
                license_plate = vehicle.get("license_plate") or vehicle.get("name")
                if license_plate:
                    self.drivers[license_plate] = websocket
                    registered_plates.append(license_plate)

            if not registered_plates:
                error_msg = create_error_message(
                    "Vehículos sin matrícula válida", "INVALID_PLATES"
                )
                await self._send_message(websocket, error_msg)
                await websocket.close(code=1008, reason="Matrículas inválidas")
                return

            # Guardar información de la conexión
            self.connection_info[websocket] = {
                "type": "driver",
                "user_id": user_profile.get("id"),
                "email": user_profile.get("email"),
                "vehicles": vehicles,
                "license_plates": registered_plates,
                "connected_at": asyncio.get_event_loop().time(),
            }

            # Enviar confirmación de conexión
            success_msg = create_success_message(
                {
                    "user": user_profile,
                    "vehicles": vehicles,
                    "registered_plates": registered_plates,
                },
                "driver_connected",
            )

            await self._send_message(websocket, success_msg)

            logger.info(
                f"Conductor conectado desde {client_address}: {user_profile.get('email')} con {len(registered_plates)} vehículo(s)"
            )

            # Mantener la conexión activa
            await self._keep_connection_alive(websocket)

        except Exception as e:
            logger.error(f"Error en conexión de conductor desde {client_address}: {e}")
            error_msg = create_error_message(
                f"Error procesando conexión de conductor: {e}", "DRIVER_ERROR"
            )
            try:
                await self._send_message(websocket, error_msg)
                await websocket.close(code=1011, reason="Error interno")
            except:
                pass

    async def _handle_passenger_connection(
        self,
        websocket: websockets.WebSocketServerProtocol,
        api_key: str,
        lat: str,
        lng: str,
        zoom: str,
        client_address: str,
    ):
        """
        Maneja la conexión de un pasajero.

        Args:
            websocket: Conexión WebSocket del pasajero
            api_key: Clave de API del pasajero
            lat: Latitud del pasajero
            lng: Longitud del pasajero
            zoom: Nivel de zoom
            client_address: Dirección del cliente
        """
        try:
            # Validar clave de API
            if api_key != self.passenger_api_key:
                error_msg = create_error_message("Clave de API inválida", "AUTH_ERROR")
                await self._send_message(websocket, error_msg)
                await websocket.close(code=1008, reason="API key inválida")
                return

            # Validar y convertir coordenadas
            try:
                lat_float = float(lat)
                lng_float = float(lng)
            except ValueError:
                error_msg = create_error_message(
                    "Coordenadas inválidas", "INVALID_COORDS"
                )
                await self._send_message(websocket, error_msg)
                await websocket.close(code=1008, reason="Coordenadas inválidas")
                return

            if not validate_coordinates(lat_float, lng_float):
                error_msg = create_error_message(
                    "Coordenadas fuera de rango válido", "COORDS_OUT_OF_RANGE"
                )
                await self._send_message(websocket, error_msg)
                await websocket.close(code=1008, reason="Coordenadas inválidas")
                return

            zoom_level = int(zoom)

            # Registrar pasajero
            passenger_data = {
                "latitude": lat_float,
                "longitude": lng_float,
                "zoom": zoom_level,
                "connected_at": asyncio.get_event_loop().time(),
            }

            self.passengers[websocket] = passenger_data

            # Guardar información de la conexión
            self.connection_info[websocket] = {
                "type": "passenger",
                "latitude": lat_float,
                "longitude": lng_float,
                "zoom": zoom_level,
                "connected_at": passenger_data["connected_at"],
            }

            # Enviar confirmación de conexión
            success_msg = create_success_message(
                {
                    "latitude": lat_float,
                    "longitude": lng_float,
                    "zoom": zoom_level,
                    "status": "connected",
                },
                "passenger_connected",
            )

            await self._send_message(websocket, success_msg)

            logger.info(
                f"Pasajero conectado desde {client_address}: lat={lat_float}, lng={lng_float}, zoom={zoom_level}"
            )

            # Mantener la conexión activa
            await self._keep_connection_alive(websocket)

        except Exception as e:
            logger.error(f"Error en conexión de pasajero desde {client_address}: {e}")
            error_msg = create_error_message(
                f"Error procesando conexión de pasajero: {e}", "PASSENGER_ERROR"
            )
            try:
                await self._send_message(websocket, error_msg)
                await websocket.close(code=1011, reason="Error interno")
            except:
                pass

    async def _keep_connection_alive(
        self, websocket: websockets.WebSocketServerProtocol
    ):
        """
        Mantiene la conexión WebSocket activa y maneja mensajes entrantes.

        Args:
            websocket: Conexión WebSocket
        """
        try:
            async for message in websocket:
                try:
                    # Procesar mensajes del cliente
                    await self._handle_client_message(websocket, message)
                except json.JSONDecodeError:
                    error_msg = create_error_message(
                        "Mensaje JSON inválido", "INVALID_JSON"
                    )
                    await self._send_message(websocket, error_msg)
                except Exception as e:
                    logger.error(f"Error procesando mensaje de cliente: {e}")
                    error_msg = create_error_message(
                        f"Error procesando mensaje: {e}", "MESSAGE_ERROR"
                    )
                    await self._send_message(websocket, error_msg)

        except websockets.exceptions.ConnectionClosed:
            logger.info("Cliente desconectado")
        except Exception as e:
            logger.error(f"Error en conexión con cliente: {e}")
        finally:
            await self._cleanup_connection(websocket)

    async def _handle_client_message(
        self, websocket: websockets.WebSocketServerProtocol, message: str
    ):
        """
        Procesa mensajes recibidos de los clientes.

        Args:
            websocket: Conexión WebSocket del cliente
            message: Mensaje recibido
        """
        try:
            data = json.loads(message)
            message_type = data.get("type", "")

            if message_type == "ping":
                # Responder a ping con pong
                pong_msg = create_success_message({"status": "pong"}, "pong")
                await self._send_message(websocket, pong_msg)

            elif message_type == "update_location" and websocket in self.passengers:
                # Actualizar ubicación de pasajero
                await self._update_passenger_location(websocket, data)

            elif message_type == "get_status":
                # Enviar estado de la conexión
                await self._send_connection_status(websocket)

            else:
                logger.debug(f"Tipo de mensaje no reconocido: {message_type}")

        except Exception as e:
            logger.error(f"Error procesando mensaje del cliente: {e}")
            raise

    async def _update_passenger_location(
        self, websocket: websockets.WebSocketServerProtocol, data: Dict[str, Any]
    ):
        """
        Actualiza la ubicación de un pasajero.

        Args:
            websocket: Conexión WebSocket del pasajero
            data: Datos del mensaje con nueva ubicación
        """
        try:
            new_lat = float(data.get("latitude", 0))
            new_lng = float(data.get("longitude", 0))
            new_zoom = int(data.get("zoom", 1000))

            if validate_coordinates(new_lat, new_lng):
                # Actualizar datos del pasajero
                self.passengers[websocket].update(
                    {"latitude": new_lat, "longitude": new_lng, "zoom": new_zoom}
                )

                self.connection_info[websocket].update(
                    {"latitude": new_lat, "longitude": new_lng, "zoom": new_zoom}
                )

                # Confirmar actualización
                success_msg = create_success_message(
                    {"latitude": new_lat, "longitude": new_lng, "zoom": new_zoom},
                    "location_updated",
                )

                await self._send_message(websocket, success_msg)

                logger.debug(
                    f"Ubicación de pasajero actualizada: lat={new_lat}, lng={new_lng}, zoom={new_zoom}"
                )
            else:
                error_msg = create_error_message(
                    "Coordenadas inválidas", "INVALID_COORDS"
                )
                await self._send_message(websocket, error_msg)

        except (ValueError, TypeError) as e:
            error_msg = create_error_message(
                f"Error en datos de ubicación: {e}", "LOCATION_ERROR"
            )
            await self._send_message(websocket, error_msg)

    async def _send_connection_status(
        self, websocket: websockets.WebSocketServerProtocol
    ):
        """
        Envía el estado actual de la conexión.

        Args:
            websocket: Conexión WebSocket del cliente
        """
        connection_info = self.connection_info.get(websocket, {})
        status_data = {
            "type": connection_info.get("type", "unknown"),
            "connected_at": connection_info.get("connected_at", 0),
            "total_drivers": len(self.drivers),
            "total_passengers": len(self.passengers),
        }

        if connection_info.get("type") == "driver":
            status_data["license_plates"] = connection_info.get("license_plates", [])
        elif connection_info.get("type") == "passenger":
            status_data.update(
                {
                    "latitude": connection_info.get("latitude"),
                    "longitude": connection_info.get("longitude"),
                    "zoom": connection_info.get("zoom"),
                }
            )

        status_msg = create_success_message(status_data, "status")
        await self._send_message(websocket, status_msg)

    async def _cleanup_connection(self, websocket: websockets.WebSocketServerProtocol):
        """
        Limpia los recursos de una conexión cerrada.

        Args:
            websocket: Conexión WebSocket a limpiar
        """
        try:
            # Limpiar registro de conductores
            plates_to_remove = [
                plate for plate, ws in self.drivers.items() if ws == websocket
            ]
            for plate in plates_to_remove:
                del self.drivers[plate]
                logger.debug(f"Conductor desregistrado: {plate}")

            # Limpiar registro de pasajeros
            if websocket in self.passengers:
                del self.passengers[websocket]
                logger.debug("Pasajero desregistrado")

            # Limpiar información de conexión
            if websocket in self.connection_info:
                connection_type = self.connection_info[websocket].get("type", "unknown")
                del self.connection_info[websocket]
                logger.info(f"Conexión {connection_type} limpiada")

        except Exception as e:
            logger.error(f"Error limpiando conexión: {e}")

    async def broadcast_to_drivers(self, vehicle_updates: List[Dict[str, Any]]):
        """
        Envía actualizaciones de vehículos a los conductores correspondientes.

        Args:
            vehicle_updates: Lista de vehículos actualizados
        """
        if not vehicle_updates or not self.drivers:
            logger.warning(
                "Broadcast a conductores omitido: no hay actualizaciones o no hay conductores conectados."
            )
            return

        logger.debug(
            f"Iniciando broadcast a {len(self.drivers)} conductores. Conductores conectados: {list(self.drivers.keys())}"
        )

        for vehicle in vehicle_updates:
            license_plate = vehicle.get("license_plate") or vehicle.get("name")
            logger.debug(
                f"Procesando actualización para vehículo con matrícula: {license_plate}"
            )

            if license_plate in self.drivers:
                websocket = self.drivers[license_plate]
                logger.debug(
                    f"Conductor encontrado para {license_plate}. Enviando actualización."
                )
                try:
                    message = create_success_message(vehicle, "vehicle_update")
                    await self._send_message(websocket, message)

                except websockets.exceptions.ConnectionClosed:
                    logger.warning(f"Conexión cerrada para conductor {license_plate}")
                    # La limpieza se hará en _cleanup_connection

                except Exception as e:
                    logger.error(
                        f"Error enviando actualización a conductor {license_plate}: {e}"
                    )
            else:
                logger.warning(
                    f"No se encontró conductor conectado para la matrícula: {license_plate}"
                )

    async def broadcast_to_passengers(self, vehicle_updates: List[Dict[str, Any]]):
        """
        Envía vehículos cercanos a los pasajeros según su ubicación y zoom.

        Args:
            vehicle_updates: Lista de vehículos actualizados
        """
        if not vehicle_updates or not self.passengers:
            return

        # Crear tareas para envío paralelo
        tasks = []

        for websocket, passenger_data in self.passengers.items():
            task = self._send_filtered_vehicles_to_passenger(
                websocket, passenger_data, vehicle_updates
            )
            tasks.append(task)

        # Ejecutar todas las tareas en paralelo
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_filtered_vehicles_to_passenger(
        self,
        websocket: websockets.WebSocketServerProtocol,
        passenger_data: Dict[str, Any],
        vehicle_updates: List[Dict[str, Any]],
    ):
        """
        Filtra y envía vehículos a un pasajero específico.

        Args:
            websocket: Conexión del pasajero
            passenger_data: Datos del pasajero (ubicación y zoom)
            vehicle_updates: Lista de vehículos actualizados
        """
        try:
            logger.info(f"Enviando vehículos filtrados a pasajero: {passenger_data}")
            # Filtrar vehículos por proximidad
            nearby_vehicles = filter_vehicles_by_proximity(
                vehicle_updates,
                passenger_data["latitude"],
                passenger_data["longitude"],
                passenger_data["zoom"],
            )
            logger.info(
                f"Vehículos filtrados para pasajero {passenger_data}: {nearby_vehicles}"
            )

            if nearby_vehicles:
                message = create_success_message(
                    {
                        "vehicles": nearby_vehicles,
                        "total": len(nearby_vehicles),
                        "passenger_location": {
                            "latitude": passenger_data["latitude"],
                            "longitude": passenger_data["longitude"],
                        },
                    },
                    "vehicles_update",
                )

                await self._send_message(websocket, message)

        except websockets.exceptions.ConnectionClosed:
            logger.warning("Conexión cerrada para pasajero durante envío")
            # La limpieza se hará en _cleanup_connection

        except Exception as e:
            logger.error(f"Error enviando vehículos a pasajero: {e}")

    async def _send_message(
        self, websocket: websockets.WebSocketServerProtocol, message: Dict[str, Any]
    ):
        """
        Envía un mensaje JSON a través de WebSocket.

        Args:
            websocket: Conexión WebSocket
            message: Mensaje a enviar
        """
        try:
            json_message = json.dumps(message, ensure_ascii=False)
            await websocket.send(json_message)
        except websockets.exceptions.ConnectionClosed:
            raise  # Re-raise para manejo en nivel superior
        except Exception as e:
            logger.error(f"Error enviando mensaje: {e}")
            raise

    def get_connection_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas de las conexiones actuales.

        Returns:
            Dict con estadísticas
        """
        return {
            "total_drivers": len(self.drivers),
            "total_passengers": len(self.passengers),
            "total_connections": len(self.connection_info),
            "driver_vehicles": list(self.drivers.keys()),
            "passenger_locations": [
                {
                    "lat": data["latitude"],
                    "lng": data["longitude"],
                    "zoom": data["zoom"],
                }
                for data in self.passengers.values()
            ],
        }
