
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
        stock INTEGER NOT NULL DEFAULT 0
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
            INSERT INTO products(product_id, product_name, price, stock)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                product_name = excluded.product_name,
                price = excluded.price,
                stock = excluded.stock
        """, (product_id, name, price, stock))

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
                    """INSERT INTO products(product_id, product_name, price, stock)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(product_id) DO UPDATE SET
                       product_name = excluded.product_name,
                       price = excluded.price,
                       stock = excluded.stock""",
                    (product_id, name, price, stock),
                )

        conn.commit()
        return len(groups_df), len(products_df)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
  <p>Team Building · operação local preparada para SQLite</p>
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

    selected_group_name = st.selectbox(
        "Grupo",
        list(group_options.keys())
    )

    selected_group_id = group_options[selected_group_name]

    selected_group = next(
        g for g in groups if g["group_id"] == selected_group_id
    )

    st.info(
        f"Saldo inicial: **{money(selected_group['initial_balance'])}**  \n"
        f"Saldo atual: **{money(selected_group['current_balance'])}**"
    )

    st.subheader("2. Escolha os produtos")

    products = get_products()

    if "cart" not in st.session_state:
        st.session_state.cart = {}

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

# -----------------------------
# ADMIN
# -----------------------------

with st.sidebar:
    st.header("⚙️ Administração")

    st.caption(
        "Os dados operacionais são mantidos no SQLite. A planilha administrativa "
        "pode atualizar os cadastros sem apagar o histórico."
    )

    if st.button("🔄 Atualizar tela", use_container_width=True):
        st.rerun()

    with st.expander("📥 Importar planilha administrativa"):
        st.caption(
            "Use o arquivo Mini_Market_Admin.xlsx. Os cabeçalhos devem permanecer "
            "nas abas Grupos e Produtos."
        )
        uploaded_workbook = st.file_uploader(
            "Selecione o Excel",
            type=["xlsx"],
            key="admin_workbook",
        )
        reset_activity = st.checkbox(
            "Aplicar saldo inicial e estoque da planilha",
            value=False,
            help=(
                "Marque somente para uma carga inicial ou reinício autorizado. "
                "Se desmarcado, saldos, estoque atual e histórico são preservados."
            ),
        )
        if st.button(
            "⬆️ Validar e importar",
            use_container_width=True,
            disabled=uploaded_workbook is None,
        ):
            try:
                group_count, product_count = import_admin_workbook(
                    uploaded_workbook,
                    reset_activity=reset_activity,
                )
                st.success(
                    f"Importação concluída: {group_count} grupos e "
                    f"{product_count} produtos."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Importação não realizada: {exc}")

    if st.button(
        "⚠️ Restaurar dados de teste",
        use_container_width=True
    ):
        conn = get_conn()
        conn.execute("DELETE FROM purchase_items")
        conn.execute("DELETE FROM purchases")
        conn.execute("DELETE FROM groups")
        conn.execute("DELETE FROM products")
        conn.commit()
        conn.close()

        seed_test_data()
        st.session_state.cart = {}
        st.rerun()

    st.divider()

    st.subheader("📊 Estoque atual")

    products_admin = get_products()

    st.dataframe(
        pd.DataFrame([
            {
                "Produto": p["product_name"],
                "Preço": money(p["price"]),
                "Estoque": p["stock"],
            }
            for p in products_admin
        ]),
        use_container_width=True,
        hide_index=True,
    )
