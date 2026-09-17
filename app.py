"""
app.py
Interface do sistema de estoque, feita em Streamlit.

Rodar com: streamlit run app.py
"""

import datetime

import altair as alt
import pandas as pd
import streamlit as st

import database
import crud
import nfe_import
import zig_import

database.criar_tabelas()  # garante que as tabelas existem ao abrir o app

st.set_page_config(
    page_title="Estoque do Restaurante",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

COR = "#2E7D6F"
COR_ALERTA = "#C1443F"


# ---------- Helpers de consulta ----------

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


def unidades_dos_insumos():
    """Retorna um dicionário {nome do insumo: unidade de medida}."""
    conn = database.get_connection()
    dados = conn.execute("SELECT nome, unidade_medida FROM insumos").fetchall()
    conn.close()
    return {d["nome"]: d["unidade_medida"] for d in dados}


# ---------- Dashboard ----------

def _grafico_consumo(dias: int):
    consumo = crud.consumo_por_insumo(dias)
    if not consumo:
        st.info("Sem consumo no período — lance vendas para ver este gráfico.")
        return

    # Comparar kg com "un" na mesma barra não diz nada, então o gráfico
    # mostra uma unidade por vez.
    unidades = sorted({c["unidade_medida"] for c in consumo})
    unidade = unidades[0]
    if len(unidades) > 1:
        padrao = max(unidades, key=lambda u: sum(1 for c in consumo if c["unidade_medida"] == u))
        unidade = st.segmented_control(
            "Unidade", unidades, default=padrao, key="consumo_unidade"
        ) or padrao

    df = pd.DataFrame([c for c in consumo if c["unidade_medida"] == unidade][:8])
    grafico = (
        alt.Chart(df)
        .mark_bar(color=COR, cornerRadiusEnd=4)
        .encode(
            x=alt.X("consumo:Q", title=f"Consumo no período ({unidade})"),
            y=alt.Y("insumo:N", sort="-x", title=None),
            tooltip=[
                alt.Tooltip("insumo:N", title="Insumo"),
                alt.Tooltip("consumo:Q", title="Consumo", format=".2f"),
                alt.Tooltip("unidade_medida:N", title="Unidade"),
            ],
        )
        .properties(height=max(180, 34 * len(df)))
    )
    st.altair_chart(grafico, width="stretch")


def _grafico_vendas(dias: int):
    vendas = crud.vendas_por_dia(dias)
    if not vendas:
        st.info("Sem vendas lançadas no período.")
        return

    df = pd.DataFrame(vendas)
    df["data"] = pd.to_datetime(df["data"])
    grafico = (
        alt.Chart(df)
        .mark_area(
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color=COR, offset=0),
                    alt.GradientStop(color="rgba(46,125,111,0.05)", offset=1),
                ],
                x1=1, x2=1, y1=1, y2=0,
            ),
            line={"color": COR, "strokeWidth": 2},
            point={"color": COR, "size": 40},
        )
        .encode(
            x=alt.X("data:T", title=None),
            y=alt.Y("pratos_vendidos:Q", title="Pratos vendidos"),
            tooltip=[
                alt.Tooltip("data:T", title="Data", format="%d/%m/%Y"),
                alt.Tooltip("pratos_vendidos:Q", title="Pratos"),
            ],
        )
        .properties(height=280)
    )
    st.altair_chart(grafico, width="stretch")


def _tabela_cobertura(dias: int):
    cobertura = crud.cobertura_estoque(dias)
    if not cobertura:
        return

    df = pd.DataFrame(cobertura)
    # Insumo sem consumo no período não tem previsão de fim: vai pro fim da lista.
    df["_ordem"] = df["dias_restantes"].fillna(10**6)
    df = df.sort_values("_ordem")

    def status(linha):
        if linha["estoque_atual"] < 0:
            return "🔴 Negativo"
        if linha["abaixo_do_minimo"]:
            return "🟠 Abaixo do mínimo"
        if linha["dias_restantes"] is not None and linha["dias_restantes"] <= 7:
            return "🟡 Acaba em breve"
        return "🟢 Ok"

    df["Status"] = df.apply(status, axis=1)
    visivel = df[[
        "insumo", "estoque_atual", "unidade_medida", "estoque_minimo",
        "consumo_medio_diario", "dias_restantes", "Status",
    ]].rename(columns={
        "insumo": "Insumo",
        "estoque_atual": "Estoque atual",
        "unidade_medida": "Un.",
        "estoque_minimo": "Mínimo",
        "consumo_medio_diario": "Consumo/dia",
        "dias_restantes": "Dias de estoque",
    })

    st.dataframe(
        visivel,
        width="stretch",
        hide_index=True,
        column_config={
            "Estoque atual": st.column_config.NumberColumn(format="%.1f"),
            "Mínimo": st.column_config.NumberColumn(format="%.1f"),
            "Consumo/dia": st.column_config.NumberColumn(format="%.2f"),
            "Dias de estoque": st.column_config.NumberColumn(
                format="%.1f d", help="Estoque atual ÷ consumo médio diário do período"
            ),
        },
    )


def pagina_dashboard():
    st.title("📦 Controle de Estoque")
    st.caption(
        "Estoque teórico calculado automaticamente a partir de compras e vendas — "
        "a contagem física só é necessária 1x por mês."
    )

    insumos = listar_insumos()
    if not insumos:
        st.info("Nenhum insumo cadastrado ainda. Comece por aqui:")
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🥬 Cadastrar insumo", width="stretch", type="primary"):
                st.switch_page(PG_INSUMOS)
        with col2:
            if st.button("🍽️ Cadastrar prato", width="stretch"):
                st.switch_page(PG_PRATOS)
        with col3:
            if st.button("📋 Montar ficha técnica", width="stretch"):
                st.switch_page(PG_FICHA)
        return

    dias = st.segmented_control(
        "Período de análise",
        options=[7, 30, 90],
        format_func=lambda d: f"Últimos {d} dias",
        default=30,
        key="dashboard_periodo",
    ) or 30

    resumo = crud.resumo_dashboard(dias)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Insumos", resumo["total_insumos"], border=True)
    col2.metric(
        "Abaixo do mínimo",
        resumo["abaixo_do_minimo"],
        delta="tudo ok" if resumo["abaixo_do_minimo"] == 0 else "repor",
        delta_color="normal" if resumo["abaixo_do_minimo"] == 0 else "inverse",
        border=True,
    )
    col3.metric("Pratos vendidos", int(resumo["pratos_vendidos"]), border=True)
    col4.metric("Compras lançadas", resumo["compras_lancadas"], border=True)
    col5.metric(
        "Última contagem",
        "nunca" if resumo["dias_sem_contagem"] is None else f"{resumo['dias_sem_contagem']} d",
        help="Dias desde a contagem física mais recente. O ideal é reconciliar 1x por mês.",
        border=True,
    )

    if resumo["estoque_negativo"]:
        st.error(
            f"{resumo['estoque_negativo']} insumo(s) com estoque negativo. "
            "Isso costuma significar compra não lançada ou ficha técnica errada."
        )
    if resumo["dias_sem_contagem"] is not None and resumo["dias_sem_contagem"] > 35:
        st.warning(
            f"A última contagem física foi há {resumo['dias_sem_contagem']} dias. "
            "Vale reconciliar o estoque."
        )

    st.divider()

    esquerda, direita = st.columns([1, 1])
    with esquerda:
        st.subheader("Insumos mais consumidos")
        _grafico_consumo(dias)
    with direita:
        st.subheader("Vendas por dia")
        _grafico_vendas(dias)

    st.divider()
    st.subheader("O que acaba primeiro")
    st.caption(
        "Ordenado pelo tempo que o estoque ainda dura, usando o consumo médio do período."
    )
    _tabela_cobertura(dias)

    st.divider()
    col_pratos, col_mov = st.columns([1, 2])

    with col_pratos:
        st.subheader("Pratos mais vendidos")
        top = crud.top_pratos(dias)
        if top:
            st.dataframe(
                pd.DataFrame(top).rename(columns={"prato": "Prato", "vendidos": "Vendidos"}),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("Sem vendas no período.")

    with col_mov:
        st.subheader("Movimentações recentes")
        movimentacoes = crud.movimentacoes_recentes()
        if movimentacoes:
            df = pd.DataFrame(movimentacoes)
            df["data"] = pd.to_datetime(df["data"]).dt.strftime("%d/%m/%Y")
            st.dataframe(
                df.rename(columns={
                    "data": "Data",
                    "tipo": "Tipo",
                    "item": "Item",
                    "quantidade": "Qtd.",
                    "unidade": "Un.",
                    "detalhe": "Detalhe",
                }),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("Nenhum lançamento registrado ainda.")


# ---------- Painel de Estoque ----------

def pagina_painel():
    st.title("📊 Painel de Estoque")
    st.caption(
        "Estoque teórico atual de cada insumo, calculado a partir de compras e vendas."
    )

    insumos = listar_insumos()
    if not insumos:
        st.info("Nenhum insumo cadastrado ainda. Vá em 'Insumos'.")
        return

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
    st.dataframe(estilo, width="stretch")

    alertas = df[df["Abaixo do mínimo?"]]
    if not alertas.empty:
        st.warning(f"⚠️ {len(alertas)} insumo(s) abaixo do estoque mínimo!")

    st.divider()
    st.caption(
        "Excluir um insumo diretamente daqui apaga também ficha técnica, "
        "compras e contagens físicas ligadas a ele. Não tem como desfazer."
    )

    for item in dados:
        nome = item["insumo"]
        col1, col2, col3, col4 = st.columns([4, 2, 2, 1])
        with col1:
            st.write(f"**{nome}**")
        with col2:
            st.write(f"{item['estoque_atual']:.1f}")
        with col3:
            st.write(item["unidade_medida"])
        with col4:
            if st.button("🗑️", key=f"painel_del_{nome}", help=f"Excluir {nome}"):
                st.session_state["painel_excluir_pendente"] = nome
                st.rerun()

    pendente = st.session_state.get("painel_excluir_pendente")
    if pendente:
        st.warning(
            f"⚠️ Excluir **{pendente}** apaga também ficha técnica, compras "
            f"e contagens físicas ligadas a ele. Não tem como desfazer."
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button(f"Sim, excluir '{pendente}' definitivamente", type="primary"):
                crud.excluir_insumo(pendente)
                st.success(f"Insumo '{pendente}' excluído.")
                del st.session_state["painel_excluir_pendente"]
                st.rerun()
        with col2:
            if st.button("Cancelar"):
                del st.session_state["painel_excluir_pendente"]
                st.rerun()


# ---------- Cadastrar Insumo ----------

def pagina_insumos():
    st.title("🥬 Insumos")
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
        return

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

def pagina_pratos():
    st.title("🍽️ Pratos")
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

    st.divider()
    st.subheader("Excluir prato")
    st.caption(
        "⚠️ Isso apaga o prato e todo o histórico ligado a ele "
        "(ficha técnica e vendas diárias). Não tem como desfazer."
    )

    pratos_existentes = listar_pratos()
    if not pratos_existentes:
        st.info("Nenhum prato cadastrado ainda.")
        return

    prato_excluir = st.selectbox("Selecione o prato para excluir", pratos_existentes)
    confirmar_prato = st.checkbox(f"Confirmo que quero excluir '{prato_excluir}' permanentemente")
    if st.button("Excluir prato", type="primary", disabled=not confirmar_prato):
        try:
            crud.excluir_prato(prato_excluir)
            st.success(f"Prato '{prato_excluir}' excluído.")
            st.rerun()
        except Exception as e:
            st.error(f"Erro: {e}")


# ---------- Ficha Técnica ----------

def pagina_ficha_tecnica():
    st.title("📋 Ficha Técnica")
    st.caption("Quanto de cada insumo é gasto para preparar 1 unidade do prato.")

    pratos = listar_pratos()
    insumos = listar_insumos()

    if not pratos or not insumos:
        st.info("Cadastre ao menos um prato e um insumo antes de continuar.")
        return

    unidades = unidades_dos_insumos()

    prato = st.selectbox("Prato", pratos)
    num_insumos = st.number_input(
        "Quantos insumos essa ficha técnica usa?",
        min_value=1, max_value=10, value=1, step=1,
    )

    insumos_selecionados = [
        st.selectbox(f"Insumo {i + 1}", insumos, key=f"ficha_insumo_{i}")
        for i in range(int(num_insumos))
    ]

    with st.form("form_ficha"):
        linhas = []
        for i, insumo_i in enumerate(insumos_selecionados):
            quantidade_i = st.number_input(
                f"Quantidade de '{insumo_i}' usada por prato ({unidades[insumo_i]})",
                min_value=0.0, step=0.01, key=f"ficha_qtd_{i}",
            )
            linhas.append((insumo_i, quantidade_i))

        enviado = st.form_submit_button("Salvar")

    if enviado:
        nomes_usados = [nome for nome, _ in linhas]
        if len(set(nomes_usados)) != len(nomes_usados):
            st.error("Cada insumo só pode aparecer uma vez na ficha técnica do prato.")
        else:
            try:
                for insumo_i, quantidade_i in linhas:
                    crud.definir_ficha_tecnica(prato, insumo_i, quantidade_i)
                st.success(f"Ficha técnica de '{prato}' salva com {len(linhas)} insumo(s)!")
            except Exception as e:
                st.error(f"Erro: {e}")


# ---------- Lançar Compra ----------

def pagina_compra():
    st.title("🛒 Lançar Compra")
    st.caption("Registrar entrada de estoque.")

    insumos = listar_insumos()
    if not insumos:
        st.info("Cadastre um insumo antes de lançar compras.")
        return

    unidades = unidades_dos_insumos()
    insumo = st.selectbox("Insumo", insumos)

    with st.form("form_compra"):
        quantidade = st.number_input(
            f"Quantidade comprada ({unidades[insumo]})", min_value=0.0, step=0.5
        )
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

def pagina_nfe():
    st.title("🧾 Importar Nota Fiscal")
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
    if not dados:
        return

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


# ---------- Lançar Venda ----------

def pagina_venda():
    st.title("💰 Lançar Venda do Dia")
    st.caption("Digite quantos de cada prato foram vendidos hoje, olhando o resumo do PDV.")

    pratos = listar_pratos()
    if not pratos:
        st.info("Cadastre um prato antes de lançar vendas.")
        return

    with st.form("form_venda"):
        prato = st.selectbox("Prato", pratos)
        quantidade = st.number_input("Quantidade vendida", min_value=0, step=1)
        data = st.date_input("Data da venda", value=datetime.date.today())
        enviado = st.form_submit_button("Registrar")

    if enviado:
        try:
            ja_lancado = crud.total_vendido_no_dia(prato, str(data))
        except Exception as e:
            st.error(f"Erro: {e}")
            ja_lancado = None

        if ja_lancado:
            st.session_state["venda_pendente"] = {
                "prato": prato,
                "quantidade": quantidade,
                "data": str(data),
                "ja_lancado": ja_lancado,
            }
        elif ja_lancado == 0:
            crud.registrar_venda_diaria(prato, quantidade, str(data))
            st.success("Venda registrada!")

    pendente = st.session_state.get("venda_pendente")
    if pendente:
        st.warning(
            f"Já existe(m) {pendente['ja_lancado']:.0f} unidade(s) de "
            f"**{pendente['prato']}** lançada(s) em {pendente['data']}. "
            f"Isso pode ser um lançamento duplicado (ex: clique duplo no botão). "
            f"Confirma que quer somar mais {pendente['quantidade']:.0f}?"
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Sim, somar mesmo assim"):
                crud.registrar_venda_diaria(
                    pendente["prato"], pendente["quantidade"], pendente["data"]
                )
                st.success("Venda registrada!")
                del st.session_state["venda_pendente"]
                st.rerun()
        with col2:
            if st.button("Cancelar"):
                del st.session_state["venda_pendente"]
                st.rerun()


# ---------- Importar Vendas do PDV (Zig) ----------

NAO_CONTROLAR = "— não controlar no estoque —"


def _mapeamentos_salvos(pratos):
    """Permite revisar, trocar o prato ou remover um mapeamento já salvo."""
    mapeamentos = crud.listar_mapeamentos_zig()
    if not mapeamentos:
        return

    with st.expander(f"Mapeamentos salvos ({len(mapeamentos)})"):
        st.caption(
            "Troque o prato de um produto, marque como não controlado, ou remova o "
            "mapeamento para que ele volte a aparecer como pendente na próxima importação."
        )
        antes = pd.DataFrame([
            {
                "SKU": m["sku"],
                "Produto na Zig": m["nome_produto"],
                "Prato no sistema": (
                    NAO_CONTROLAR if m["ignorar"] or not m["prato_nome"] else m["prato_nome"]
                ),
                "Remover": False,
            }
            for m in mapeamentos
        ])
        depois = st.data_editor(
            antes,
            hide_index=True,
            width="stretch",
            key="zig_mapeamentos",
            disabled=["SKU", "Produto na Zig"],
            column_config={
                "Prato no sistema": st.column_config.SelectboxColumn(
                    options=pratos + [NAO_CONTROLAR]
                ),
                "Remover": st.column_config.CheckboxColumn(
                    help="Apaga o mapeamento deste produto"
                ),
            },
        )

        if st.button("Salvar alterações", key="zig_salvar_mapeamentos"):
            alterados = 0
            removidos = 0
            for (_, linha_antes), (_, linha_depois) in zip(antes.iterrows(), depois.iterrows()):
                escolha = linha_depois["Prato no sistema"]
                if linha_depois["Remover"]:
                    crud.remover_mapeamento_zig(linha_antes["SKU"])
                    removidos += 1
                elif escolha and escolha != linha_antes["Prato no sistema"]:
                    crud.mapear_produto_zig(
                        linha_antes["SKU"],
                        linha_antes["Produto na Zig"],
                        prato_nome=None if escolha == NAO_CONTROLAR else escolha,
                        ignorar=escolha == NAO_CONTROLAR,
                    )
                    alterados += 1

            if alterados or removidos:
                st.success(f"{alterados} alterado(s), {removidos} removido(s).")
                st.rerun()
            else:
                st.info("Nada foi alterado.")


def pagina_zig():
    st.title("🧾 Importar Vendas do PDV")
    st.caption(
        "Envie a planilha de vendas exportada da Zig. Cada produto é ligado uma "
        "vez a um prato do sistema e, nas próximas importações, já é reconhecido "
        "sozinho — no lugar de digitar prato a prato."
    )

    pratos = listar_pratos()
    arquivo = st.file_uploader("Planilha de vendas da Zig", type=["xlsx", "xls"])

    if arquivo is not None:
        try:
            st.session_state["zig_dados"] = zig_import.extrair_vendas_zig(arquivo)
        except Exception as e:
            st.error(f"Não consegui ler essa planilha: {e}")
            st.session_state.pop("zig_dados", None)

    _mapeamentos_salvos(pratos)

    dados = st.session_state.get("zig_dados")
    if not dados:
        return

    datas = dados["datas"]
    periodo = "—" if not datas else (
        datas[0] if len(datas) == 1 else f"{datas[0]} a {datas[-1]}"
    )
    col1, col2, col3 = st.columns(3)
    col1.metric("Linhas na planilha", dados["total_linhas"], border=True)
    col2.metric("Período", periodo, border=True)
    col3.metric("Produtos distintos", len({l["sku"] for l in dados["linhas"]}), border=True)

    if dados["descartadas"]:
        st.warning(
            f"{dados['descartadas']} linha(s) não são transações normais "
            "(cancelamento/estorno) e ficaram de fora da conta."
        )

    reconhecidos = []
    ignorados = []
    pendentes = {}
    for linha in dados["linhas"]:
        mapeamento = crud.buscar_mapeamento_zig(linha["sku"])
        if mapeamento is None:
            pendente = pendentes.setdefault(
                linha["sku"],
                {"SKU": linha["sku"], "Produto na Zig": linha["nome"], "Vendidos": 0},
            )
            pendente["Vendidos"] += linha["quantidade"]
        elif mapeamento["ignorar"] or not mapeamento["prato_nome"]:
            ignorados.append(linha)
        else:
            reconhecidos.append({
                "Data": linha["data"],
                "Produto na Zig": linha["nome"],
                "Prato": mapeamento["prato_nome"],
                "Quantidade": linha["quantidade"],
            })

    if pendentes:
        st.subheader(f"{len(pendentes)} produto(s) para mapear")
        st.caption(
            "Escolha o prato correspondente de cada produto. Itens que não consomem "
            "estoque controlado (couvert, itens de loja) podem ser marcados para não "
            "controlar — assim não voltam a aparecer aqui."
        )
        if not pratos:
            st.error("Cadastre ao menos um prato antes de mapear os produtos da Zig.")
        else:
            df_pendentes = pd.DataFrame(
                sorted(pendentes.values(), key=lambda p: -p["Vendidos"])
            )
            df_pendentes["Prato no sistema"] = None
            editado = st.data_editor(
                df_pendentes,
                hide_index=True,
                width="stretch",
                key="zig_editor",
                disabled=["SKU", "Produto na Zig", "Vendidos"],
                column_config={
                    "Prato no sistema": st.column_config.SelectboxColumn(
                        options=pratos + [NAO_CONTROLAR]
                    ),
                },
            )

            if st.button("Salvar mapeamentos", type="primary"):
                salvos = 0
                for _, linha in editado.iterrows():
                    escolha = linha["Prato no sistema"]
                    if not escolha:
                        continue
                    crud.mapear_produto_zig(
                        linha["SKU"],
                        linha["Produto na Zig"],
                        prato_nome=None if escolha == NAO_CONTROLAR else escolha,
                        ignorar=escolha == NAO_CONTROLAR,
                    )
                    salvos += 1
                if salvos:
                    st.success(f"{salvos} produto(s) mapeado(s)!")
                    st.rerun()
                else:
                    st.info("Nenhum produto foi escolhido ainda.")

    if reconhecidos:
        with st.expander(f"✅ {len(reconhecidos)} lançamento(s) já reconhecido(s)"):
            st.dataframe(pd.DataFrame(reconhecidos), hide_index=True, width="stretch")
    if ignorados:
        st.caption(f"➖ {len(ignorados)} lançamento(s) de produtos marcados para não controlar.")

    st.divider()
    substituir = st.checkbox(
        "Substituir vendas já lançadas nesses dias",
        value=True,
        help="Recomendado: reimportar o mesmo relatório corrige o dia em vez de somar de novo.",
    )
    if st.button(
        "📥 Lançar vendas no estoque", type="primary", disabled=not reconhecidos
    ):
        lancadas, _, nao_mapeadas = zig_import.processar_vendas_zig(dados, substituir)
        st.success(f"{len(lancadas)} venda(s) lançada(s)!")
        st.dataframe(
            pd.DataFrame(lancadas, columns=["Prato", "Data", "Quantidade"]),
            hide_index=True,
            width="stretch",
        )
        if nao_mapeadas:
            st.warning(
                f"{len(nao_mapeadas)} produto(s) ainda sem mapeamento não foram lançados."
            )
        st.session_state.pop("zig_dados", None)


# ---------- Contagem Física Mensal ----------

def pagina_contagem():
    st.title("✅ Contagem Física Mensal")
    st.caption("Use isso 1x por mês para reconciliar o estoque teórico com o real.")

    insumos = listar_insumos()
    if not insumos:
        st.info("Cadastre um insumo antes de registrar contagem.")
        return

    unidades = unidades_dos_insumos()
    insumo = st.selectbox("Insumo", insumos)

    with st.form("form_contagem"):
        quantidade = st.number_input(
            f"Quantidade contada fisicamente ({unidades[insumo]})", min_value=0.0, step=0.5
        )
        data = st.date_input("Data da contagem", value=datetime.date.today())
        observacao = st.text_input("Observação (opcional)")
        enviado = st.form_submit_button("Registrar")

    if enviado:
        try:
            crud.registrar_contagem_fisica(insumo, quantidade, str(data), observacao or None)
            st.success("Contagem registrada! Ela vira a nova base do cálculo automático.")
        except Exception as e:
            st.error(f"Erro: {e}")


# ---------- Navegação ----------

PG_DASHBOARD = st.Page(
    pagina_dashboard, title="Dashboard", icon=":material/dashboard:", default=True
)
PG_PAINEL = st.Page(
    pagina_painel, title="Painel de Estoque", icon=":material/inventory_2:", url_path="painel"
)
PG_INSUMOS = st.Page(
    pagina_insumos, title="Insumos", icon=":material/nutrition:", url_path="insumos"
)
PG_PRATOS = st.Page(
    pagina_pratos, title="Pratos", icon=":material/restaurant:", url_path="pratos"
)
PG_FICHA = st.Page(
    pagina_ficha_tecnica, title="Ficha Técnica", icon=":material/receipt_long:",
    url_path="ficha-tecnica",
)
PG_COMPRA = st.Page(
    pagina_compra, title="Lançar Compra", icon=":material/shopping_cart:", url_path="compra"
)
PG_NFE = st.Page(
    pagina_nfe, title="Importar Nota Fiscal", icon=":material/upload_file:", url_path="nota-fiscal"
)
PG_VENDA = st.Page(
    pagina_venda, title="Lançar Venda do Dia", icon=":material/point_of_sale:", url_path="venda"
)
PG_ZIG = st.Page(
    pagina_zig, title="Importar Vendas (PDV)", icon=":material/receipt:", url_path="vendas-pdv"
)
PG_CONTAGEM = st.Page(
    pagina_contagem, title="Contagem Física", icon=":material/fact_check:", url_path="contagem"
)

navegacao = st.navigation({
    "Visão geral": [PG_DASHBOARD, PG_PAINEL],
    "Cadastros": [PG_INSUMOS, PG_PRATOS, PG_FICHA],
    "Lançamentos": [PG_COMPRA, PG_NFE, PG_ZIG, PG_VENDA, PG_CONTAGEM],
})

with st.sidebar:
    st.divider()
    alertas = crud.resumo_dashboard(30)["abaixo_do_minimo"]
    if alertas:
        st.error(f"⚠️ {alertas} insumo(s) abaixo do mínimo")
    st.caption(f"Hoje: {datetime.date.today().strftime('%d/%m/%Y')}")

navegacao.run()
