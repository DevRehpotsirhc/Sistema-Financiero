import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from hashlib import sha256
from tkinter import *
from tkinter import ttk, messagebox, simpledialog, filedialog
from fpdf import FPDF

# ----------------------------------------------
# CONFIGURACIÓN
DB_NAME = "finanzas.db"
BACKUP_FOLDER = "backups"
APP_VERSION = "1.0.0"
VERSION_CHECK_FILE = "version.txt"  # archivo local o remoto para actualización automática (ejemplo básico)

# ----------------------------------------------
# BASE DE DATOS - CONEXIÓN Y CREACIÓN DE TABLAS

class DB:
    _conn = None
    _lock = threading.Lock()

    @classmethod
    def connect(cls):
        if cls._conn is None:
            cls._conn = sqlite3.connect(DB_NAME, check_same_thread=False)
            cls._conn.row_factory = sqlite3.Row
        return cls._conn

    @classmethod
    def execute(cls, sql, params=()):
        with cls._lock:
            c = cls.connect().cursor()
            c.execute(sql, params)
            cls.connect().commit()
            return c

    @classmethod
    def query(cls, sql, params=()):
        with cls._lock:
            c = cls.connect().cursor()
            c.execute(sql, params)
            return c.fetchall()

    @classmethod
    def close(cls):
        if cls._conn:
            cls._conn.close()
            cls._conn = None


def init_db():
    DB.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        apellido TEXT NOT NULL,
        cedula TEXT NOT NULL UNIQUE,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        tipo TEXT NOT NULL CHECK(tipo IN ('master','estandar'))
    )
    """)
    DB.execute("""
    CREATE TABLE IF NOT EXISTS transacciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT NOT NULL,
        tipo TEXT NOT NULL CHECK(tipo IN ('entrada','salida')),
        monto REAL NOT NULL,
        moneda TEXT NOT NULL CHECK(moneda IN ('Bs','USD')),
        medio TEXT NOT NULL CHECK(medio IN ('fisico','digital')),
        banco_ven REAL DEFAULT 0,
        banco_mercantil REAL DEFAULT 0,
        banco_banesco REAL DEFAULT 0,
        descripcion TEXT,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    DB.execute("""
    CREATE TABLE IF NOT EXISTS cuentas_por_cobrar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente TEXT NOT NULL,
        monto REAL NOT NULL,
        moneda TEXT NOT NULL CHECK(moneda IN ('Bs','USD')),
        fecha_vencimiento DATE NOT NULL,
        estado TEXT NOT NULL CHECK(estado IN ('pendiente','pagada','vencida')) DEFAULT 'pendiente',
        descripcion TEXT,
        fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    DB.execute("""
    CREATE TABLE IF NOT EXISTS cuentas_por_pagar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proveedor TEXT NOT NULL,
        monto REAL NOT NULL,
        moneda TEXT NOT NULL CHECK(moneda IN ('Bs','USD')),
        fecha_vencimiento DATE NOT NULL,
        estado TEXT NOT NULL CHECK(estado IN ('pendiente','pagada','vencida')) DEFAULT 'pendiente',
        descripcion TEXT,
        fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    DB.execute("""
    CREATE TABLE IF NOT EXISTS historial_cambios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT NOT NULL,
        accion TEXT NOT NULL,
        tabla TEXT NOT NULL,
        registro_id INTEGER NOT NULL,
        descripcion TEXT,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

init_db()

# ----------------------------------------------
# UTILIDADES

def hash_password(password):
    return sha256(password.encode('utf-8')).hexdigest()

def check_password(password, hashed):
    return hash_password(password) == hashed

def backup_database():
    if not os.path.exists(BACKUP_FOLDER):
        os.makedirs(BACKUP_FOLDER)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_name = f"backup_{timestamp}.db"
    src = DB_NAME
    dst = os.path.join(BACKUP_FOLDER, backup_name)
    try:
        shutil.copy2(src, dst)
        return True, dst
    except Exception as e:
        return False, str(e)

def log_change(usuario, accion, tabla, registro_id, descripcion=None):
    DB.execute("""
    INSERT INTO historial_cambios (usuario, accion, tabla, registro_id, descripcion)
    VALUES (?, ?, ?, ?, ?)
    """, (usuario, accion, tabla, registro_id, descripcion))

def get_user(username):
    rows = DB.query("SELECT * FROM usuarios WHERE username = ?", (username,))
    return rows[0] if rows else None

# ----------------------------------------------
# REPORTES PDF

class PDFReport(FPDF):
    def header(self):
        self.set_font("Arial", 'B', 12)
        self.cell(0, 10, "Reporte Financiero", border=0, ln=1, align='C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", 'I', 8)
        self.cell(0, 10, f"Página {self.page_no()}", 0, 0, 'C')

def generate_pdf_report(username, filename="reporte_financiero.pdf"):
    pdf = PDFReport()
    pdf.add_page()
    pdf.set_font("Arial", '', 11)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pdf.cell(0, 10, f"Usuario: {username}", ln=1)
    pdf.cell(0, 10, f"Fecha y hora: {now}", ln=1)
    pdf.ln(5)

    # Resumen transacciones
    entradas = DB.query("SELECT SUM(monto) as total FROM transacciones WHERE tipo='entrada'")
    salidas = DB.query("SELECT SUM(monto) as total FROM transacciones WHERE tipo='salida'")

    total_entrada = entradas[0]["total"] or 0
    total_salida = salidas[0]["total"] or 0
    balance = total_entrada - total_salida

    pdf.cell(0, 10, f"Total Entradas: {total_entrada:.2f}", ln=1)
    pdf.cell(0, 10, f"Total Salidas: {total_salida:.2f}", ln=1)
    pdf.cell(0, 10, f"Balance Neto: {balance:.2f}", ln=1)
    pdf.ln(10)

    # Cuentas por cobrar
    pdf.cell(0, 10, "Cuentas por Cobrar:", ln=1)
    cxc = DB.query("SELECT * FROM cuentas_por_cobrar ORDER BY fecha_vencimiento")
    for c in cxc:
        pdf.cell(0, 8, f"{c['cliente']} - {c['monto']} {c['moneda']} - Vence: {c['fecha_vencimiento']} - Estado: {c['estado']}", ln=1)

    pdf.ln(5)
    # Cuentas por pagar
    pdf.cell(0, 10, "Cuentas por Pagar:", ln=1)
    cxp = DB.query("SELECT * FROM cuentas_por_pagar ORDER BY fecha_vencimiento")
    for c in cxp:
        pdf.cell(0, 8, f"{c['proveedor']} - {c['monto']} {c['moneda']} - Vence: {c['fecha_vencimiento']} - Estado: {c['estado']}", ln=1)

    pdf.output(filename)
    return filename

# ----------------------------------------------
# INTERFAZ GRÁFICA

class App(Tk):
    def __init__(self):
        super().__init__()
        self.title("Sistema Financiero Completo - v" + APP_VERSION)
        self.geometry("900x650")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.current_user = None
        self.create_login_screen()
        self.backup_on_startup()
        self.after(60 * 60 * 1000, self.backup_periodic)  # backup cada hora

    def backup_on_startup(self):
        success, msg = backup_database()
        if success:
            print(f"Backup realizado al iniciar: {msg}")
        else:
            print(f"Error backup al iniciar: {msg}")

    def backup_periodic(self):
        success, msg = backup_database()
        if success:
            print(f"Backup periódico realizado: {msg}")
        else:
            print(f"Error backup periódico: {msg}")
        self.after(60 * 60 * 1000, self.backup_periodic)

    def on_close(self):
        # Backup al cerrar app
        success, msg = backup_database()
        if success:
            print(f"Backup realizado al cerrar: {msg}")
        else:
            print(f"Error backup al cerrar: {msg}")
        self.destroy()

    def clear_screen(self):
        for widget in self.winfo_children():
            widget.destroy()

    # ---------------------
    # LOGIN
    def create_login_screen(self):
        self.clear_screen()
        frame = Frame(self)
        frame.pack(pady=100)

        Label(frame, text="Usuario:").grid(row=0, column=0, sticky=E)
        usuario_entry = Entry(frame)
        usuario_entry.grid(row=0, column=1, pady=5)

        Label(frame, text="Contraseña:").grid(row=1, column=0, sticky=E)
        password_entry = Entry(frame, show="*")
        password_entry.grid(row=1, column=1, pady=5)

        def login():
            username = usuario_entry.get().strip()
            password = password_entry.get()
            if not username or not password:
                messagebox.showwarning("Error", "Debe ingresar usuario y contraseña")
                return
            user = get_user(username)
            if not user or not check_password(password, user["password"]):
                messagebox.showerror("Error", "Usuario o contraseña incorrectos")
                return
            self.current_user = user
            messagebox.showinfo("Bienvenido", f"Bienvenido {user['nombre']} {user['apellido']}")
            self.create_main_screen()

        Button(frame, text="Ingresar", command=login).grid(row=2, column=0, columnspan=2, pady=10)
        Button(frame, text="Registrarse", command=lambda: self.create_user_registration_screen(solo_estandar=True)).grid(row=4, column=0, columnspan=2)
        # Crear usuario master si no existe ninguno
        masters = DB.query("SELECT * FROM usuarios WHERE tipo='master'")
        if not masters:
            if messagebox.askyesno("Registro inicial", "No hay usuario MASTER. Crear uno ahora?"):
                self.create_user_registration_screen(master_creation=True)

    # ---------------------
    # PANTALLA PRINCIPAL CON PESTAÑAS
    def create_main_screen(self):
        self.clear_screen()

        menubar = Menu(self)
        self.config(menu=menubar)

        # Menú Archivo
        archivo_menu = Menu(menubar, tearoff=0)
        archivo_menu.add_command(label="Backup Manual", command=self.backup_manual)
        archivo_menu.add_separator()
        archivo_menu.add_command(label="Cerrar Sesión", command=self.logout)
        archivo_menu.add_command(label="Salir", command=self.on_close)
        menubar.add_cascade(label="Archivo", menu=archivo_menu)

        # Menú Usuarios (solo para master)
        if self.current_user and self.current_user["tipo"] == "master":
            user_menu = Menu(menubar, tearoff=0)
            user_menu.add_command(label="Registrar Usuario", command=self.create_user_registration_screen)
            user_menu.add_command(label="Historial de Cambios", command=self.view_change_history)
            menubar.add_cascade(label="Usuarios", menu=user_menu)

        # Menú Ayuda
        ayuda_menu = Menu(menubar, tearoff=0)
        ayuda_menu.add_command(label="Acerca de", command=self.show_about)
        ayuda_menu.add_command(label="Verificar actualización", command=self.check_update)
        menubar.add_cascade(label="Ayuda", menu=ayuda_menu)

        # Pestañas
        tab_control = ttk.Notebook(self)
        tab_control.pack(expand=1, fill="both")

        # Pestaña transacciones
        tab_transacciones = Frame(tab_control)
        tab_control.add(tab_transacciones, text="Transacciones")
        self.build_tab_transacciones(tab_transacciones)

        # Pestaña cuentas por cobrar
        tab_cxc = Frame(tab_control)
        tab_control.add(tab_cxc, text="Cuentas por Cobrar")
        self.build_tab_cuentas_por_cobrar(tab_cxc)

        # Pestaña cuentas por pagar
        tab_cxp = Frame(tab_control)
        tab_control.add(tab_cxp, text="Cuentas por Pagar")
        self.build_tab_cuentas_por_pagar(tab_cxp)

        # Pestaña reportes
        tab_reportes = Frame(tab_control)
        tab_control.add(tab_reportes, text="Reportes")
        self.build_tab_reportes(tab_reportes)

    def logout(self):
        if messagebox.askyesno("Cerrar Sesión", "¿Desea cerrar sesión?"):
            self.current_user = None
            self.create_login_screen()

    # ---------------------
    # USUARIOS

    def create_user_registration_screen(self, master_creation=False, solo_estandar=False):
        self.clear_screen()
        frame = Frame(self)
        frame.pack(pady=20)

        Label(frame, text="Nombre:").grid(row=0, column=0, sticky=E)
        nombre_entry = Entry(frame)
        nombre_entry.grid(row=0, column=1)

        Label(frame, text="Apellido:").grid(row=1, column=0, sticky=E)
        apellido_entry = Entry(frame)
        apellido_entry.grid(row=1, column=1)

        Label(frame, text="Cédula:").grid(row=2, column=0, sticky=E)
        cedula_entry = Entry(frame)
        cedula_entry.grid(row=2, column=1)

        Label(frame, text="Usuario (username):").grid(row=3, column=0, sticky=E)
        username_entry = Entry(frame)
        username_entry.grid(row=3, column=1)

        Label(frame, text="Contraseña:").grid(row=4, column=0, sticky=E)
        password_entry = Entry(frame, show="*")
        password_entry.grid(row=4, column=1)
        if not solo_estandar or not master_creation:
            Label(frame, text="Tipo:").grid(row=5, column=0, sticky=E)
        tipo_var = StringVar(value="estandar")
        if master_creation:
            tipo_var.set("master")
        elif solo_estandar:
            tipo_var.set("estandar")
        else:
            Radiobutton(frame, text="Master", variable=tipo_var, value="master").grid(row=5, column=1, sticky=W)
            Radiobutton(frame, text="Estándar", variable=tipo_var, value="estandar").grid(row=5, column=1, sticky=E)

        def register_user():
            nombre = nombre_entry.get().strip()
            apellido = apellido_entry.get().strip()
            cedula = cedula_entry.get().strip()
            username = username_entry.get().strip()
            password = password_entry.get()
            tipo = tipo_var.get()

            if not all([nombre, apellido, cedula, username, password]):
                messagebox.showwarning("Error", "Todos los campos son obligatorios")
                return
            if len(password) < 4:
                messagebox.showwarning("Error", "La contraseña debe tener al menos 4 caracteres")
                return
            if get_user(username):
                messagebox.showerror("Error", "El usuario ya existe")
                return

            hashed = hash_password(password)
            try:
                DB.execute("""
                    INSERT INTO usuarios (nombre, apellido, cedula, username, password, tipo)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (nombre, apellido, cedula, username, hashed, tipo))
                messagebox.showinfo("Éxito", "Usuario registrado correctamente")
                self.create_login_screen()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo registrar el usuario: {e}")

        Button(frame, text="Registrar", command=register_user).grid(row=6, column=0, columnspan=2, pady=10)
        if not master_creation:
            Button(frame, text="Cancelar", command=self.create_login_screen if solo_estandar else self.create_main_screen).grid(row=7, column=0, columnspan=2)

    # ---------------------
    # TRANSACCIONES

    def build_tab_transacciones(self, container):
        frm_top = Frame(container)
        frm_top.pack(fill=X, pady=5)
        frm_buttons = Frame(container)
        frm_buttons.pack(fill=X, pady=5)
        frm_balance = Frame(container)
        frm_balance.pack(fill=X, pady=5)

        balance_label = Label(frm_balance, text="Balance: Calculando...", fg="blue")
        balance_label.pack(side=LEFT, padx=10)
        frm_table = Frame(container)
        frm_table.pack(expand=1, fill=BOTH)

        # Campos de entrada
        Label(frm_top, text="Tipo:").grid(row=0, column=0)
        tipo_var = StringVar(value="entrada")
        ttk.Combobox(frm_top, textvariable=tipo_var, values=["entrada", "salida"], state="readonly", width=10).grid(row=0, column=1)

        Label(frm_top, text="Monto:").grid(row=0, column=2)
        monto_entry = Entry(frm_top, width=15)
        monto_entry.grid(row=0, column=3)

        Label(frm_top, text="Moneda:").grid(row=0, column=4)
        moneda_var = StringVar(value="Bs")
        ttk.Combobox(frm_top, textvariable=moneda_var, values=["Bs", "USD"], state="readonly", width=5).grid(row=0, column=5)

        Label(frm_top, text="Medio:").grid(row=0, column=6)
        medio_var = StringVar(value="fisico")
        ttk.Combobox(frm_top, textvariable=medio_var, values=["fisico", "digital"], state="readonly", width=7).grid(row=0, column=7)

        Label(frm_top, text="Banco Ven:").grid(row=1, column=0)
        banco_ven_entry = Entry(frm_top, width=10)
        banco_ven_entry.grid(row=1, column=1)
        banco_ven_entry.insert(0, "0")

        Label(frm_top, text="Banco Mercantil:").grid(row=1, column=2)
        banco_merc_entry = Entry(frm_top, width=10)
        banco_merc_entry.grid(row=1, column=3)
        banco_merc_entry.insert(0, "0")

        Label(frm_top, text="Banco Banesco:").grid(row=1, column=4)
        banco_ban_entry = Entry(frm_top, width=10)
        banco_ban_entry.grid(row=1, column=5)
        banco_ban_entry.insert(0, "0")

        Label(frm_top, text="Descripción:").grid(row=1, column=6)
        descripcion_entry = Entry(frm_top, width=25)
        descripcion_entry.grid(row=1, column=7)

        # Tabla
        cols = ("ID", "Usuario", "Tipo", "Monto", "Moneda", "Medio", "Banco Ven", "Banco Mercantil", "Banco Banesco", "Descripción", "Fecha")
        tree = ttk.Treeview(frm_table, columns=cols, show="headings")
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, minwidth=50, width=90, stretch=False)
        tree.pack(expand=1, fill=BOTH)

        def load_transactions():
            for row in tree.get_children():
                tree.delete(row)
            data = DB.query("SELECT * FROM transacciones ORDER BY fecha DESC")
            for d in data:
                tree.insert("", END, values=(
                    d["id"], d["usuario"], d["tipo"], f"{d['monto']:.2f}", d["moneda"], d["medio"],
                    f"{d['banco_ven']:.2f}", f"{d['banco_mercantil']:.2f}", f"{d['banco_banesco']:.2f}",
                    d["descripcion"] or "", d["fecha"]
                ))
            entradas = DB.query("SELECT SUM(monto) as total FROM transacciones WHERE tipo='entrada'")
            salidas = DB.query("SELECT SUM(monto) as total FROM transacciones WHERE tipo='salida'")

            total_entrada = entradas[0]["total"] or 0
            total_salida = salidas[0]["total"] or 0
            balance = total_entrada - total_salida

            balance_label.config(text=f"Balance actual: {balance:.2f}")

        def add_transaction():
            try:
                monto = float(monto_entry.get())
                banco_ven = float(banco_ven_entry.get())
                banco_merc = float(banco_merc_entry.get())
                banco_ban = float(banco_ban_entry.get())
            except ValueError:
                messagebox.showwarning("Error", "Monto y bancos deben ser números válidos")
                return
            tipo = tipo_var.get()
            moneda = moneda_var.get()
            medio = medio_var.get()
            descripcion = descripcion_entry.get().strip()
            if monto <= 0:
                messagebox.showwarning("Error", "El monto debe ser mayor a cero")
                return
            if self.current_user:
                DB.execute("""
                    INSERT INTO transacciones (usuario, tipo, monto, moneda, medio, banco_ven, banco_mercantil, banco_banesco, descripcion)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (self.current_user["username"], tipo, monto, moneda, medio, banco_ven, banco_merc, banco_ban, descripcion))
                log_change(self.current_user["username"], "insert", "transacciones", DB.execute("SELECT last_insert_rowid()").fetchone()[0], descripcion)
                messagebox.showinfo("Éxito", "Transacción registrada")
                load_transactions()
                # Limpiar
                monto_entry.delete(0, END)
                descripcion_entry.delete(0, END)
                banco_ven_entry.delete(0, END)
                banco_ven_entry.insert(0, "0")
                banco_merc_entry.delete(0, END)
                banco_merc_entry.insert(0, "0")
                banco_ban_entry.delete(0, END)
                banco_ban_entry.insert(0, "0")

        def delete_transaction():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("Error", "Seleccione una transacción para eliminar")
                return
            if self.current_user and self.current_user["tipo"] != "master":
                messagebox.showerror("Permiso denegado", "Solo usuarios MASTER pueden eliminar transacciones")
                return
            tid = tree.item(selected[0])["values"][0]
            if self.current_user and messagebox.askyesno("Confirmar", "¿Eliminar transacción seleccionada?"):
                DB.execute("DELETE FROM transacciones WHERE id = ?", (tid,))
                log_change(self.current_user["username"], "delete", "transacciones", tid, "Eliminada desde interfaz")
                load_transactions()

        Button(frm_buttons, text="Agregar", command=add_transaction).pack(side=LEFT, padx=5)
        Button(frm_buttons, text="Eliminar", command=delete_transaction).pack(side=LEFT, padx=5)

        load_transactions()

    # ---------------------
    # CUENTAS POR COBRAR

    def build_tab_cuentas_por_cobrar(self, container):
        frm_top = Frame(container)
        frm_top.pack(fill=X, pady=5)
        frm_buttons = Frame(container)
        frm_buttons.pack(fill=X, pady=5)
        frm_table = Frame(container)
        frm_table.pack(expand=1, fill=BOTH)

        Label(frm_top, text="Cliente:").grid(row=0, column=0)
        cliente_entry = Entry(frm_top, width=20)
        cliente_entry.grid(row=0, column=1)

        Label(frm_top, text="Monto:").grid(row=0, column=2)
        monto_entry = Entry(frm_top, width=15)
        monto_entry.grid(row=0, column=3)

        Label(frm_top, text="Moneda:").grid(row=0, column=4)
        moneda_var = StringVar(value="Bs")
        ttk.Combobox(frm_top, textvariable=moneda_var, values=["Bs", "USD"], state="readonly", width=5).grid(row=0, column=5)

        Label(frm_top, text="Fecha Vencimiento (YYYY-MM-DD):").grid(row=1, column=0)
        venc_entry = Entry(frm_top, width=15)
        venc_entry.grid(row=1, column=1)

        Label(frm_top, text="Descripción:").grid(row=1, column=2)
        descripcion_entry = Entry(frm_top, width=30)
        descripcion_entry.grid(row=1, column=3, columnspan=3)

        cols = ("ID", "Cliente", "Monto", "Moneda", "Vencimiento", "Estado", "Descripción", "Registro")
        tree = ttk.Treeview(frm_table, columns=cols, show="headings")
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, minwidth=50, width=100, stretch=False)
        tree.pack(expand=1, fill=BOTH)

        def load_cxc():
            for row in tree.get_children():
                tree.delete(row)
            data = DB.query("SELECT * FROM cuentas_por_cobrar ORDER BY fecha_vencimiento")
            for d in data:
                tree.insert("", END, values=(
                    d["id"], d["cliente"], f"{d['monto']:.2f}", d["moneda"], d["fecha_vencimiento"], d["estado"],
                    d["descripcion"] or "", d["fecha_registro"]
                ))

        def add_cxc():
            cliente = cliente_entry.get().strip()
            desc = descripcion_entry.get().strip()
            moneda = moneda_var.get()
            try:
                monto = float(monto_entry.get())
            except:
                messagebox.showwarning("Error", "Monto inválido")
                return
            fecha_venc = venc_entry.get().strip()
            try:
                datetime.strptime(fecha_venc, "%Y-%m-%d")
            except:
                messagebox.showwarning("Error", "Formato de fecha vencimiento inválido")
                return
            if monto <= 0 or not cliente:
                messagebox.showwarning("Error", "Complete todos los campos correctamente")
                return
            DB.execute("""
                INSERT INTO cuentas_por_cobrar (cliente, monto, moneda, fecha_vencimiento, descripcion)
                VALUES (?, ?, ?, ?, ?)
            """, (cliente, monto, moneda, fecha_venc, desc))
            messagebox.showinfo("Éxito", "Cuenta por cobrar registrada")
            load_cxc()
            cliente_entry.delete(0, END)
            monto_entry.delete(0, END)
            venc_entry.delete(0, END)
            descripcion_entry.delete(0, END)

        def mark_paid_cxc():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("Error", "Seleccione una cuenta por cobrar")
                return
            cid = tree.item(selected[0])["values"][0]
            DB.execute("UPDATE cuentas_por_cobrar SET estado = 'pagada' WHERE id = ?", (cid,))
            messagebox.showinfo("Éxito", "Cuenta por cobrar marcada como pagada")
            load_cxc()

        Button(frm_buttons, text="Agregar", command=add_cxc).pack(side=LEFT, padx=5)
        Button(frm_buttons, text="Marcar como Pagada", command=mark_paid_cxc).pack(side=LEFT, padx=5)

        load_cxc()

    # ---------------------
    # CUENTAS POR PAGAR

    def build_tab_cuentas_por_pagar(self, container):
        frm_top = Frame(container)
        frm_top.pack(fill=X, pady=5)
        frm_buttons = Frame(container)
        frm_buttons.pack(fill=X, pady=5)
        frm_table = Frame(container)
        frm_table.pack(expand=1, fill=BOTH)

        Label(frm_top, text="Proveedor:").grid(row=0, column=0)
        proveedor_entry = Entry(frm_top, width=20)
        proveedor_entry.grid(row=0, column=1)

        Label(frm_top, text="Monto:").grid(row=0, column=2)
        monto_entry = Entry(frm_top, width=15)
        monto_entry.grid(row=0, column=3)

        Label(frm_top, text="Moneda:").grid(row=0, column=4)
        moneda_var = StringVar(value="Bs")
        ttk.Combobox(frm_top, textvariable=moneda_var, values=["Bs", "USD"], state="readonly", width=5).grid(row=0, column=5)

        Label(frm_top, text="Fecha Vencimiento (YYYY-MM-DD):").grid(row=1, column=0)
        venc_entry = Entry(frm_top, width=15)
        venc_entry.grid(row=1, column=1)

        Label(frm_top, text="Descripción:").grid(row=1, column=2)
        descripcion_entry = Entry(frm_top, width=30)
        descripcion_entry.grid(row=1, column=3, columnspan=3)

        cols = ("ID", "Proveedor", "Monto", "Moneda", "Vencimiento", "Estado", "Descripción", "Registro")
        tree = ttk.Treeview(frm_table, columns=cols, show="headings")
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, minwidth=50, width=100, stretch=False)
        tree.pack(expand=1, fill=BOTH)

        def load_cxp():
            for row in tree.get_children():
                tree.delete(row)
            data = DB.query("SELECT * FROM cuentas_por_pagar ORDER BY fecha_vencimiento")
            for d in data:
                tree.insert("", END, values=(
                    d["id"], d["proveedor"], f"{d['monto']:.2f}", d["moneda"], d["fecha_vencimiento"], d["estado"],
                    d["descripcion"] or "", d["fecha_registro"]
                ))

        def add_cxp():
            proveedor = proveedor_entry.get().strip()
            desc = descripcion_entry.get().strip()
            moneda = moneda_var.get()
            try:
                monto = float(monto_entry.get())
            except:
                messagebox.showwarning("Error", "Monto inválido")
                return
            fecha_venc = venc_entry.get().strip()
            try:
                datetime.strptime(fecha_venc, "%Y-%m-%d")
            except:
                messagebox.showwarning("Error", "Formato de fecha vencimiento inválido")
                return
            if monto <= 0 or not proveedor:
                messagebox.showwarning("Error", "Complete todos los campos correctamente")
                return
            DB.execute("""
                INSERT INTO cuentas_por_pagar (proveedor, monto, moneda, fecha_vencimiento, descripcion)
                VALUES (?, ?, ?, ?, ?)
            """, (proveedor, monto, moneda, fecha_venc, desc))
            messagebox.showinfo("Éxito", "Cuenta por pagar registrada")
            load_cxp()
            proveedor_entry.delete(0, END)
            monto_entry.delete(0, END)
            venc_entry.delete(0, END)
            descripcion_entry.delete(0, END)

        def mark_paid_cxp():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("Error", "Seleccione una cuenta por pagar")
                return
            cid = tree.item(selected[0])["values"][0]
            DB.execute("UPDATE cuentas_por_pagar SET estado = 'pagada' WHERE id = ?", (cid,))
            messagebox.showinfo("Éxito", "Cuenta por pagar marcada como pagada")
            load_cxp()

        Button(frm_buttons, text="Agregar", command=add_cxp).pack(side=LEFT, padx=5)
        Button(frm_buttons, text="Marcar como Pagada", command=mark_paid_cxp).pack(side=LEFT, padx=5)

        load_cxp()

    # ---------------------
    # REPORTES

    def build_tab_reportes(self, container):
        frm_top = Frame(container)
        frm_top.pack(pady=10)

        Label(frm_top, text="Generar reporte completo:").pack(side=LEFT, padx=5)
        Button(frm_top, text="Generar PDF", command=self.generate_report_pdf).pack(side=LEFT)

        self.report_label = Label(container, text="", fg="green")
        self.report_label.pack(pady=10)

    def generate_report_pdf(self):
        try:
            filename = filedialog.asksaveasfilename(
                defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")],
                initialfile=f"reporte_financiero_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            )
            if not filename:
                return
            if self.current_user:
                generate_pdf_report(self.current_user["username"], filename)
                self.report_label.config(text=f"Reporte generado: {filename}")
                messagebox.showinfo("Reporte", f"Reporte PDF generado correctamente en:\n{filename}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el reporte: {e}")

    # ---------------------
    # HISTORIAL DE CAMBIOS

    def view_change_history(self):
        self.clear_screen()
        frame = Frame(self)
        frame.pack(expand=1, fill=BOTH)

        Label(frame, text="Historial de Cambios", font=("Arial", 14, "bold")).pack(pady=10)

        cols = ("ID", "Usuario", "Acción", "Tabla", "ID Registro", "Descripción", "Fecha")
        tree = ttk.Treeview(frame, columns=cols, show="headings")
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, minwidth=50, width=120, stretch=False)
        tree.pack(expand=1, fill=BOTH, padx=10, pady=10)

        def load_history():
            for row in tree.get_children():
                tree.delete(row)
            data = DB.query("SELECT * FROM historial_cambios ORDER BY fecha DESC LIMIT 1000")
            for d in data:
                tree.insert("", END, values=(
                    d["id"], d["usuario"], d["accion"], d["tabla"], d["registro_id"], d["descripcion"] or "", d["fecha"]
                ))
        load_history()

        Button(frame, text="Volver", command=self.create_main_screen).pack(pady=10)

    # ---------------------
    # AYUDA / ACERCA DE

    def show_about(self):
        messagebox.showinfo("Acerca de", f"Sistema Financiero Completo\nVersión {APP_VERSION}\nDesarrollado por Ing Douglas Hidalgo")

    def check_update(self):
        # Demo muy básico de actualización: solo verifica un archivo local con versión
        if not os.path.exists(VERSION_CHECK_FILE):
            messagebox.showinfo("Actualización", "No se encontró información de actualización.")
            return
        with open(VERSION_CHECK_FILE, "r") as f:
            latest_version = f.read().strip()
        if latest_version > APP_VERSION:
            messagebox.showinfo("Actualización disponible", f"Existe una versión más reciente: {latest_version}\nDescargue la nueva versión desde el sitio oficial.")
        else:
            messagebox.showinfo("Actualización", "Usted tiene la última versión.")

    # ---------------------
    # BACKUP MANUAL

    def backup_manual(self):
        success, msg = backup_database()
        if success:
            messagebox.showinfo("Backup", f"Backup realizado correctamente:\n{msg}")
        else:
            messagebox.showerror("Backup", f"Error al hacer backup:\n{msg}")

# ------------------------------
# EJECUCIÓN

if __name__ == "__main__":
    app = App()
    app.mainloop()
    DB.close()
