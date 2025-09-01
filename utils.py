"""
Utilidades y funciones auxiliares para el sistema de taxi en tiempo real.
"""

import math
from typing import List, Dict, Any, Tuple
from logger_config import get_logger

logger = get_logger(__name__)


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcula la distancia en metros entre dos puntos GPS usando la fórmula de Haversine.

    Args:
        lat1, lon1: Latitud y longitud del primer punto
        lat2, lon2: Latitud y longitud del segundo punto

    Returns:
        float: Distancia en metros entre los dos puntos
    """
    # Radio de la Tierra en metros
    R = 6371000

    # Convertir grados a radianes
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    # Fórmula de Haversine
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def filter_vehicles_by_proximity(
    vehicles: List[Dict[str, Any]],
    passenger_lat: float,
    passenger_lon: float,
    zoom_level: int,
) -> List[Dict[str, Any]]:
    """
    Filtra vehículos basándose en la proximidad al pasajero según el nivel de zoom.

    Args:
        vehicles: Lista de vehículos con coordenadas
        passenger_lat: Latitud del pasajero
        passenger_lon: Longitud del pasajero
        zoom_level: Nivel de zoom (mayor número = menor radio)

    Returns:
        List[Dict]: Lista de vehículos filtrados dentro del radio
    """
    # Mapeo de zoom a radio en metros
    zoom_to_radius = {
        1: 50000,  # 50 km
        2: 25000,  # 25 km
        3: 10000,  # 10 km
        4: 5000,  # 5 km
        5: 2500,  # 2.5 km
        6: 1000,  # 1 km
        7: 500,  # 500 m
        8: 250,  # 250 m
        9: 100,  # 100 m
        10: 50,  # 50 m
    }

    max_distance = zoom_to_radius.get(zoom_level, 1000)  # Default 1km
    filtered_vehicles = []

    for vehicle in vehicles:
        try:
            vehicle_lat = float(vehicle.get("lat", 0))
            vehicle_lon = float(vehicle.get("lng", 0))

            distance = calculate_distance(
                passenger_lat, passenger_lon, vehicle_lat, vehicle_lon
            )

            if distance <= max_distance:
                # Añadir distancia calculada al objeto vehículo
                vehicle_copy = vehicle.copy()
                vehicle_copy["distance"] = round(distance, 2)
                filtered_vehicles.append(vehicle_copy)

        except (ValueError, TypeError) as e:
            logger.warning(
                f"Error al procesar vehículo {vehicle.get('name', 'unknown')}: {e}"
            )
            continue

    # Ordenar por distancia (más cerca primero)
    filtered_vehicles.sort(key=lambda x: x.get("distance", float("inf")))

    return filtered_vehicles


def validate_coordinates(lat: float, lon: float) -> bool:
    """
    Valida si las coordenadas están dentro de rangos válidos.

    Args:
        lat: Latitud
        lon: Longitud

    Returns:
        bool: True si las coordenadas son válidas
    """
    return -90 <= lat <= 90 and -180 <= lon <= 180


def format_vehicle_data(vehicle: Dict[str, Any]) -> Dict[str, Any]:
    """
    Formatea los datos del vehículo para envío a clientes.

    Args:
        vehicle: Datos raw del vehículo

    Returns:
        Dict: Datos formateados del vehículo
    """
    try:
        return {
            "id": vehicle.get("id"),
            "name": vehicle.get("name"),
            "license_plate": vehicle.get("name"),  # Asumiendo que name es la matrícula
            "lat": float(vehicle.get("lat", 0)),
            "lng": float(vehicle.get("lng", 0)),
            "speed": float(vehicle.get("speed", 0)),
            "course": float(vehicle.get("course", 0)),
            "status": vehicle.get("status", "unknown"),
            "last_update": vehicle.get("time"),
            "distance": vehicle.get("distance"),  # Si está disponible
            "attributes": vehicle.get("attributes", {}),
        }
    except (ValueError, TypeError) as e:
        logger.warning(f"Error al formatear datos del vehículo: {e}")
        return vehicle


def create_error_message(error: str, code: str = "ERROR") -> Dict[str, Any]:
    """
    Crea un mensaje de error estandarizado.

    Args:
        error: Descripción del error
        code: Código del error

    Returns:
        Dict: Mensaje de error formateado
    """
    return {
        "type": "error",
        "code": code,
        "message": error,
        "timestamp": get_current_timestamp(),
    }


def create_success_message(data: Any, message_type: str = "data") -> Dict[str, Any]:
    """
    Crea un mensaje de éxito estandarizado.

    Args:
        data: Datos a enviar
        message_type: Tipo de mensaje

    Returns:
        Dict: Mensaje formateado
    """
    return {"type": message_type, "data": data, "timestamp": get_current_timestamp()}


def get_current_timestamp() -> int:
    """
    Obtiene el timestamp actual en milisegundos.

    Returns:
        int: Timestamp en milisegundos
    """
    import time

    return int(time.time() * 1000)


def parse_zoom_level(zoom: Any) -> int:
    """
    Parsea y valida el nivel de zoom.

    Args:
        zoom: Nivel de zoom a parsear

    Returns:
        int: Nivel de zoom válido (1-10)
    """
    try:
        zoom_int = int(zoom)
        return max(1, min(10, zoom_int))  # Clamp entre 1 y 10
    except (ValueError, TypeError):
        return 5  # Default zoom level
