import httpx
import os

class ApiClient:
    """
    Cliente para interactuar con la API de backend de forma asíncrona.
    """
    def __init__(self):
        self.base_url = os.getenv("API_BASE_URL")
        self.client = httpx.AsyncClient(verify=False)  # 'verify=False' para desarrollo con localhost

    async def get_user_profile(self, token: str):
        """
        Valida un token de conductor y obtiene los datos del perfil.
        """
        try:
            headers = {'Authorization': f'Bearer {token}'}
            response = await self.client.get(f"{self.base_url}/api/auth/me", headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"Error al validar el perfil de usuario: {e}")
            return None
        except Exception as e:
            print(f"Error inesperado en get_user_profile: {e}")
            return None

    async def get_vehicles(self, token: str):
        """
        Obtiene los vehículos asociados a un conductor.
        """
        try:
            headers = {'Authorization': f'Bearer {token}'}
            response = await self.client.get(f"{self.base_url}/api/vehicles", headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"Error al obtener los vehículos: {e}")
            return None
        except Exception as e:
            print(f"Error inesperado en get_vehicles: {e}")
            return None

    async def close(self):
        """Cierra el cliente httpx."""
        await self.client.aclose()
