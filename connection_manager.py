import json
import os
from typing import Dict, Set
from websockets.server import WebSocketServerProtocol
from api_client import ApiClient
from utils import calculate_distance

class ConnectionManager:
    """
    Gestiona todas las conexiones de WebSocket, diferenciando entre
    conductores y pasajeros.
    """
    def __init__(self, api_client: ApiClient):
        self.api_client = api_client
        # Mapea license_plate -> WebSocket
        self.drivers: Dict[str, WebSocketServerProtocol] = {}
        # Mapea WebSocket -> {lat, lon, zoom}
        self.passengers: Dict[WebSocketServerProtocol, Dict] = {}
        self.passenger_api_key = os.getenv("PASSENGER_API_KEY")

    async def handle_connection(self, websocket: WebSocketServerProtocol):
        """
        Maneja una nueva conexión, la autentica y la registra.
        """
        try:
            initial_message = await websocket.recv()
            data = json.loads(initial_message)
            
            auth_type = data.get("type")
            
            if auth_type == "driver" and "token" in data:
                await self._register_driver(websocket, data["token"])
            elif auth_type == "passenger" and "apiKey" in data:
                if data["apiKey"] == self.passenger_api_key:
                    await self._register_passenger(websocket, data)
                else:
                    await websocket.close(1008, "Invalid API Key")
            else:
                await websocket.close(1008, "Invalid authentication")

            # Mantener la conexión viva para recibir futuros mensajes o detectar desconexión
            async for message in websocket:
                # Por ahora, no se espera que los clientes envíen más datos,
                # pero este bucle es necesario para mantener la conexión abierta.
                pass

        except json.JSONDecodeError:
            await websocket.close(1008, "Invalid JSON format")
        except Exception as e:
            print(f"Conexión cerrada inesperadamente: {e}")
        finally:
            self._unregister(websocket)

    async def _register_driver(self, websocket: WebSocketServerProtocol, token: str):
        profile = await self.api_client.get_user_profile(token)
        if not profile:
            await websocket.close(1008, "Invalid token")
            return

        vehicles = await self.api_client.get_vehicles(token)
        if not vehicles:
            await websocket.close(1008, "No vehicles found")
            return

        for vehicle in vehicles.get("data", []):
            license_plate = vehicle.get("license_plate")
            if license_plate:
                self.drivers[license_plate] = websocket
                print(f"Conductor conectado para el vehículo: {license_plate}")
        
        await websocket.send(json.dumps({"status": "connected", "role": "driver"}))

    async def _register_passenger(self, websocket: WebSocketServerProtocol, data: dict):
        try:
            lat = float(data["latitude"])
            lon = float(data["longitude"])
            zoom = int(data["zoom"])
            self.passengers[websocket] = {"latitude": lat, "longitude": lon, "zoom": zoom}
            print(f"Pasajero conectado en: ({lat}, {lon}) con zoom {zoom}m")
            await websocket.send(json.dumps({"status": "connected", "role": "passenger"}))
        except (ValueError, KeyError) as e:
            await websocket.close(1008, f"Invalid passenger data: {e}")

    def _unregister(self, websocket: WebSocketServerProtocol):
        # Eliminar de pasajeros
        if websocket in self.passengers:
            del self.passengers[websocket]
            print("Pasajero desconectado.")
            return

        # Eliminar de conductores (más complejo, necesita encontrar por valor)
        driver_keys_to_remove = [key for key, value in self.drivers.items() if value == websocket]
        for key in driver_keys_to_remove:
            del self.drivers[key]
            print(f"Conductor del vehículo {key} desconectado.")

    async def broadcast_to_drivers(self, vehicle_updates: Dict):
        for license_plate, vehicle_data in vehicle_updates.items():
            if license_plate in self.drivers:
                websocket = self.drivers[license_plate]
                try:
                    await websocket.send(json.dumps(vehicle_data))
                except Exception as e:
                    print(f"Error enviando a conductor {license_plate}: {e}")

    async def broadcast_to_passengers(self, vehicle_updates: Dict):
        all_vehicles = list(vehicle_updates.values())
        
        for websocket, passenger_data in self.passengers.items():
            nearby_vehicles = []
            for vehicle in all_vehicles:
                dist = calculate_distance(
                    passenger_data["latitude"], passenger_data["longitude"],
                    vehicle.get("latitude"), vehicle.get("longitude")
                )
                if dist <= passenger_data["zoom"]:
                    nearby_vehicles.append(vehicle)
            
            try:
                await websocket.send(json.dumps({"nearby_vehicles": nearby_vehicles}))
            except Exception as e:
                print(f"Error enviando a pasajero: {e}")

