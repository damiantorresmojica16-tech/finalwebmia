# Venom Modz x Guebo xit - Backend

Este es el sistema de backend para la validación de llaves de acceso de Venom Modz. Está construido con Node.js, Express y SQLite, diseñado para ser desplegado fácilmente en Render.

## Estructura del Proyecto

- `server.js`: Servidor principal Express con todos los endpoints.
- `db.js`: Configuración y esquema de la base de datos SQLite.
- `views/`: Contiene las páginas HTML (Login e Index).
- `bot_integration.py`: Ejemplo de integración para tu bot de Telegram en Python.
- `render.yaml`: Configuración para despliegue automático en Render.

## Requisitos Previos

- Una cuenta en [Render](https://render.com/).
- Un repositorio en GitHub con estos archivos.

## Pasos para el Despliegue en Render

1. **Subir a GitHub**: Crea un nuevo repositorio privado y sube todos los archivos de esta carpeta.
2. **Crear Web Service en Render**:
   - Ve a tu Dashboard de Render.
   - Haz clic en **New +** -> **Web Service**.
   - Conecta tu repositorio de GitHub.
   - Render detectará automáticamente el archivo `render.yaml`.
3. **Configurar Variables de Entorno**:
   En la sección **Environment** de tu servicio en Render, asegúrate de configurar:
   - `BOT_SECRET`: Una clave secreta que solo tu bot y el servidor conozcan.
   - `COOKIE_SECRET`: Una cadena larga aleatoria para firmar las cookies de sesión.
   - `NODE_ENV`: Establecer a `production`.

> **Nota sobre Render Free Tier**: El nivel gratuito de Render no admite discos persistentes. Esto significa que si el servidor se reinicia o entra en reposo, la base de datos SQLite se borrará. Para una solución permanente, se recomienda usar el plan "Starter" con un "Disk" adjunto o migrar a una base de datos externa como PostgreSQL.

## Endpoints de la API para el Bot

Todos los endpoints del bot requieren el encabezado `X-Bot-Secret`.

- `POST /api/keys/register`: Registrar llave.
  - Body: `{ "key": "...", "duration_days": 1 }`
- `POST /api/keys/revoke`: Revocar llave.
  - Body: `{ "key": "..." }`
- `GET /api/keys/info?key=...`: Obtener estado de la llave.

## Integración con el Bot

Usa el archivo `bot_integration.py` como referencia para conectar tu bot de Telegram con este backend. Solo necesitas cambiar la `API_URL` y el `BOT_SECRET`.
