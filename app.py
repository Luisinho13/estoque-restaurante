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
import nfe_import

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
        "Importar Nota Fiscal",
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

    st.divider()
    st.subheader("Excluir insumo")
    st.caption(
        "⚠️ Isso apaga o insumo e todo o histórico ligado a ele "
        "(ficha técnica, compras e contagens). Não tem como desfazer."
    )

    insumos_existentes = listar_insumos()
    if not insumos_existentes:
        st.info("Nenhum insumo cadastrado ainda.")
    else:
        insumo_excluir = st.selectbox("Selecione o insumo para excluir", insumos_existentes)
        confirmar = st.checkbox(f"Confirmo que quero excluir '{insumo_excluir}' permanentemente")
        if st.button("Excluir insumo", type="primary", disabled=not confirmar):
            try:
                crud.excluir_insumo(insumo_excluir)
                st.success(f"Insumo '{insumo_excluir}' excluído.")
                st.rerun()
            except Exception as e:
                st.error(f"Erro: {e}")


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


# ---------- Importar Nota Fiscal ----------
elif pagina == "Importar Nota Fiscal":
    st.subheader("Importar compra a partir de uma NF-e (XML)")
    st.caption(
        "Envie o arquivo XML da nota fiscal. Produtos já mapeados são "
        "lançados automaticamente; produtos novos você mapeia uma vez aqui, "
        "e da próxima vez que aparecerem numa nota já são reconhecidos sozinhos."
    )

    arquivo = st.file_uploader("Arquivo XML da NF-e", type=["xml"])

    if arquivo is not None:
        try:
            dados = nfe_import.extrair_dados_nfe(arquivo)
            st.session_state["nfe_dados"] = dados
        except Exception as e:
            st.error(f"Não consegui ler esse XML: {e}")
            st.session_state.pop("nfe_dados", None)

    dados = st.session_state.get("nfe_dados")

    if dados:
        st.info(
            f"Nota nº {dados['numero_nota']} — {dados['fornecedor_nome']} "
            f"— emitida em {dados['data_emissao']} — {len(dados['itens'])} item(ns)"
        )

        insumos = listar_insumos()
        itens_sem_mapa = []
        for item in dados["itens"]:
            mapeamento = crud.buscar_mapeamento_nfe(dados["fornecedor_cnpj"], item["codigo_produto"])
            if mapeamento:
                st.write(
                    f"✅ **{item['descricao']}** → já mapeado para "
                    f"*{mapeamento['insumo_nome']}* "
                    f"({item['quantidade']} × fator {mapeamento['fator_conversao']} = "
                    f"{item['quantidade'] * mapeamento['fator_conversao']:.2f})"
                )
            else:
                itens_sem_mapa.append(item)

        if itens_sem_mapa:
            st.warning(f"{len(itens_sem_mapa)} item(ns) ainda não mapeado(s). Mapeie abaixo:")
            if not insumos:
                st.error("Cadastre ao menos um insumo antes de mapear produtos da nota.")
            else:
                for item in itens_sem_mapa:
                    with st.form(f"mapa_{item['codigo_produto']}"):
                        st.write(
                            f"**{item['descricao']}** "
                            f"(código {item['codigo_produto']}, "
                            f"{item['quantidade']} {item['unidade']} na nota)"
                        )
                        insumo_escolhido = st.selectbox(
                            "Qual insumo isso representa?", insumos,
                            key=f"sel_{item['codigo_produto']}",
                        )
                        fator = st.number_input(
                            "Fator de conversão (nota → unidade do insumo). "
                            "Deixe 1 se a unidade já bate.",
                            min_value=0.0001, value=1.0, step=0.1,
                            key=f"fator_{item['codigo_produto']}",
                        )
                        mapear = st.form_submit_button("Salvar mapeamento")

                    if mapear:
                        crud.mapear_produto_nfe(
                            dados["fornecedor_cnpj"], item["codigo_produto"],
                            item["descricao"], insumo_escolhido, fator,
                        )
                        st.success(f"'{item['descricao']}' mapeado para '{insumo_escolhido}'!")
                        st.rerun()
        else:
            st.success("Todos os itens da nota já estão mapeados!")

        st.divider()
        if st.button("📥 Lançar compras desta nota no estoque", type="primary"):
            lancados, nao_mapeados = nfe_import.processar_itens_nfe(dados, dados["fornecedor_cnpj"])
            if lancados:
                st.success(f"{len(lancados)} compra(s) lançada(s) no estoque!")
                for descricao, insumo_nome, qtd in lancados:
                    st.write(f"- {descricao} → {insumo_nome}: +{qtd:.2f}")
            if nao_mapeados:
                st.warning(
                    f"{len(nao_mapeados)} item(ns) ainda sem mapeamento não foram lançados. "
                    "Mapeie-os acima e clique de novo."
                )
            st.session_state.pop("nfe_dados", None)
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
