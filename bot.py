import os
import json
import time
import io
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import qrcode
from neonize.client import NewClient
from neonize.events import MessageEv, ConnectedEv, QREv

# Variable global para guardar la imagen del QR más reciente
qr_image_bytes = None
is_connected = False

# --- SERVIDOR WEB: RENDER HEALTH CHECK + MOSTRAR QR LIMPIO ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global qr_image_bytes, is_connected
        
        # Ruta para ver la imagen directa del QR
        if self.path == "/qr.png":
            if qr_image_bytes:
                self.send_response(200)
                self.send_header('Content-type', 'image/png')
                self.end_headers()
                self.wfile.write(qr_image_bytes)
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"No hay QR activo")
            return

        # Página de inicio con visor web y auto-refresco
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        
        if is_connected:
            html = """
            <html>
            <body style="font-family:sans-serif; text-align:center; padding-top:50px; background:#111; color:#fff;">
                <h1 style="color:#25D366;">✅ Bot Conectado a WhatsApp</h1>
                <p>El bot de Click&Cut Store esta activo y respondiendo mensajes.</p>
            </body>
            </html>
            """
        elif qr_image_bytes:
            html = f"""
            <html>
            <head><meta http-equiv="refresh" content="5"></head>
            <body style="font-family:sans-serif; text-align:center; padding-top:30px; background:#222; color:#fff;">
                <h2>Escanear QR de Click&Cut Store</h2>
                <p>Abre WhatsApp > Dispositivos vinculados > Vincular un dispositivo</p>
                <div style="background:#fff; display:inline-block; padding:15px; border-radius:10px;">
                    <img src="/qr.png?t={int(time.time())}" style="width:300px; height:300px; display:block;" />
                </div>
                <p style="color:#aaa; font-size:12px;">Esta pagina se actualiza sola cada 5 segundos si cambia el codigo.</p>
            </body>
            </html>
            """
        else:
            html = """
            <html>
            <head><meta http-equiv="refresh" content="3"></head>
            <body style="font-family:sans-serif; text-align:center; padding-top:50px; background:#222; color:#fff;">
                <h2>Iniciando conexion...</h2>
                <p>Generando codigo QR, espera unos segundos...</p>
            </body>
            </html>
            """
        self.wfile.write(html.encode("utf-8"))

def iniciar_servidor_web():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=iniciar_servidor_web, daemon=True).start()
# -------------------------------------------------------------

# 1. Configuración de Administrador
ADMIN_NUMBERS = ["5218641062059"]

# 2. Rutas
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "sesion_clickandcut.db")
SALDOS_FILE = os.path.join(BASE_DIR, "saldos.json")
PEDIDOS_FILE = os.path.join(BASE_DIR, "pedidos.json")
CLIENTES_FILE = os.path.join(BASE_DIR, "clientes.json")

def cargar_datos(ruta):
    if not os.path.exists(ruta):
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)
        return {}
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def guardar_datos(ruta, datos):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)

def registrar_cliente(numero, nombre="Cliente"):
    clientes = cargar_datos(CLIENTES_FILE)
    saldos = cargar_datos(SALDOS_FILE)
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if numero not in clientes:
        clientes[numero] = {"nombre": nombre, "fecha_registro": ahora, "ultimo_mensaje": ahora}
    else:
        clientes[numero]["ultimo_mensaje"] = ahora
    guardar_datos(CLIENTES_FILE, clientes)

    if numero not in saldos:
        saldos[numero] = 0.0
        guardar_datos(SALDOS_FILE, saldos)

# 3. Cliente WhatsApp
client = NewClient(DB_PATH)

@client.event(QREv)
def on_qr(_: NewClient, data: bytes):
    global qr_image_bytes
    # Genera la imagen PNG limpia en memoria
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_image_bytes = buf.getvalue()
    print("\n[INFO] Nuevo codigo QR generado y listo en la web.\n")

@client.event(ConnectedEv)
def on_connected(_: NewClient, __: ConnectedEv):
    global is_connected
    is_connected = True
    print("\n*********************************************")
    print(" ✅ Bot Click&Cut Store CONECTADO A WHATSAPP ")
    print("*********************************************\n")

@client.event(MessageEv)
def on_message(cl: NewClient, message: MessageEv):
    try:
        if not hasattr(message, "Info") or message.Info is None:
            return

        if getattr(message.Info, "IsFromMe", False):
            return

        sender = getattr(message.Info, "Sender", None)
        if not sender:
            return
        remitente = getattr(sender, "User", "")
        if not remitente:
            return

        push_name = getattr(message.Info, "PushName", "") or "Cliente"

        msg_obj = getattr(message, "Message", None)
        if not msg_obj:
            return

        texto = ""
        if hasattr(msg_obj, "conversation") and msg_obj.conversation:
            texto = msg_obj.conversation
        elif hasattr(msg_obj, "extendedTextMessage") and msg_obj.extendedTextMessage:
            texto = getattr(msg_obj.extendedTextMessage, "text", "")

        texto = texto.strip()
        if not texto:
            return

        registrar_cliente(remitente, push_name)
        es_admin = remitente in ADMIN_NUMBERS

        if es_admin:
            if texto.startswith(".recargar"):
                partes = texto.split()
                if len(partes) == 3 and partes[2].replace('.', '', 1).isdigit():
                    destino = partes[1].replace("+", "").strip()
                    monto = float(partes[2])
                    saldos = cargar_datos(SALDOS_FILE)
                    saldos[destino] = saldos.get(destino, 0.0) + monto
                    guardar_datos(SALDOS_FILE, saldos)
                    cl.reply_message(message, f"✅ Recarga exitosa a {destino}: ${monto:.2f}\nSaldo total:${saldos[destino]:.2f}")
                else:
                    cl.reply_message(message, "⚠️ Uso: `.recargar <numero> <monto>`")
                return

            elif texto == ".verpedidos":
                pedidos = cargar_datos(PEDIDOS_FILE)
                if not pedidos:
                    cl.reply_message(message, "📦 No hay pedidos pendientes.")
                else:
                    resumen = "📦 *ÚLTIMOS PEDIDOS:*\n"
                    for item in list(pedidos.values())[-5:]:
                        resumen += f"- {item.get('fecha')}: {item.get('cliente')} -> {item.get('producto')}\n"
                    cl.reply_message(message, resumen)
                return

        if texto == ".menu":
            menu_msg = (
                "🛍️ *Click&Cut Store - Menú*\n\n"
                "🔹 *.catalogo* - Ver cuentas disponibles\n"
                "🔹 *.saldo* - Consultar tu saldo\n"
                "🔹 *.comprar <producto>* - Realizar pedido\n"
                "🔹 *.soporte* - Reportar una falla en tu cuenta"
            )
            cl.reply_message(message, menu_msg)

        elif texto == ".saldo":
            saldos = cargar_datos(SALDOS_FILE)
            cl.reply_message(message, f"💳 Tu saldo actual es de: *${saldos.get(remitente, 0.0):.2f}*")

        elif texto.startswith(".comprar"):
            partes = texto.split(maxsplit=1)
            if len(partes) < 2:
                cl.reply_message(message, "⚠️ Indica el servicio. Ejemplo: `.comprar Netflix 1 Mes`")
                return
            producto = partes[1]
            pedidos = cargar_datos(PEDIDOS_FILE)
            id_ped = str(len(pedidos) + 1)
            pedidos[id_ped] = {
                "cliente": remitente,
                "producto": producto,
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "estado": "Pendiente"
            }
            guardar_datos(PEDIDOS_FILE, pedidos)
            cl.reply_message(message, f"🛒 *Pedido #{id_ped} recibido!*\nProducto: {producto}\nEstado: *Pendiente*")

        elif texto == ".soporte":
            cl.reply_message(
                message, 
                "🛠️ *Portal de Garantías y Soporte Click&Cut*\n\n"
                "Si tu cuenta presenta fallas, repórtalo en nuestra web:\n"
                "👉 https://soporte-clickandcut.lovable.app"
            )

    except Exception as e:
        print(f"Error procesando mensaje: {e}")

if __name__ == "__main__":
    print("Iniciando servicio de WhatsApp...")
    client.connect()