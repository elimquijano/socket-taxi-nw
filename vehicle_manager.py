import asyncio
import json
import os
import websockets
from typing import Dict, Callable

# Almacén de datos en memoria para los vehículos.
# Mapea name (license_plate) -> datos del vehículo
vehicle_data_store: Dict[str, Dict] = {}

async def run_external_client(connection_manager):
    """
    Se conecta al servicio WSS externo, recibe actualizaciones de vehículos
    y dispara las funciones de broadcast del ConnectionManager.
    """
    uri = os.getenv("EXTERNAL_WSS_URI")
    print(f"Conectando al servicio de geolocalización externo en {uri}...")
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print("Conectado al servicio de geolocalización externo.")
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        print(f"Mensaje recibido del servicio externo: {data}")
                        if "devices" in data:
                            # Actualiza el almacén de datos global
                            updated_vehicles = {
                                device["name"]: device for device in data["devices"] if device.get("name")
                            }
                            vehicle_data_store.clear()
                            vehicle_data_store.update(updated_vehicles)
                            
                            # Notifica al ConnectionManager para que distribuya los datos
                            await connection_manager.broadcast_to_drivers(vehicle_data_store)
                            await connection_manager.broadcast_to_passengers(vehicle_data_store)

                    except json.JSONDecodeError:
                        print("Error decodificando JSON del servicio externo.")
                    except Exception as e:
                        print(f"Error procesando mensaje externo: {e}")
        except Exception as e:
            print(f"Error en la conexión con el servicio externo: {e}. Reconectando en 5 segundos...")
            await asyncio.sleep(5)
