"""
app.py
Interface do sistema de estoque, feita em Streamlit.

Rodar com: streamlit run app.py
"""

import datetime
import pandas as pd
import streamlit as st

import database
import crud

database.criar_tabelas()  # garante que as tabelas existem ao abrir o app

st.set_page_config(page_title="Estoque do Restaurante", layout="wide")
st.title("📦 Controle de Estoque")

pagina = st.sidebar.radio(
    "Menu",
    [
        "Painel de Estoque",
        "Cadastrar Insumo",
        "Cadastrar Prato",
        "Ficha Técnica",
        "Lançar Compra",
        "Lançar Venda do Dia",
        "Contagem Física Mensal",
    ],
    key="menu_principal",
)


def listar_insumos():
    conn = database.get_connection()
    dados = conn.execute("SELECT nome FROM insumos ORDER BY nome").fetchall()
    conn.close()
    return [d["nome"] for d in dados]


def listar_pratos():
    conn = database.get_connection()
    dados = conn.execute("SELECT nome FROM pratos ORDER BY nome").fetchall()
    conn.close()
    return [d["nome"] for d in dados]


# ---------- Painel de Estoque ----------
if pagina == "Painel de Estoque":
    st.subheader("Estoque teórico atual")
    st.caption(
        "Calculado automaticamente a partir de compras e vendas, "
        "sem precisar de contagem física toda semana."
    )

    insumos = listar_insumos()
    if not insumos:
        st.info("Nenhum insumo cadastrado ainda. Vá em 'Cadastrar Insumo'.")
    else:
        dados = crud.calcular_estoque_todos_insumos()
        df = pd.DataFrame(dados)
        df = df.rename(columns={
            "insumo": "Insumo",
            "unidade_medida": "Unidade",
            "estoque_minimo": "Estoque mínimo",
            "estoque_atual": "Estoque atual",
            "abaixo_do_minimo": "Abaixo do mínimo?",
            "baseline_usada": "Última contagem usada como base",
        })

        def destacar_baixo(row):
            cor = "background-color: #ffcccc" if row["Abaixo do mínimo?"] else ""
            return [cor] * len(row)

        estilo = df.style.apply(destacar_baixo, axis=1).format(
            {"Estoque atual": "{:.1f}", "Estoque mínimo": "{:.1f}"}
        )
        st.dataframe(estilo, use_container_width=True)

        alertas = df[df["Abaixo do mínimo?"]]
        if not alertas.empty:
            st.warning(f"⚠️ {len(alertas)} insumo(s) abaixo do estoque mínimo!")


# ---------- Cadastrar Insumo ----------
elif pagina == "Cadastrar Insumo":
    st.subheader("Cadastrar novo insumo")
    with st.form("form_insumo"):
        nome = st.text_input("Nome do insumo")
        unidade = st.selectbox("Unidade de medida", ["kg", "g", "l", "ml", "un"])
        minimo = st.number_input("Estoque mínimo", min_value=0.0, step=0.5)
        enviado = st.form_submit_button("Cadastrar")

    if enviado:
        if nome:
            try:
                crud.cadastrar_insumo(nome, unidade, minimo)
                st.success(f"Insumo '{nome}' cadastrado!")
            except Exception as e:
                st.error(f"Erro: {e}")
        else:
            st.error("Informe o nome do insumo.")


# ---------- Cadastrar Prato ----------
elif pagina == "Cadastrar Prato":
    st.subheader("Cadastrar novo prato")
    with st.form("form_prato"):
        nome = st.text_input("Nome do prato")
        enviado = st.form_submit_button("Cadastrar")

    if enviado:
        if nome:
            try:
                crud.cadastrar_prato(nome)
                st.success(f"Prato '{nome}' cadastrado!")
            except Exception as e:
                st.error(f"Erro: {e}")
        else:
            st.error("Informe o nome do prato.")


# ---------- Ficha Técnica ----------
elif pagina == "Ficha Técnica":
    st.subheader("Definir ficha técnica (receita)")
    st.caption("Quanto de cada insumo é gasto para preparar 1 unidade do prato.")

    pratos = listar_pratos()
    insumos = listar_insumos()

    if not pratos or not insumos:
        st.info("Cadastre ao menos um prato e um insumo antes de continuar.")
    else:
        with st.form("form_ficha"):
            prato = st.selectbox("Prato", pratos)
            insumo = st.selectbox("Insumo", insumos)
            quantidade = st.number_input("Quantidade usada por prato", min_value=0.0, step=0.01)
            enviado = st.form_submit_button("Salvar")

        if enviado:
            try:
                crud.definir_ficha_tecnica(prato, insumo, quantidade)
                st.success(f"Ficha técnica salva: {prato} usa {quantidade} de {insumo}.")
            except Exception as e:
                st.error(f"Erro: {e}")


# ---------- Lançar Compra ----------
elif pagina == "Lançar Compra":
    st.subheader("Registrar compra (entrada de estoque)")

    insumos = listar_insumos()
    if not insumos:
        st.info("Cadastre um insumo antes de lançar compras.")
    else:
        with st.form("form_compra"):
            insumo = st.selectbox("Insumo", insumos)
            quantidade = st.number_input("Quantidade comprada", min_value=0.0, step=0.5)
            data = st.date_input("Data da compra", value=datetime.date.today())
            fornecedor = st.text_input("Fornecedor (opcional)")
            enviado = st.form_submit_button("Registrar")

        if enviado:
            try:
                crud.registrar_compra(insumo, quantidade, str(data), fornecedor or None)
                st.success("Compra registrada!")
            except Exception as e:
                st.error(f"Erro: {e}")


# ---------- Lançar Venda do Dia ----------
elif pagina == "Lançar Venda do Dia":
    st.subheader("Registrar vendas do dia")
    st.caption("Digite quantos de cada prato foram vendidos hoje, olhando o resumo do PDV.")

    pratos = listar_pratos()
    if not pratos:
        st.info("Cadastre um prato antes de lançar vendas.")
    else:
        with st.form("form_venda"):
            prato = st.selectbox("Prato", pratos)
            quantidade = st.number_input("Quantidade vendida", min_value=0, step=1)
            data = st.date_input("Data da venda", value=datetime.date.today())
            enviado = st.form_submit_button("Registrar")

        if enviado:
            try:
                crud.registrar_venda_diaria(prato, quantidade, str(data))
                st.success("Venda registrada!")
            except Exception as e:
                st.error(f"Erro: {e}")


# ---------- Contagem Física Mensal ----------
elif pagina == "Contagem Física Mensal":
    st.subheader("Registrar contagem física")
    st.caption("Use isso 1x por mês para reconciliar o estoque teórico com o real.")

    insumos = listar_insumos()
    if not insumos:
        st.info("Cadastre um insumo antes de registrar contagem.")
    else:
        with st.form("form_contagem"):
            insumo = st.selectbox("Insumo", insumos)
            quantidade = st.number_input("Quantidade contada fisicamente", min_value=0.0, step=0.5)
            data = st.date_input("Data da contagem", value=datetime.date.today())
            observacao = st.text_input("Observação (opcional)")
            enviado = st.form_submit_button("Registrar")

        if enviado:
            try:
                crud.registrar_contagem_fisica(insumo, quantidade, str(data), observacao or None)
                st.success("Contagem registrada! Ela vira a nova base do cálculo automático.")
            except Exception as e:
                st.error(f"Erro: {e}")
