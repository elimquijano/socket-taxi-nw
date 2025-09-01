"""
Cliente para comunicación con la API REST del backend.
"""

import asyncio
from typing import Dict, List, Optional, Any
import httpx
from logger_config import get_logger

logger = get_logger(__name__)


class ApiClient:
    """Cliente asíncrono para interactuar con la API REST del backend."""

    def __init__(self, base_url: str, timeout: int = 30):
        """
        Inicializa el cliente API.

        Args:
            base_url: URL base de la API
            timeout: Timeout para las peticiones en segundos
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = None
        logger.info(f"ApiClient inicializado con base_url: {self.base_url}")

    async def __aenter__(self):
        """Context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.close()

    async def start(self):
        """Inicia el cliente HTTP."""
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
            )
            logger.debug("Cliente HTTP iniciado")

    async def close(self):
        """Cierra el cliente HTTP."""
        if self.client:
            await self.client.aclose()
            self.client = None
            logger.debug("Cliente HTTP cerrado")

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Realiza una petición HTTP genérica.

        Args:
            method: Método HTTP (GET, POST, etc.)
            endpoint: Endpoint de la API (sin base_url)
            headers: Headers adicionales
            params: Parámetros de query
            json_data: Datos JSON para el body

        Returns:
            Dict con la respuesta o None si hay error
        """
        if not self.client:
            await self.start()

        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        # Preparar headers
        final_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if headers:
            final_headers.update(headers)

        try:
            logger.debug(f"Realizando petición {method} a {url}")

            response = await self.client.request(
                method=method,
                url=url,
                headers=final_headers,
                params=params,
                json=json_data,
            )

            logger.debug(f"Respuesta recibida: {response.status_code}")

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                logger.warning(f"Token inválido o expirado para {url}")
                return None
            elif response.status_code == 403:
                logger.warning(f"Acceso denegado para {url}")
                return None
            else:
                logger.error(
                    f"Error HTTP {response.status_code} para {url}: {response.text}"
                )
                return None

        except httpx.TimeoutException:
            logger.error(f"Timeout en petición a {url}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Error de conexión a {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error inesperado en petición a {url}: {e}")
            return None

    async def get_user_profile(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene el perfil del usuario usando su token.

        Args:
            token: Token Bearer del usuario

        Returns:
            Dict con los datos del usuario o None si hay error
        """
        headers = {"Authorization": f"Bearer {token}"}

        try:
            result = await self._make_request("GET", "api/auth/me", headers=headers)

            if result:
                logger.debug(
                    f"Perfil obtenido para usuario: {result.get('id', 'unknown')}"
                )
            else:
                logger.warning("No se pudo obtener el perfil del usuario")

            return result.get("user", None)

        except Exception as e:
            logger.error(f"Error al obtener perfil de usuario: {e}")
            return None

    async def get_vehicles(self, token: str) -> Optional[List[Dict[str, Any]]]:
        """
        Obtiene la lista de vehículos asociados al conductor.

        Args:
            token: Token Bearer del conductor

        Returns:
            Lista de vehículos o None si hay error
        """
        headers = {"Authorization": f"Bearer {token}"}

        try:
            result = await self._make_request("GET", "api/vehicles", headers=headers)

            if result:
                # Asumimos que la respuesta puede ser un dict con 'data' o directamente una lista
                vehicles = (
                    result if isinstance(result, list) else result.get("data", [])
                )
                logger.debug(f"Obtenidos {len(vehicles)} vehículos")
                return vehicles
            else:
                logger.warning("No se pudo obtener la lista de vehículos")
                return []

        except Exception as e:
            logger.error(f"Error al obtener vehículos: {e}")
            return []

    async def validate_passenger_api_key(self, api_key: str) -> bool:
        """
        Valida la clave de API de un pasajero.

        Args:
            api_key: Clave de API del pasajero

        Returns:
            bool: True si la clave es válida
        """
        headers = {"X-API-Key": api_key}

        try:
            result = await self._make_request(
                "GET", "api/passengers/validate", headers=headers
            )

            if result:
                logger.debug("Clave de API de pasajero válida")
                return True
            else:
                logger.warning("Clave de API de pasajero inválida")
                return False

        except Exception as e:
            logger.error(f"Error al validar clave de API de pasajero: {e}")
            return False

    async def get_vehicle_details(
        self, vehicle_id: str, token: str
    ) -> Optional[Dict[str, Any]]:
        """
        Obtiene detalles específicos de un vehículo.

        Args:
            vehicle_id: ID del vehículo
            token: Token Bearer del conductor

        Returns:
            Dict con los detalles del vehículo o None si hay error
        """
        headers = {"Authorization": f"Bearer {token}"}

        try:
            result = await self._make_request(
                "GET", f"api/vehicles/{vehicle_id}", headers=headers
            )

            if result:
                logger.debug(f"Detalles obtenidos para vehículo: {vehicle_id}")
            else:
                logger.warning(
                    f"No se pudieron obtener detalles del vehículo: {vehicle_id}"
                )

            return result

        except Exception as e:
            logger.error(f"Error al obtener detalles del vehículo {vehicle_id}: {e}")
            return None

    async def health_check(self) -> bool:
        """
        Verifica si la API está disponible.

        Returns:
            bool: True si la API responde correctamente
        """
        try:
            result = await self._make_request("GET", "api/health")
            return result is not None
        except Exception:
            return False
