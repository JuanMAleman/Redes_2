import os
import socket
import struct
import json
import threading
import hashlib
import secrets
import mariadb

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

# IP donde escuchará el servidor Python.
# 0.0.0.0 significa que acepta conexiones desde cualquier
# interfaz de red de la computadora.
SERVER_HOST = "0.0.0.0"

# Puerto de nuestra aplicación cliente-servidor
SERVER_PORT = 5000


# ============================================================
# CONFIGURACIÓN DE MARIADB
# ============================================================

DB_HOST = "localhost"
DB_PORT = 3306

# CAMBIA ESTO por tus credenciales de MariaDB
DB_USER = "root"
DB_PASSWORD = "ROOT"

DB_NAME = "sistema_archivos"


# ============================================================
# CONFIGURACIÓN FTP
# ============================================================

FTP_HOST = "0.0.0.0"
FTP_PORT = 2121

FTP_USER = "ftpuser"
FTP_PASSWORD = "ftp123"

BASE_DIRECTORY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "archivos"
)

PDF_DIRECTORY = os.path.join(
    BASE_DIRECTORY,
    "pdf"
)

PNG_DIRECTORY = os.path.join(
    BASE_DIRECTORY,
    "png"
)

EXE_DIRECTORY = os.path.join(
    BASE_DIRECTORY,
    "exe"
)


# ============================================================
# CONFIGURACIÓN MULTICAST
# ============================================================

MULTICAST_GROUP = "239.10.10.10"
MULTICAST_PORT = 5001


# ============================================================
# TIPOS DE ARCHIVO PERMITIDOS
# ============================================================

ALLOWED_EXTENSIONS = {
    ".pdf": "PDF",
    ".png": "PNG",
    ".exe": "EXE"
}


# ============================================================
# CREAR DIRECTORIOS
# ============================================================

def create_directories():

    os.makedirs(PDF_DIRECTORY, exist_ok=True)
    os.makedirs(PNG_DIRECTORY, exist_ok=True)
    os.makedirs(EXE_DIRECTORY, exist_ok=True)

    print("[OK] Directorios de archivos preparados.")


# ============================================================
# CONEXIÓN A MARIADB
# ============================================================

def get_database_connection():

    return mariadb.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )


# ============================================================
# HASH DE CONTRASEÑAS
# ============================================================

def hash_password(password, salt=None):

    if salt is None:
        salt = secrets.token_hex(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    ).hex()

    return f"{salt}${password_hash}"


def verify_password(password, stored_password):

    try:

        salt, stored_hash = stored_password.split("$")

        password_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            100000
        ).hex()

        return secrets.compare_digest(
            password_hash,
            stored_hash
        )

    except Exception:

        return False


# ============================================================
# PROTOCOLO DE COMUNICACIÓN
# ============================================================

def send_json(sock, data):

    message = json.dumps(
        data,
        ensure_ascii=False
    ).encode("utf-8")

    # Enviamos primero el tamaño del mensaje.
    header = struct.pack(
        "!I",
        len(message)
    )

    sock.sendall(
        header + message
    )


def receive_json(sock):

    header = receive_exact(
        sock,
        4
    )

    if not header:
        return None

    message_length = struct.unpack(
        "!I",
        header
    )[0]

    message = receive_exact(
        sock,
        message_length
    )

    if not message:
        return None

    return json.loads(
        message.decode("utf-8")
    )


def receive_exact(sock, size):

    data = b""

    while len(data) < size:

        chunk = sock.recv(
            size - len(data)
        )

        if not chunk:
            return None

        data += chunk

    return data


# ============================================================
# MULTICAST
# ============================================================

def send_multicast(message):

    try:

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
            socket.IPPROTO_UDP
        )

        # TTL = 2 permite que el paquete pase algunos routers.
        sock.setsockopt(
            socket.IPPROTO_IP,
            socket.IP_MULTICAST_TTL,
            2
        )

        sock.sendto(
            message.encode("utf-8"),
            (
                MULTICAST_GROUP,
                MULTICAST_PORT
            )
        )

        sock.close()

        print(
            f"[MULTICAST] {message}"
        )

    except Exception as error:

        print(
            f"[ERROR MULTICAST] {error}"
        )


# ============================================================
# USUARIOS
# ============================================================

def register_user(username, password):

    connection = get_database_connection()
    cursor = connection.cursor()

    try:

        password_hash = hash_password(
            password
        )

        cursor.execute(
            """
            INSERT INTO usuarios
            (usuario, password_hash)
            VALUES (?, ?)
            """,
            (
                username,
                password_hash
            )
        )

        connection.commit()

        return True, "Usuario registrado correctamente."

    except mariadb.IntegrityError:

        return False, "El usuario ya existe."

    except Exception as error:

        return False, f"Error: {error}"

    finally:

        cursor.close()
        connection.close()


def authenticate_user(username, password):

    connection = get_database_connection()
    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            SELECT id, password_hash
            FROM usuarios
            WHERE usuario = ?
            """,
            (username,)
        )

        result = cursor.fetchone()

        if result is None:
            return None

        user_id = result[0]
        stored_password = result[1]

        if verify_password(
            password,
            stored_password
        ):

            return user_id

        return None

    finally:

        cursor.close()
        connection.close()


# ============================================================
# ARCHIVOS
# ============================================================

def get_file_type(filename):

    extension = os.path.splitext(
        filename
    )[1].lower()

    return ALLOWED_EXTENSIONS.get(
        extension
    )


def get_file_directory(filename):

    extension = os.path.splitext(
        filename
    )[1].lower()

    if extension == ".pdf":
        return PDF_DIRECTORY

    if extension == ".png":
        return PNG_DIRECTORY

    if extension == ".exe":
        return EXE_DIRECTORY

    return None


def register_file(
    filename,
    size,
    user_id
):

    file_type = get_file_type(
        filename
    )

    if file_type is None:

        return False, "Tipo de archivo no permitido."

    directory = get_file_directory(
        filename
    )

    if directory is None:

        return False, "Directorio no encontrado."

    file_path = os.path.join(
        directory,
        filename
    )

    connection = get_database_connection()
    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            SELECT id
            FROM archivos
            WHERE nombre = ?
            """,
            (filename,)
        )

        existing = cursor.fetchone()

        if existing:

            return False, "El archivo ya existe."

        cursor.execute(
            """
            INSERT INTO archivos
            (
                nombre,
                tipo,
                tamano,
                ruta,
                usuario_id
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                filename,
                file_type,
                size,
                file_path,
                user_id
            )
        )

        file_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO transferencias
            (
                usuario_id,
                archivo_id,
                operacion
            )
            VALUES (?, ?, 'SUBIDA')
            """,
            (
                user_id,
                file_id
            )
        )

        connection.commit()

        # Avisamos a todos los clientes
        send_multicast(
            f"Nuevo archivo disponible: {filename}"
        )

        return True, "Archivo registrado correctamente."

    except Exception as error:

        connection.rollback()

        return False, f"Error: {error}"

    finally:

        cursor.close()
        connection.close()


def get_files():
    connection = None
    cursor = None
    try:
        connection = get_database_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                a.id,
                a.nombre,
                a.tipo,
                a.tamano,
                a.ruta,
                u.usuario,
                a.fecha_subida
            FROM archivos a
            INNER JOIN usuarios u
                ON a.usuario_id = u.id
            ORDER BY a.fecha_subida DESC
            """
        )
        rows = cursor.fetchall()
        files = []

        for row in rows:
            files.append(
                {
                    "id": row[0],
                    "nombre": row[1],
                    "tipo": row[2],
                    "tamano": row[3],
                    "ruta": row[4],
                    "usuario": row[5],
                    "fecha": str(row[6]) if row[6] is not None else ""
                }
            )
        return files
    except Exception as error:
        print(f"[ERROR GET_FILES] {error}")
        return []
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def register_transfer(
    username,
    filename,
    operation
):

    connection = get_database_connection()
    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            SELECT id
            FROM usuarios
            WHERE usuario = ?
            """,
            (username,)
        )

        user = cursor.fetchone()

        if user is None:
            return

        user_id = user[0]

        cursor.execute(
            """
            SELECT id
            FROM archivos
            WHERE nombre = ?
            """,
            (filename,)
        )

        file = cursor.fetchone()

        file_id = file[0] if file else None

        cursor.execute(
            """
            INSERT INTO transferencias
            (
                usuario_id,
                archivo_id,
                operacion
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                file_id,
                operation
            )
        )

        connection.commit()

    finally:

        cursor.close()
        connection.close()


def delete_file(
    filename,
    user_id
):

    directory = get_file_directory(
        filename
    )

    if directory is None:

        return False, "Tipo de archivo inválido."

    path = os.path.join(
        directory,
        filename
    )

    connection = get_database_connection()
    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            SELECT id
            FROM archivos
            WHERE nombre = ?
            """,
            (filename,)
        )

        result = cursor.fetchone()

        if result is None:

            return False, "Archivo no encontrado."

        file_id = result[0]

        # Eliminar físicamente el archivo
        if os.path.exists(path):

            os.remove(path)

        cursor.execute(
            """
            INSERT INTO transferencias
            (
                usuario_id,
                archivo_id,
                operacion
            )
            VALUES (?, ?, 'ELIMINACION')
            """,
            (
                user_id,
                file_id
            )
        )

        cursor.execute(
            """
            DELETE FROM archivos
            WHERE id = ?
            """,
            (file_id,)
        )

        connection.commit()

        send_multicast(
            f"Archivo eliminado: {filename}"
        )

        return True, "Archivo eliminado correctamente."

    except Exception as error:

        connection.rollback()

        return False, f"Error: {error}"

    finally:

        cursor.close()
        connection.close()


# ============================================================
# HISTORIAL
# ============================================================

def get_history():

    connection = get_database_connection()
    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            SELECT
                u.usuario,
                a.nombre,
                t.operacion,
                t.fecha
            FROM transferencias t
            INNER JOIN usuarios u
                ON t.usuario_id = u.id
            LEFT JOIN archivos a
                ON t.archivo_id = a.id
            ORDER BY t.fecha DESC
            """
        )

        rows = cursor.fetchall()

        history = []

        for row in rows:

            history.append(
                {
                    "usuario": row[0],
                    "archivo": row[1],
                    "operacion": row[2],
                    "fecha": str(row[3])
                }
            )

        return history

    finally:

        cursor.close()
        connection.close()


# ============================================================
# CLIENTES TCP
# ============================================================

def handle_client(
    client_socket,
    address
):

    print(
        f"[+] Cliente conectado: {address}"
    )

    current_user = None
    current_user_id = None

    try:

        while True:

            request = receive_json(
                client_socket
            )

            if request is None:
                break

            command = request.get(
                "command"
            )

            # --------------------------------------------
            # REGISTRO
            # --------------------------------------------

            if command == "REGISTER":

                username = request.get(
                    "username"
                )

                password = request.get(
                    "password"
                )

                if not username or not password:

                    response = {
                        "success": False,
                        "message": "Complete todos los campos."
                    }

                else:

                    success, message = register_user(
                        username,
                        password
                    )

                    response = {
                        "success": success,
                        "message": message
                    }

            # --------------------------------------------
            # LOGIN
            # --------------------------------------------

            elif command == "LOGIN":

                username = request.get(
                    "username"
                )

                password = request.get(
                    "password"
                )

                user_id = authenticate_user(
                    username,
                    password
                )

                if user_id is not None:

                    current_user = username
                    current_user_id = user_id

                    response = {
                        "success": True,
                        "message": "Inicio de sesión correcto.",
                        "usuario": username
                    }

                    print(
                        f"[LOGIN] {username}"
                    )

                else:

                    response = {
                        "success": False,
                        "message": "Usuario o contraseña incorrectos."
                    }

            # --------------------------------------------
            # LISTAR ARCHIVOS
            # --------------------------------------------

            elif command == "LIST":
                if current_user_id is None:
                    response = {
                        "success": False,
                        "message": "Debe iniciar sesión."
                    }
                else:
                    try:
                        files = get_files()
                        response = {
                            "success": True,
                            "files": files
                        }
                    except Exception as e:
                        response = {
                            "success": False,
                            "message": f"Error al obtener archivos: {e}"
                        }

            # --------------------------------------------
            # REGISTRAR SUBIDA FTP
            # --------------------------------------------

            elif command == "REGISTER_UPLOAD":

                if current_user_id is None:

                    response = {
                        "success": False,
                        "message": "Debe iniciar sesión."
                    }

                else:

                    filename = request.get(
                        "filename"
                    )

                    size = request.get(
                        "size"
                    )

                    success, message = register_file(
                        filename,
                        size,
                        current_user_id
                    )

                    response = {
                        "success": success,
                        "message": message
                    }

            # --------------------------------------------
            # REGISTRAR DESCARGA
            # --------------------------------------------

            elif command == "REGISTER_DOWNLOAD":

                if current_user_id is None:

                    response = {
                        "success": False,
                        "message": "Debe iniciar sesión."
                    }

                else:

                    filename = request.get(
                        "filename"
                    )

                    register_transfer(
                        current_user,
                        filename,
                        "DESCARGA"
                    )

                    response = {
                        "success": True,
                        "message": "Descarga registrada."
                    }

            # --------------------------------------------
            # ELIMINAR
            # --------------------------------------------

            elif command == "DELETE":

                if current_user_id is None:

                    response = {
                        "success": False,
                        "message": "Debe iniciar sesión."
                    }

                else:

                    filename = request.get(
                        "filename"
                    )

                    success, message = delete_file(
                        filename,
                        current_user_id
                    )

                    response = {
                        "success": success,
                        "message": message
                    }

            # --------------------------------------------
            # HISTORIAL
            # --------------------------------------------

            elif command == "HISTORY":

                if current_user_id is None:

                    response = {
                        "success": False,
                        "message": "Debe iniciar sesión."
                    }

                else:

                    history = get_history()

                    response = {
                        "success": True,
                        "history": history
                    }

            # --------------------------------------------
            # SALIR
            # --------------------------------------------

            elif command == "QUIT":

                response = {
                    "success": True,
                    "message": "Conexión finalizada."
                }

                send_json(
                    client_socket,
                    response
                )

                break

            else:

                response = {
                    "success": False,
                    "message": "Comando desconocido."
                }

            send_json(
                client_socket,
                response
            )

    except ConnectionResetError:

        print(
            f"[!] Cliente desconectado abruptamente: {address}"
        )

    except Exception as error:

        print(
            f"[ERROR CLIENTE] {address}: {error}"
        )

    finally:

        client_socket.close()

        print(
            f"[-] Conexión cerrada: {address}"
        )


# ============================================================
# SERVIDOR FTP
# ============================================================

def start_ftp_server():

    authorizer = DummyAuthorizer()

    # El usuario FTP tendrá acceso a toda la carpeta
    # de archivos.
    authorizer.add_user(
        FTP_USER,
        FTP_PASSWORD,
        BASE_DIRECTORY,
        perm="elradfmwMT"
    )

    handler = FTPHandler

    handler.authorizer = authorizer

    ftp_server = FTPServer(
        (FTP_HOST, FTP_PORT),
        handler
    )

    print(
        f"[FTP] Servidor FTP iniciado en puerto {FTP_PORT}"
    )

    ftp_server.serve_forever()


# ============================================================
# SERVIDOR TCP
# ============================================================

def start_tcp_server():

    server_socket = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    server_socket.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    server_socket.bind(
        (
            SERVER_HOST,
            SERVER_PORT
        )
    )

    server_socket.listen(10)

    print(
        f"[TCP] Servidor escuchando en puerto {SERVER_PORT}"
    )

    while True:

        client_socket, address = server_socket.accept()

        thread = threading.Thread(
            target=handle_client,
            args=(
                client_socket,
                address
            ),
            daemon=True
        )

        thread.start()


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print("       SERVIDOR DE ARCHIVOS")
    print("=" * 60)

    # Crear carpetas
    create_directories()

    # Probar MariaDB
    try:

        connection = get_database_connection()
        connection.close()

        print(
            "[OK] Conexión con MariaDB correcta."
        )

    except Exception as error:

        print(
            "[ERROR] No se pudo conectar con MariaDB."
        )

        print(error)

        return

    # Iniciar FTP en otro hilo
    ftp_thread = threading.Thread(
        target=start_ftp_server,
        daemon=True
    )

    ftp_thread.start()

    # Iniciar servidor TCP
    start_tcp_server()


if __name__ == "__main__":

    main()