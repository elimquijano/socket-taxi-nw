"""
Utilidades y funciones auxiliares para el sistema de taxi en tiempo real.
"""

import math
from typing import List, Dict, Any
import re
from shapely.geometry import Point, Polygon
from datetime import datetime
from logger_config import get_logger

logger = get_logger(__name__)


def filter_connected_drivers_by_proximity(
    drivers: List[Dict[str, Any]],
    passenger_lat: float,
    passenger_lon: float,
    max_distance: int = 1000,
) -> List[Dict[str, Any]]:
    """
    Filtra vehículos basándose en la proximidad al pasajero según el nivel de zoom.

    Args:
        drivers: Lista de vehículos con coordenadas
        passenger_lat: Latitud del pasajero
        passenger_lon: Longitud del pasajero
        max_distance: Radio en metros

    Returns:
        List[Dict]: Lista de vehículos filtrados dentro del radio
    """

    # Crear geocerca circular temporal alrededor del pasajero
    try:
        temp_geofence_str = f"CIRCLE ({passenger_lat} {passenger_lon}, {max_distance})"
        geofence_obj = parse_geofence(temp_geofence_str)
    except ValueError as e:
        logger.error(
            f"Error creando geocerca temporal para el pasajero que está en {passenger_lat}, {passenger_lon}: {e}"
        )
        return []

    filtered_drivers = []

    for vehicle in drivers.values():
        # Omitir el vehículo actual y los que no tienen grupo o coordenadas
        if not vehicle.get("latitude") or not vehicle.get("longitude"):
            continue
        # Verificar si está dentro de la geocerca temporal
        if is_point_in_geofence(
            vehicle["latitude"], vehicle["longitude"], geofence_obj
        ):
            filtered_drivers.append(vehicle)
    return filtered_drivers


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
        "data": {
            "code": code,
            "message": error,
        },
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


def is_point_in_geofence(lat, lon, geofence):
    """Verifica si un punto está dentro de la geozona."""
    if geofence["type"] == "polygon":
        point = Point(lat, lon)
        return geofence["geometry"].contains(point)

    elif geofence["type"] == "circle":
        # Calcular distancia haversine entre el punto y el centro del círculo
        center_lat, center_lon = geofence["center"]
        radius = geofence["radius"]

        # Distancia haversine (considerando la Tierra como esfera)
        R = 6371000  # Radio de la Tierra en metros

        lat1, lon1 = math.radians(center_lat), math.radians(center_lon)
        lat2, lon2 = math.radians(lat), math.radians(lon)

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        distance = R * c

        return distance <= radius


def parse_geofence(geofence_str):
    """Parsea una cadena de geozona en formato POLYGON o CIRCLE y retorna un objeto para realizar verificaciones."""
    if geofence_str.startswith("POLYGON"):
        # Extraer coordenadas del polígono
        coordinates_str = re.search(r"POLYGON \(\((.*)\)\)", geofence_str).group(1)
        coordinate_pairs = coordinates_str.split(", ")

        # Convertir a lista de tuplas (lon, lat)
        polygon_coords = []
        for pair in coordinate_pairs:
            lat, lon = map(float, pair.split())
            polygon_coords.append((lat, lon))

        return {"type": "polygon", "geometry": Polygon(polygon_coords)}

    elif geofence_str.startswith("CIRCLE"):
        # Extraer centro y radio del círculo
        circle_data = re.search(r"CIRCLE \((.*), (.*)\)", geofence_str)

        # Separar latitud y longitud del centro que vienen juntos
        center_coords = circle_data.group(1).split()
        center_lat = float(center_coords[0])
        center_lon = float(center_coords[1])

        radius = float(circle_data.group(2))  # en metros

        return {"type": "circle", "center": (center_lat, center_lon), "radius": radius}

    else:
        raise ValueError("Formato de geozona no reconocido. Use POLYGON o CIRCLE.")


def get_current_datetime_in_str():
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")
