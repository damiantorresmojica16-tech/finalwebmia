import requests

API_URL = "https://YOUR-APP.onrender.com"  # Cambia esto por tu URL de Render
BOT_SECRET = "8712217253:AAGmnCdbIYFLOKtaHQLjLoGlc7bWsDgo2xI"  # Cambia esto por tu BOT_SECRET configurado

def register_key(key: str, duration_days: int):
    """
    Registra una nueva llave en el sistema.
    """
    try:
        r = requests.post(f"{API_URL}/api/keys/register",
            json={"key": key, "duration_days": duration_days},
            headers={"X-Bot-Secret": BOT_SECRET})
        return r.status_code == 201, r.json()
    except Exception as e:
        return False, {"error": str(e)}

def revoke_key(key: str):
    """
    Revoca una llave existente.
    """
    try:
        r = requests.post(f"{API_URL}/api/keys/revoke",
            json={"key": key},
            headers={"X-Bot-Secret": BOT_SECRET})
        return r.status_code == 200, r.json()
    except Exception as e:
        return False, {"error": str(e)}

def check_key(key: str):
    """
    Obtiene información de una llave.
    """
    try:
        r = requests.get(f"{API_URL}/api/keys/info",
            params={"key": key},
            headers={"X-Bot-Secret": BOT_SECRET})
        return r.json()
    except Exception as e:
        return {"error": str(e)}

# Ejemplo de uso:
# success, data = register_key("WIDMAN-WEB-DAY-ABC12345", 1)
# print(success, data)
