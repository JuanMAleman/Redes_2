import socket
import struct
import json
import os
import threading
from ftplib import FTP


# ============================================================
# CONFIGURACIÓN
# ============================================================

# Si cliente y servidor están en la misma PC:
SERVER_HOSTNAME = "localhost"

# Si posteriormente el servidor estará en otra PC,
# aquí pondrás su nombre DNS, por ejemplo:
#
# SERVER_HOSTNAME = "servidor.local"


# Puerto de nuestra aplicación
SERVER_PORT = 5000


# ============================================================
# FTP
# ============================================================

FTP_PORT = 2121

FTP_USER = "ftpuser"
FTP_PASSWORD = "ftp123"


# ============================================================
# MULTICAST
# ============================================================

MULTICAST_GROUP = "239.10.10.10"
MULTICAST_PORT = 5001


# ============================================================
# COMUNICACIÓN TCP
# ============================================================

def send_json(sock, data):

    message = json.dumps(
        data,
        ensure_ascii=False
    ).encode("utf-8")

    header = struct.pack(
        "!I",
        len(message)
    )

    sock.sendall(
        header + message
    )


def receive_exact(sock, size):

    data = b""

    while len(data) < size:

        chunk = sock.recv(
            size - len(data)
        )

        if not chunk:

            raise ConnectionError(
                "El servidor cerró la conexión."
            )

        data += chunk

    return data


def receive_json(sock):

    header = receive_exact(
        sock,
        4
    )

    message_length = struct.unpack(
        "!I",
        header
    )[0]

    message = receive_exact(
        sock,
        message_length
    )

    return json.loads(
        message.decode("utf-8")
    )


def send_request(sock, request):

    send_json(
        sock,
        request
    )

    return receive_json(
        sock
    )


# ============================================================
# DNS
# ============================================================

def resolve_server():

    try:

        ip = socket.gethostbyname(
            SERVER_HOSTNAME
        )

        print()
        print(
            "[DNS] Resolución de nombre"
        )

        print(
            f"      {SERVER_HOSTNAME}"
        )

        print(
            f"          ↓"
        )

        print(
            f"      {ip}"
        )

        return ip

    except socket.gaierror:

        print(
            "[ERROR DNS] No se pudo resolver:"
        )

        print(
            SERVER_HOSTNAME
        )

        return None


# ============================================================
# MULTICAST / IGMP
# ============================================================

def multicast_listener():

    try:

        multicast_socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
            socket.IPPROTO_UDP
        )

        multicast_socket.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1
        )

        multicast_socket.bind(
            (
                "",
                MULTICAST_PORT
            )
        )

        # Solicita al sistema operativo unirse
        # al grupo multicast.
        membership = (
            socket.inet_aton(
                MULTICAST_GROUP
            )
            +
            socket.inet_aton(
                "0.0.0.0"
            )
        )

        multicast_socket.setsockopt(
            socket.IPPROTO_IP,
            socket.IP_ADD_MEMBERSHIP,
            membership
        )

        print()
        print(
            "[IGMP] Cliente unido al grupo multicast:"
        )

        print(
            f"       {MULTICAST_GROUP}:{MULTICAST_PORT}"
        )

        while True:

            data, address = multicast_socket.recvfrom(
                4096
            )

            print()
            print(
                "╔══════════════════════════════════════════╗"
            )

            print(
                "║       NOTIFICACIÓN MULTICAST            ║"
            )

            print(
                "╚══════════════════════════════════════════╝"
            )

            print(
                data.decode("utf-8")
            )

            print()
            print(
                "Seleccione una opción: ",
                end="",
                flush=True
            )

    except Exception as error:

        print(
            f"[ERROR MULTICAST] {error}"
        )


# ============================================================
# REGISTRO
# ============================================================

def register(sock):

    print()
    print("=" * 45)
    print("REGISTRO DE USUARIO")
    print("=" * 45)

    username = input(
        "Usuario: "
    ).strip()

    password = input(
        "Contraseña: "
    )

    if not username or not password:

        print(
            "Los campos no pueden estar vacíos."
        )

        return

    response = send_request(
        sock,
        {
            "command": "REGISTER",
            "username": username,
            "password": password
        }
    )

    print()
    print(
        response["message"]
    )


# ============================================================
# LOGIN
# ============================================================

def login(sock):

    print()
    print("=" * 45)
    print("INICIO DE SESIÓN")
    print("=" * 45)

    username = input(
        "Usuario: "
    ).strip()

    password = input(
        "Contraseña: "
    )

    response = send_request(
        sock,
        {
            "command": "LOGIN",
            "username": username,
            "password": password
        }
    )

    print()
    print(
        response["message"]
    )

    return response["success"]


# ============================================================
# LISTAR ARCHIVOS
# ============================================================

def list_files(sock):

    response = send_request(
        sock,
        {
            "command": "LIST"
        }
    )

    if not response["success"]:

        print(
            response["message"]
        )

        return

    files = response["files"]

    print()
    print("=" * 100)
    print("ARCHIVOS DISPONIBLES")
    print("=" * 100)

    if not files:

        print(
            "No hay archivos registrados."
        )

        return

    for file in files:

        print(
            f"ID: {file['id']}"
        )

        print(
            f"Nombre: {file['nombre']}"
        )

        print(
            f"Tipo: {file['tipo']}"
        )

        print(
            f"Tamaño: {file['tamano']} bytes"
        )

        print(
            f"Usuario: {file['usuario']}"
        )

        print(
            f"Fecha: {file['fecha']}"
        )

        print(
            "-" * 100
        )


# ============================================================
# SUBIR ARCHIVO MEDIANTE FTP
# ============================================================

def upload_file(sock):

    print()
    print("=" * 45)
    print("SUBIR ARCHIVO")
    print("=" * 45)

    path = input(
        "Ruta completa del archivo: "
    ).strip().strip('"')

    if not os.path.isfile(path):

        print(
            "El archivo no existe."
        )

        return

    filename = os.path.basename(
        path
    )

    extension = os.path.splitext(
        filename
    )[1].lower()

    if extension not in [
        ".pdf",
        ".png",
        ".exe"
    ]:

        print(
            "ERROR: solamente se permiten:"
        )

        print(
            "PDF, PNG y EXE"
        )

        return

    size = os.path.getsize(
        path
    )

    # Elegimos la carpeta FTP correspondiente.
    if extension == ".pdf":
        ftp_directory = "pdf"

    elif extension == ".png":
        ftp_directory = "png"

    else:
        ftp_directory = "exe"

    try:

        print()
        print(
            "[FTP] Conectando al servidor..."
        )

        server_ip = resolve_server()

        if server_ip is None:
            return

        ftp = FTP()

        ftp.connect(
            server_ip,
            FTP_PORT,
            timeout=10
        )

        ftp.login(
            FTP_USER,
            FTP_PASSWORD
        )

        print(
            "[FTP] Conexión correcta."
        )

        # Entramos a la carpeta correspondiente.
        ftp.cwd(
            ftp_directory
        )

        print(
            f"[FTP] Carpeta: {ftp_directory}"
        )

        with open(
            path,
            "rb"
        ) as file:

            ftp.storbinary(
                f"STOR {filename}",
                file
            )

        ftp.quit()

        print()
        print(
            "[FTP] Archivo transferido correctamente."
        )

        # Registramos la operación en MariaDB.
        response = send_request(
            sock,
            {
                "command": "REGISTER_UPLOAD",
                "filename": filename,
                "size": size
            }
        )

        print(
            response["message"]
        )

    except Exception as error:

        print()
        print(
            f"[ERROR FTP] {error}"
        )


# ============================================================
# DESCARGAR ARCHIVO
# ============================================================

def download_file(sock):

    print()
    print("=" * 45)
    print("DESCARGAR ARCHIVO")
    print("=" * 45)

    filename = input(
        "Nombre del archivo: "
    ).strip()

    if not filename:

        print(
            "Debe escribir un nombre."
        )

        return

    extension = os.path.splitext(
        filename
    )[1].lower()

    if extension == ".pdf":
        ftp_directory = "pdf"

    elif extension == ".png":
        ftp_directory = "png"

    elif extension == ".exe":
        ftp_directory = "exe"

    else:

        print(
            "Tipo de archivo no permitido."
        )

        return

    destination = input(
        "Carpeta donde guardarlo "
        "(Enter = carpeta actual): "
    ).strip().strip('"')

    if not destination:

        destination = os.getcwd()

    os.makedirs(
        destination,
        exist_ok=True
    )

    output_path = os.path.join(
        destination,
        filename
    )

    try:

        server_ip = resolve_server()

        if server_ip is None:
            return

        print(
            "[FTP] Conectando..."
        )

        ftp = FTP()

        ftp.connect(
            server_ip,
            FTP_PORT,
            timeout=10
        )

        ftp.login(
            FTP_USER,
            FTP_PASSWORD
        )

        ftp.cwd(
            ftp_directory
        )

        with open(
            output_path,
            "wb"
        ) as file:

            ftp.retrbinary(
                f"RETR {filename}",
                file.write
            )

        ftp.quit()

        print()
        print(
            "[FTP] Descarga completada."
        )

        print(
            f"Archivo: {output_path}"
        )

        # Registrar descarga
        response = send_request(
            sock,
            {
                "command": "REGISTER_DOWNLOAD",
                "filename": filename
            }
        )

        print(
            response["message"]
        )

    except Exception as error:

        print()
        print(
            f"[ERROR FTP] {error}"
        )


# ============================================================
# ELIMINAR ARCHIVO
# ============================================================

def delete_file(sock):

    print()
    print("=" * 45)
    print("ELIMINAR ARCHIVO")
    print("=" * 45)

    filename = input(
        "Nombre del archivo: "
    ).strip()

    if not filename:

        return

    confirmation = input(
        f"¿Eliminar '{filename}'? (s/n): "
    ).lower()

    if confirmation != "s":

        print(
            "Operación cancelada."
        )

        return

    response = send_request(
        sock,
        {
            "command": "DELETE",
            "filename": filename
        }
    )

    print(
        response["message"]
    )


# ============================================================
# HISTORIAL
# ============================================================

def show_history(sock):

    response = send_request(
        sock,
        {
            "command": "HISTORY"
        }
    )

    if not response["success"]:

        print(
            response["message"]
        )

        return

    history = response["history"]

    print()
    print("=" * 90)
    print("HISTORIAL DE OPERACIONES")
    print("=" * 90)

    if not history:

        print(
            "No hay operaciones registradas."
        )

        return

    for item in history:

        print(
            f"Usuario: {item['usuario']}"
        )

        print(
            f"Archivo: {item['archivo']}"
        )

        print(
            f"Operación: {item['operacion']}"
        )

        print(
            f"Fecha: {item['fecha']}"
        )

        print(
            "-" * 90
        )


# ============================================================
# MENÚ PRINCIPAL DESPUÉS DEL LOGIN
# ============================================================

def main_menu(sock):

    while True:

        print()
        print("=" * 50)
        print("        SISTEMA DE ARCHIVOS")
        print("=" * 50)

        print(
            """
1. Listar archivos
2. Subir archivo
3. Descargar archivo
4. Eliminar archivo
5. Ver historial
6. Cerrar sesión
"""
        )

        option = input(
            "Seleccione una opción: "
        ).strip()

        if option == "1":

            list_files(sock)

        elif option == "2":

            upload_file(sock)

        elif option == "3":

            download_file(sock)

        elif option == "4":

            delete_file(sock)

        elif option == "5":

            show_history(sock)

        elif option == "6":

            print(
                "Cerrando sesión..."
            )

            return

        else:

            print(
                "Opción inválida."
            )


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():

    print()
    print("=" * 60)
    print("        CLIENTE - SISTEMA DE ARCHIVOS")
    print("=" * 60)

    # --------------------------------------------------------
    # DNS
    # --------------------------------------------------------

    server_ip = resolve_server()

    if server_ip is None:

        return

    # --------------------------------------------------------
    # MULTICAST
    # --------------------------------------------------------

    multicast_thread = threading.Thread(
        target=multicast_listener,
        daemon=True
    )

    multicast_thread.start()

    # --------------------------------------------------------
    # TCP
    # --------------------------------------------------------

    try:

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        )

        sock.connect(
            (
                server_ip,
                SERVER_PORT
            )
        )

        print()
        print(
            f"[TCP] Conectado a {server_ip}:{SERVER_PORT}"
        )

    except Exception as error:

        print()
        print(
            "[ERROR] No se pudo conectar con el servidor."
        )

        print(
            error
        )

        return

    # --------------------------------------------------------
    # MENÚ DE ACCESO
    # --------------------------------------------------------

    while True:

        print()
        print("=" * 45)
        print("ACCESO")
        print("=" * 45)

        print(
            """
1. Registrarse
2. Iniciar sesión
3. Salir
"""
        )

        option = input(
            "Seleccione: "
        ).strip()

        if option == "1":

            register(sock)

        elif option == "2":

            if login(sock):

                main_menu(sock)

        elif option == "3":

            try:

                send_request(
                    sock,
                    {
                        "command": "QUIT"
                    }
                )

            except Exception:
                pass

            break

        else:

            print(
                "Opción inválida."
            )

    sock.close()

    print(
        "Programa terminado."
    )


if __name__ == "__main__":

    main()