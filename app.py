
import sqlite3
import io
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import qrcode
import streamlit as st

DB_PATH = Path(__file__).parent / "mini_market.db"

st.set_page_config(
    page_title="Mini Market | Team Building",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# -----------------------------
# DATABASE
# -----------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS groups (
        group_id INTEGER PRIMARY KEY,
        group_name TEXT NOT NULL,
        initial_balance REAL NOT NULL DEFAULT 0,
        current_balance REAL NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS products (
        product_id INTEGER PRIMARY KEY,
        product_name TEXT NOT NULL,
        price REAL NOT NULL DEFAULT 0,
        stock INTEGER NOT NULL DEFAULT 0,
        initial_stock INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS purchases (
        purchase_id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        date_time TEXT NOT NULL,
        total REAL NOT NULL,
        balance_before REAL NOT NULL,
        balance_after REAL NOT NULL,
        FOREIGN KEY(group_id) REFERENCES groups(group_id)
    );

    CREATE TABLE IF NOT EXISTS purchase_items (
        purchase_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        subtotal REAL NOT NULL,
        FOREIGN KEY(purchase_id) REFERENCES purchases(purchase_id),
        FOREIGN KEY(product_id) REFERENCES products(product_id)
    );
    """)

    product_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(products)").fetchall()
    }
    if "initial_stock" not in product_columns:
        conn.execute(
            "ALTER TABLE products ADD COLUMN initial_stock INTEGER NOT NULL DEFAULT 0"
        )
        conn.execute("UPDATE products SET initial_stock = stock WHERE initial_stock = 0")

    conn.commit()
    conn.close()


def seed_test_data():
    """
    Dados iguais aos exemplos das listas do SharePoint mostradas
    na atividade. Executar somente para criar uma base de teste.
    """
    conn = get_conn()

    groups = [
        (1, "Grupo 1", 64),
        (2, "Grupo 2", 200),
        (3, "Grupo 3", 300),
        (4, "Grupo 4", 400),
        (5, "Grupo 5", 500),
        (6, "Grupo 6", 600),
        (7, "Grupo 7", 700),
    ]

    products = [
        (1, "Pão", 5, 30),
        (2, "Hambúrguer", 18, 5),
        (3, "Queijo", 8, 20),
        (4, "Alface", 4, 20),
        (5, "Tomate", 6, 20),
        (6, "Batata", 7, 25),
        (7, "Refrigerante", 9, 30),
        (8, "Água", 4, 40),
        (9, "Sal", 1, 5),
        (10, "Mel", 3, 30),
    ]

    for group_id, name, balance in groups:
        conn.execute("""
            INSERT INTO groups(group_id, group_name, initial_balance, current_balance)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                group_name = excluded.group_name,
                initial_balance = excluded.initial_balance,
                current_balance = excluded.current_balance
        """, (group_id, name, balance, balance))

    for product_id, name, price, stock in products:
        conn.execute("""
            INSERT INTO products(product_id, product_name, price, stock, initial_stock)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                product_name = excluded.product_name,
                price = excluded.price,
                stock = excluded.stock,
                initial_stock = excluded.initial_stock
        """, (product_id, name, price, stock, stock))

    conn.commit()
    conn.close()


# -----------------------------
# DATA ACCESS
# -----------------------------

def get_groups():
    conn = get_conn()
    rows = conn.execute("""
        SELECT group_id, group_name, initial_balance, current_balance
        FROM groups
        ORDER BY group_id
    """).fetchall()
    conn.close()
    return rows


def get_products():
    conn = get_conn()
    rows = conn.execute("""
        SELECT product_id, product_name, price, stock
        FROM products
        ORDER BY product_id
    """).fetchall()
    conn.close()
    return rows


def get_purchase_history():
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            p.purchase_id,
            p.date_time,
            g.group_name,
            p.total,
            p.balance_before,
            p.balance_after
        FROM purchases p
        JOIN groups g ON g.group_id = p.group_id
        ORDER BY p.purchase_id DESC
    """).fetchall()
    conn.close()
    return rows


def get_purchase_items(purchase_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            pi.quantity,
            pi.unit_price,
            pi.subtotal,
            pr.product_name
        FROM purchase_items pi
        JOIN products pr ON pr.product_id = pi.product_id
        WHERE pi.purchase_id = ?
        ORDER BY pi.purchase_item_id
    """, (purchase_id,)).fetchall()
    conn.close()
    return rows


def execute_purchase(group_id, cart):
    """
    Faz saldo + estoque + histórico dentro de UMA transação SQLite.
    Isso evita registrar metade da compra se ocorrer algum erro.
    """
    if not cart:
        raise ValueError("Carrinho vazio.")

    conn = get_conn()

    try:
        conn.execute("BEGIN IMMEDIATE")

        group = conn.execute("""
            SELECT group_id, group_name, current_balance
            FROM groups
            WHERE group_id = ?
        """, (group_id,)).fetchone()

        if not group:
            raise ValueError("Grupo não encontrado.")

        total = 0
        validated_items = []

        for item in cart:
            product = conn.execute("""
                SELECT product_id, product_name, price, stock
                FROM products
                WHERE product_id = ?
            """, (item["product_id"],)).fetchone()

            if not product:
                raise ValueError(f"Produto {item['product_id']} não encontrado.")

            qty = int(item["quantity"])

            if qty <= 0:
                raise ValueError("Quantidade inválida.")

            if qty > product["stock"]:
                raise ValueError(
                    f"Estoque insuficiente para {product['product_name']}. "
                    f"Disponível: {product['stock']}."
                )

            subtotal = product["price"] * qty
            total += subtotal

            validated_items.append({
                "product_id": product["product_id"],
                "product_name": product["product_name"],
                "quantity": qty,
                "unit_price": product["price"],
                "subtotal": subtotal,
            })

        balance_before = group["current_balance"]

        if total > balance_before:
            raise ValueError(
                f"Saldo insuficiente. "
                f"Saldo: R$ {balance_before:,.2f} | "
                f"Compra: R$ {total:,.2f}"
            )

        balance_after = balance_before - total
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        cur = conn.execute("""
            INSERT INTO purchases
                (group_id, date_time, total, balance_before, balance_after)
            VALUES (?, ?, ?, ?, ?)
        """, (group_id, now, total, balance_before, balance_after))

        purchase_id = cur.lastrowid

        for item in validated_items:
            conn.execute("""
                UPDATE products
                SET stock = stock - ?
                WHERE product_id = ?
            """, (item["quantity"], item["product_id"]))

            conn.execute("""
                INSERT INTO purchase_items
                    (purchase_id, product_id, quantity, unit_price, subtotal)
                VALUES (?, ?, ?, ?, ?)
            """, (
                purchase_id,
                item["product_id"],
                item["quantity"],
                item["unit_price"],
                item["subtotal"],
            ))

        conn.execute("""
            UPDATE groups
            SET current_balance = ?
            WHERE group_id = ?
        """, (balance_after, group_id))

        conn.commit()

        return {
            "purchase_id": purchase_id,
            "group_name": group["group_name"],
            "date_time": now,
            "items": validated_items,
            "total": total,
            "balance_before": balance_before,
            "balance_after": balance_after,
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# -----------------------------
# HELPERS
# -----------------------------

def money(value):
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


PRODUCT_ICONS = {
    "Pão": "🍞",
    "Hambúrguer": "🍔",
    "Queijo": "🧀",
    "Alface": "🥬",
    "Tomate": "🍅",
    "Batata": "🥔",
    "Refrigerante": "🥤",
    "Água": "💧",
    "Sal": "🧂",
    "Molho": "🧂",
    "Mel": "🍯",
}


def product_icon(product_name):
    return PRODUCT_ICONS.get(product_name, "🛒")


def access_url():
    """URL acessível pelo celular na mesma rede da máquina que executa o app."""
    configured = os.getenv("MINI_MARKET_URL")
    if not configured:
        try:
            configured = st.secrets.get("MINI_MARKET_URL")
        except Exception:
            configured = None
    if configured:
        return str(configured).rstrip("/")

    return "https://mini-market-team-building-hgnnwkku3kdzlxaozjravs.streamlit.app"



def secret_value(name, default=None):
    value = os.getenv(name)
    if value:
        return str(value).strip()
    try:
        value = st.secrets.get(name)
        if value is not None:
            return str(value).strip()
        general = st.secrets.get("general")
        if general and general.get(name) is not None:
            return str(general.get(name)).strip()
    except Exception:
        pass
    return default


def admin_login():
    if st.session_state.get("admin_authenticated"):
        if st.button("Sair da administração", key="admin_logout"):
            st.session_state.admin_authenticated = False
            st.rerun()
        return True

    st.warning("Área restrita. Informe as credenciais do administrador.")
    username = st.text_input("Usuário", key="admin_username")
    password = st.text_input("Senha", type="password", key="admin_password")
    if st.button("Entrar", type="primary", key="admin_login_button"):
        expected_user = secret_value("ADMIN_USERNAME", "SSBMGF")
        expected_password = secret_value("ADMIN_PASSWORD", "SSBMGF")
        if not expected_user or not expected_password:
            st.error("As credenciais ainda não foram configuradas nos Secrets da aplicação.")
        elif username == expected_user and password == expected_password:
            st.session_state.admin_authenticated = True
            st.rerun()
        else:
            st.error("Usuário ou senha inválidos.")
    return False


def qr_bytes(url):
    image = qrcode.make(url)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def import_admin_workbook(uploaded_file, reset_activity=False):
    """Importa Grupos e Produtos sem apagar o histórico de compras."""
    groups_df = pd.read_excel(uploaded_file, sheet_name="Grupos", header=3)
    products_df = pd.read_excel(uploaded_file, sheet_name="Produtos", header=3)

    group_required = {"group_id", "group_name", "initial_balance"}
    product_required = {"product_id", "product_name", "unit_price", "initial_stock"}

    missing_groups = group_required - set(groups_df.columns)
    missing_products = product_required - set(products_df.columns)
    if missing_groups:
        raise ValueError(f"Campos ausentes na aba Grupos: {', '.join(sorted(missing_groups))}")
    if missing_products:
        raise ValueError(f"Campos ausentes na aba Produtos: {', '.join(sorted(missing_products))}")

    groups_df = groups_df.dropna(how="all").copy()
    products_df = products_df.dropna(how="all").copy()

    for df, id_col, label in [
        (groups_df, "group_id", "Grupos"),
        (products_df, "product_id", "Produtos"),
    ]:
        if df[id_col].isna().any():
            raise ValueError(f"Há código vazio na aba {label}.")
        if df[id_col].duplicated().any():
            duplicated = df.loc[df[id_col].duplicated(), id_col].tolist()
            raise ValueError(f"Há códigos duplicados na aba {label}: {duplicated}")

    groups_df["group_id"] = pd.to_numeric(groups_df["group_id"], errors="coerce")
    groups_df["initial_balance"] = pd.to_numeric(groups_df["initial_balance"], errors="coerce")
    products_df["product_id"] = pd.to_numeric(products_df["product_id"], errors="coerce")
    products_df["unit_price"] = pd.to_numeric(products_df["unit_price"], errors="coerce")
    products_df["initial_stock"] = pd.to_numeric(products_df["initial_stock"], errors="coerce")

    if groups_df[["group_id", "initial_balance"]].isna().any().any():
        raise ValueError("Código ou saldo inicial inválido na aba Grupos.")
    if products_df[["product_id", "unit_price", "initial_stock"]].isna().any().any():
        raise ValueError("Código, preço ou estoque inicial inválido na aba Produtos.")
    if (groups_df["initial_balance"] < 0).any():
        raise ValueError("O saldo inicial não pode ser negativo.")
    if (products_df[["unit_price", "initial_stock"]] < 0).any().any():
        raise ValueError("Preço e estoque inicial não podem ser negativos.")

    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for row in groups_df.itertuples(index=False):
            group_id = int(row.group_id)
            name = str(row.group_name).strip()
            if not name or name == "nan":
                raise ValueError(f"Nome vazio para o grupo {group_id}.")
            balance = float(row.initial_balance)
            existing = conn.execute(
                "SELECT group_id FROM groups WHERE group_id = ?", (group_id,)
            ).fetchone()
            if existing and not reset_activity:
                conn.execute(
                    "UPDATE groups SET group_name = ?, initial_balance = ? WHERE group_id = ?",
                    (name, balance, group_id),
                )
            else:
                conn.execute(
                    """INSERT INTO groups(group_id, group_name, initial_balance, current_balance)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(group_id) DO UPDATE SET
                       group_name = excluded.group_name,
                       initial_balance = excluded.initial_balance,
                       current_balance = excluded.current_balance""",
                    (group_id, name, balance, balance),
                )

        for row in products_df.itertuples(index=False):
            product_id = int(row.product_id)
            name = str(row.product_name).strip()
            if not name or name == "nan":
                raise ValueError(f"Nome vazio para o produto {product_id}.")
            price = float(row.unit_price)
            stock = int(row.initial_stock)
            existing = conn.execute(
                "SELECT product_id FROM products WHERE product_id = ?", (product_id,)
            ).fetchone()
            if existing and not reset_activity:
                conn.execute(
                    "UPDATE products SET product_name = ?, price = ? WHERE product_id = ?",
                    (name, price, product_id),
                )
            else:
                conn.execute(
                    """INSERT INTO products(product_id, product_name, price, stock, initial_stock)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(product_id) DO UPDATE SET
                       product_name = excluded.product_name,
                       price = excluded.price,
                       stock = excluded.stock,
                       initial_stock = excluded.initial_stock""",
                    (product_id, name, price, stock, stock),
                )

        conn.commit()
        return len(groups_df), len(products_df)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_admin_stock():
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            pr.product_id,
            pr.product_name,
            pr.price,
            pr.initial_stock,
            pr.stock AS final_stock,
            COALESCE(SUM(pi.quantity), 0) AS sold_units
        FROM products pr
        LEFT JOIN purchase_items pi ON pi.product_id = pr.product_id
        GROUP BY pr.product_id, pr.product_name, pr.price, pr.initial_stock, pr.stock
        ORDER BY pr.product_id
    """).fetchall()
    conn.close()
    return pd.DataFrame([
        {
            "Produto": row["product_name"],
            "Preço unitário": row["price"],
            "Estoque inicial": row["initial_stock"],
            "Estoque final": row["final_stock"],
            "Unidades vendidas": row["sold_units"],
            "Valor estoque inicial": row["initial_stock"] * row["price"],
            "Valor estoque final": row["final_stock"] * row["price"],
        }
        for row in rows
    ])


def get_admin_groups():
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            g.group_id,
            g.group_name,
            g.initial_balance,
            g.current_balance,
            COALESCE(COUNT(p.purchase_id), 0) AS purchases_count,
            COALESCE(SUM(p.total), 0) AS total_spent
        FROM groups g
        LEFT JOIN purchases p ON p.group_id = g.group_id
        GROUP BY g.group_id, g.group_name, g.initial_balance, g.current_balance
        ORDER BY g.group_id
    """).fetchall()
    conn.close()
    return pd.DataFrame([
        {
            "Grupo": row["group_name"],
            "Saldo inicial": row["initial_balance"],
            "Total comprado": row["total_spent"],
            "Saldo final": row["current_balance"],
            "Compras": row["purchases_count"],
        }
        for row in rows
    ])


def get_group_item_summary(group_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            pr.product_name,
            SUM(pi.quantity) AS quantity,
            SUM(pi.subtotal) AS total
        FROM purchase_items pi
        JOIN purchases p ON p.purchase_id = pi.purchase_id
        JOIN products pr ON pr.product_id = pi.product_id
        WHERE p.group_id = ?
        GROUP BY pr.product_id, pr.product_name
        ORDER BY total DESC
    """, (group_id,)).fetchall()
    conn.close()
    return pd.DataFrame([
        {"Produto": row["product_name"], "Quantidade": row["quantity"], "Total": row["total"]}
        for row in rows
    ])


def render_admin_screen():
    st.title("⚙️ Administração")
    st.caption("Visão consolidada do estoque, saldos e compras da atividade.")

    if not admin_login():
        return

    stock_df = get_admin_stock()
    groups_df = get_admin_groups()
    total_initial = stock_df["Valor estoque inicial"].sum() if not stock_df.empty else 0
    total_final = stock_df["Valor estoque final"].sum() if not stock_df.empty else 0
    total_spent = groups_df["Total comprado"].sum() if not groups_df.empty else 0
    total_purchases = groups_df["Compras"].sum() if not groups_df.empty else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Valor estoque inicial", money(total_initial))
    m2.metric("Valor estoque final", money(total_final))
    m3.metric("Total comprado", money(total_spent))
    m4.metric("Compras registradas", int(total_purchases))

    tab_stock, tab_groups, tab_items, tab_import = st.tabs([
        "📦 Estoque", "👥 Compras por grupo", "🧾 Itens por grupo", "📥 Importar Excel"
    ])

    with tab_stock:
        if stock_df.empty:
            st.info("Nenhum produto cadastrado.")
        else:
            display = stock_df.copy()
            for col in ["Preço unitário", "Valor estoque inicial", "Valor estoque final"]:
                display[col] = display[col].map(money)
            st.dataframe(display, use_container_width=True, hide_index=True)

    with tab_groups:
        if groups_df.empty:
            st.info("Nenhum grupo cadastrado.")
        else:
            display = groups_df.copy()
            for col in ["Saldo inicial", "Total comprado", "Saldo final"]:
                display[col] = display[col].map(money)
            st.dataframe(display, use_container_width=True, hide_index=True)

    with tab_items:
        if groups_df.empty:
            st.info("Nenhum grupo cadastrado.")
        else:
            group_options = {
                row["group_name"]: row["group_id"]
                for row in get_groups()
            }
            selected_name = st.selectbox("Selecione o grupo", list(group_options.keys()))
            items_df = get_group_item_summary(group_options[selected_name])
            if items_df.empty:
                st.info("Este grupo ainda não realizou compras.")
            else:
                items_df["Total"] = items_df["Total"].map(money)
                st.dataframe(items_df, use_container_width=True, hide_index=True)

    with tab_import:
        st.write("Use o arquivo **Mini_Market_Admin.xlsx**.")
        uploaded_workbook = st.file_uploader(
            "Selecione a planilha administrativa",
            type=["xlsx"],
            key="admin_workbook_main",
        )
        reset_activity = st.checkbox(
            "Aplicar saldo inicial e estoque da planilha",
            value=False,
            help="Marque somente na carga inicial ou em um reinício autorizado.",
            key="admin_reset_main",
        )
        if st.button(
            "⬆️ Validar e importar",
            type="primary",
            disabled=uploaded_workbook is None,
            key="admin_import_main",
        ):
            try:
                group_count, product_count = import_admin_workbook(
                    uploaded_workbook,
                    reset_activity=reset_activity,
                )
                st.success(
                    f"Importação concluída: {group_count} grupos e {product_count} produtos."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Importação não realizada: {exc}")


def purchase_email_body(purchase):
    lines = [
        "MINI MARKET – TEAM BUILDING",
        "",
        f"Compra: #{purchase['purchase_id']}",
        f"Grupo: {purchase['group_name']}",
        f"Data/Hora: {purchase['date_time']}",
        "",
        "ITENS COMPRADOS",
    ]

    for item in purchase["items"]:
        lines.append(
            f"- {item['quantity']}x {item['product_name']} | "
            f"Valor unitário: {money(item['unit_price'])} | "
            f"Subtotal: {money(item['subtotal'])}"
        )

    lines += [
        "",
        f"TOTAL DA COMPRA: {money(purchase['total'])}",
        f"SALDO ANTES: {money(purchase['balance_before'])}",
        f"SALDO RESTANTE: {money(purchase['balance_after'])}",
        "",
        "Registro gerado pelo Mini Market – Team Building.",
    ]

    return "\n".join(lines)


# -----------------------------
# START
# -----------------------------

init_db()

if not st.session_state.get("initialized"):
    # Só cria os dados de teste se o banco ainda estiver vazio.
    if len(get_groups()) == 0:
        seed_test_data()
    st.session_state.initialized = True

st.markdown("""
<style>
.mini-hero {
    padding: 16px 20px;
    border-radius: 16px;
    background: linear-gradient(135deg, #0b3152, #1261a0);
    color: white;
    margin-bottom: 18px;
}
.mini-hero h1 { margin: 0; font-size: 30px; }
.mini-hero p { margin: 5px 0 0; opacity: .86; }
.product-figure {
    height: 70px;
    border-radius: 13px;
    display: grid;
    place-items: center;
    background: linear-gradient(135deg, #eef6fb, #f9fbfd);
    font-size: 42px;
    margin-bottom: 8px;
}
.section-note { color: #667585; font-size: 13px; }
</style>
<div class="mini-hero">
  <h1>🛒 Mini Market</h1>
  <p>Team Building · Resource &amp; Cost Challenge</p>
</div>
""", unsafe_allow_html=True)

with st.expander("📱 Acesso pelo celular", expanded=True):
    url = access_url()
    qr_col, info_col = st.columns([1, 2])
    with qr_col:
        st.image(qr_bytes(url), width=180)
    with info_col:
        st.write("**Escaneie o QR Code para abrir o Mini Market.**")
        st.code(url, language=None)
        st.caption(
            "O celular precisa estar na mesma rede Wi‑Fi da máquina que está executando o Streamlit."
        )

with st.sidebar:
    app_mode = st.radio(
        "Modo de acesso",
        ["🛒 Compras", "⚙️ Administração"],
        index=0,
    )

if app_mode == "⚙️ Administração":
    render_admin_screen()
    st.stop()

# -----------------------------
# TOP DASHBOARD
# -----------------------------

st.subheader("💰 Contas dos grupos")

groups = get_groups()

cols = st.columns(len(groups) if groups else 1)

for col, group in zip(cols, groups):
    with col:
        st.metric(
            group["group_name"],
            money(group["current_balance"]),
            delta=money(group["current_balance"] - group["initial_balance"]),
        )

st.divider()

# -----------------------------
# SHOPPING AREA
# -----------------------------

left, right = st.columns([1.5, 1])

with left:
    st.subheader("1. Identifique o grupo")

    if not groups:
        st.error("Nenhum grupo cadastrado.")
        st.stop()

    group_options = {
        g["group_name"]: g["group_id"]
        for g in groups
    }

    if "cart" not in st.session_state:
        st.session_state.cart = {}

    group_by_id = {g["group_id"]: g for g in groups}

    if st.session_state.get("locked_group_id") not in group_by_id:
        selected_group_name = st.selectbox(
            "Selecione o grupo no primeiro acesso",
            list(group_options.keys()),
            key="group_login_select",
        )
        if st.button("🔐 Confirmar meu grupo", type="primary", key="lock_group"):
            st.session_state.locked_group_id = group_options[selected_group_name]
            st.session_state.cart = {}
            st.rerun()
        st.info("Depois da confirmação, o grupo ficará fixo nesta sessão do navegador.")
        st.stop()

    selected_group_id = st.session_state.locked_group_id
    selected_group = group_by_id[selected_group_id]
    st.success(f"Grupo fixado nesta sessão: **{selected_group['group_name']}**")
    if st.button("↩️ Sair e trocar de grupo", key="unlock_group"):
        st.session_state.pop("locked_group_id", None)
        st.session_state.cart = {}
        st.rerun()

    st.info(
        f"Saldo inicial: **{money(selected_group['initial_balance'])}**  \n"
        f"Saldo atual: **{money(selected_group['current_balance'])}**"
    )

    st.subheader("2. Escolha os produtos")

    products = get_products()

    product_cols = st.columns(3)

    for i, product in enumerate(products):
        with product_cols[i % 3]:
            with st.container(border=True):
                st.markdown(
                    f'<div class="product-figure">{product_icon(product["product_name"])}</div>',
                    unsafe_allow_html=True,
                )
                st.write(f"### {product['product_name']}")
                st.write(f"**{money(product['price'])}**")
                st.caption(f"Estoque: {product['stock']}")

                if product["stock"] > 0:
                    if st.button(
                        "Adicionar",
                        key=f"add_{product['product_id']}",
                        use_container_width=True,
                    ):
                        current = st.session_state.cart.get(
                            product["product_id"], 0
                        )

                        if current < product["stock"]:
                            st.session_state.cart[product["product_id"]] = current + 1
                            st.rerun()
                else:
                    st.warning("Sem estoque")

with right:
    st.subheader("🛍️ Carrinho")

    cart_rows = []
    total = 0

    for product_id, quantity in st.session_state.cart.items():
        product = next(
            (p for p in products if p["product_id"] == product_id),
            None
        )

        if product:
            subtotal = product["price"] * quantity
            total += subtotal

            cart_rows.append({
                "Produto": product["product_name"],
                "Qtd": quantity,
                "Unitário": money(product["price"]),
                "Subtotal": money(subtotal),
            })

    if cart_rows:
        st.dataframe(
            pd.DataFrame(cart_rows),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown(f"### Total: {money(total)}")

        if total > selected_group["current_balance"]:
            st.error("Saldo insuficiente.")
        else:
            st.success(
                f"Saldo após compra: "
                f"{money(selected_group['current_balance'] - total)}"
            )

        b1, b2 = st.columns(2)

        with b1:
            if st.button(
                "🗑️ Limpar",
                use_container_width=True
            ):
                st.session_state.cart = {}
                st.rerun()

        with b2:
            if st.button(
                "💳 CONFIRMAR",
                type="primary",
                use_container_width=True,
                disabled=total > selected_group["current_balance"],
            ):
                cart_for_db = [
                    {
                        "product_id": product_id,
                        "quantity": quantity,
                    }
                    for product_id, quantity
                    in st.session_state.cart.items()
                ]

                try:
                    purchase = execute_purchase(
                        selected_group_id,
                        cart_for_db,
                    )

                    st.session_state.cart = {}
                    st.session_state.last_purchase = purchase

                    st.success(
                        f"Compra #{purchase['purchase_id']} aprovada! "
                        f"Total: {money(purchase['total'])}"
                    )

                    st.rerun()

                except Exception as exc:
                    st.error(str(exc))

    else:
        st.info(
            "Seu carrinho está vazio.\n\n"
            "Selecione os produtos ao lado."
        )

# -----------------------------
# HISTORY
# -----------------------------

st.divider()
st.subheader("📋 Histórico de compras")

history = get_purchase_history()

if history:
    for purchase in history:
        with st.expander(
            f"#{purchase['purchase_id']} • "
            f"{purchase['group_name']} • "
            f"{money(purchase['total'])} • "
            f"{purchase['date_time']}"
        ):
            items = get_purchase_items(purchase["purchase_id"])

            for item in items:
                st.write(
                    f"{item['quantity']}x {item['product_name']} — "
                    f"{money(item['subtotal'])}"
                )

            st.write(
                f"Saldo: {money(purchase['balance_before'])} → "
                f"**{money(purchase['balance_after'])}**"
            )

            body = (
                f"MINI MARKET – TEAM BUILDING\n\n"
                f"Compra: #{purchase['purchase_id']}\n"
                f"Grupo: {purchase['group_name']}\n"
                f"Data/Hora: {purchase['date_time']}\n\n"
            )

            for item in items:
                body += (
                    f"- {item['quantity']}x {item['product_name']} | "
                    f"{money(item['unit_price'])} | "
                    f"{money(item['subtotal'])}\n"
                )

            body += (
                f"\nTOTAL: {money(purchase['total'])}\n"
                f"SALDO RESTANTE: {money(purchase['balance_after'])}"
            )

            st.download_button(
                "✉️ Gerar texto do e-mail",
                data=body,
                file_name=f"compra_{purchase['purchase_id']}.txt",
                key=f"email_{purchase['purchase_id']}",
            )
else:
    st.info("Nenhuma compra realizada.")

with st.sidebar:
    st.caption("Use o seletor acima para alternar entre Compras e Administração.")
