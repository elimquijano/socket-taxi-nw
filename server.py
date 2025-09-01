import asyncio
import os
import websockets
from dotenv import load_dotenv

from api_client import ApiClient
from connection_manager import ConnectionManager
from vehicle_manager import run_external_client

async def main():
    """
    Punto de entrada principal que inicia todos los componentes del servidor.
    """
    load_dotenv()

    host = os.getenv("HOST")
    port = int(os.getenv("PORT"))

    api_client = ApiClient()
    connection_manager = ConnectionManager(api_client)

    # Iniciar el servidor WebSocket principal para clientes
    server = websockets.serve(connection_manager.handle_connection, host, port)
    
    # Iniciar el cliente para el servicio de geolocalización externo
    external_client_task = asyncio.create_task(run_external_client(connection_manager))

    print(f"Servidor WebSocket iniciado en ws://{host}:{port}")

    await asyncio.gather(
        server,
        external_client_task
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Servidor detenido manualmente.")
