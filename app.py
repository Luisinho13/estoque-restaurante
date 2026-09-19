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
import auth
import crud
import ficha_import
import nfe_import
import zig_import

database.criar_tabelas()  # garante que as tabelas existem ao abrir o app

MODO_DEMO = database.modo_demo()

st.set_page_config(
    page_title="Estoque do Restaurante",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

COR = "#2E7D6F"
COR_ALERTA = "#C1443F"

# Acima disso a perda deixa de ser normal e vira alerta. Um restaurante bem
# tocado perde de 1% a 4%; 5% já pede explicação.
LIMITE_PERDA_ALTA = 5.0


def _data_br(data_iso: str) -> str:
    """'2026-08-18' vira '18/08/2026'."""
    return datetime.date.fromisoformat(data_iso).strftime("%d/%m/%Y")


# ---------- Login e cadastro ----------

def _cabecalho_login():
    st.markdown(
        f"<h1 style='text-align:center; color:{COR}; margin-bottom:0'>📦 Estoque</h1>"
        "<p style='text-align:center; color:#6b7280; margin-top:4px'>"
        "Sistema de estoque do restaurante</p>",
        unsafe_allow_html=True,
    )


def _aba_entrar():
    with st.form("login"):
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar", type="primary", use_container_width=True)

    if not entrar:
        return

    dado = auth.autenticar(usuario.strip(), senha)
    if not dado:
        st.error("Usuário ou senha incorretos.")
    elif dado["status"] == "pendente":
        st.warning(
            "Seu cadastro ainda está aguardando aprovação do administrador. "
            "Assim que ele liberar, você consegue entrar com esses mesmos dados."
        )
    elif dado["status"] == "recusado":
        st.error("Este cadastro foi recusado. Procure o administrador.")
    else:
        st.session_state["usuario"] = dado["usuario"]
        st.rerun()


def _aba_cadastrar():
    st.caption(
        "O cadastro é enviado para aprovação do administrador. "
        "Você só consegue entrar depois que ele liberar o acesso."
    )
    with st.form("cadastro"):
        nome = st.text_input("Seu nome")
        usuario = st.text_input("Usuário desejado")
        senha = st.text_input("Senha", type="password")
        confirmacao = st.text_input("Repita a senha", type="password")
        enviar = st.form_submit_button(
            "Enviar cadastro", type="primary", use_container_width=True
        )

    if not enviar:
        return

    usuario = usuario.strip()
    if not nome.strip() or not usuario or not senha:
        st.error("Preencha nome, usuário e senha.")
    elif senha != confirmacao:
        st.error("As duas senhas não são iguais.")
    elif len(senha) < 6:
        st.error("A senha precisa ter pelo menos 6 caracteres.")
    elif auth.existe_usuario(usuario):
        st.error("Já existe alguém com esse usuário. Escolha outro.")
    else:
        auth.cadastrar_usuario(usuario, senha, nome=nome.strip())
        st.success(
            "Cadastro enviado. Avise o administrador para aprovar o seu acesso."
        )


def tela_login():
    """Login e cadastro. Nada do sistema é montado antes disso passar."""
    st.markdown("<div style='height: 6vh'></div>", unsafe_allow_html=True)
    _, meio, _ = st.columns([1, 1.2, 1])
    with meio:
        _cabecalho_login()
        aba_entrar, aba_cadastrar = st.tabs(["Entrar", "Criar cadastro"])
        with aba_entrar:
            _aba_entrar()
        with aba_cadastrar:
            _aba_cadastrar()


# ---------- Modo demonstração ----------

@st.cache_resource
def _semear_demonstracao():
    """Cria os dados fictícios na primeira vez que a vitrine sobe.

    O disco do Streamlit Cloud é efêmero: quando o app dorme e acorda, o
    arquivo some e esta função roda de novo. Na demonstração isso é
    vantagem — o que os visitantes bagunçarem se desfaz sozinho.

    O `cache_resource` faz isso valer uma vez por processo, e não a cada
    interação de cada visitante.
    """
    conn = database.get_connection()
    vazio = conn.execute("SELECT COUNT(*) AS n FROM insumos").fetchone()["n"] == 0
    conn.close()
    if vazio:
        import seed_demo

        seed_demo.main()
    return True


def _entrar_como_visitante():
    """Pula o login na vitrine, entrando com o usuário fictício do seed."""
    import seed_demo

    if not auth.buscar_usuario(seed_demo.USUARIO_DEMO):
        auth.cadastrar_usuario(
            seed_demo.USUARIO_DEMO, seed_demo.SENHA_DEMO,
            nome="Usuário de demonstração", papel="admin",
            status="aprovado", areas=list(auth.AREAS),
        )
    st.session_state["usuario"] = seed_demo.USUARIO_DEMO


if MODO_DEMO:
    _semear_demonstracao()
    if not st.session_state.get("usuario"):
        _entrar_como_visitante()

if not st.session_state.get("usuario"):
    tela_login()
    st.stop()

# Quem está logado é relido a cada execução: se o admin mudar o acesso de
# alguém, a mudança vale na próxima interação, sem precisar sair e entrar.
USUARIO = auth.buscar_usuario(st.session_state["usuario"])
if not USUARIO or USUARIO["status"] != "aprovado":
    st.session_state.pop("usuario", None)
    st.warning("Seu acesso foi alterado pelo administrador. Entre novamente.")
    st.stop()

E_ADMIN = USUARIO["papel"] == "admin"
MINHAS_AREAS = auth.permissoes_de(USUARIO["usuario"])


# ---------- Minha conta ----------

def pagina_minha_conta():
    st.title("Minha conta")

    st.subheader("Seus dados")
    col1, col2, col3 = st.columns(3)
    col1.metric("Usuário", USUARIO["usuario"])
    col2.metric("Nome", USUARIO["nome"] or "—")
    col3.metric("Perfil", "Administrador" if E_ADMIN else "Usuário")
    st.caption(f"Cadastrado em {USUARIO['criado_em']}")

    st.divider()
    st.subheader("Áreas que você acessa")
    if E_ADMIN:
        st.success("Como administrador, você tem acesso a todas as áreas do sistema.")
    else:
        liberadas = [rotulo for chave, rotulo in auth.AREAS.items() if chave in MINHAS_AREAS]
        if liberadas:
            st.write("\n".join(f"- {rotulo}" for rotulo in liberadas))
        else:
            st.info("Nenhuma área liberada ainda. Peça ao administrador.")
        st.caption("Para pedir acesso a outra área, fale com o administrador.")

    st.divider()
    st.subheader("Trocar minha senha")
    with st.form("trocar_senha"):
        atual = st.text_input("Senha atual", type="password")
        nova = st.text_input("Nova senha", type="password")
        confirmacao = st.text_input("Repita a nova senha", type="password")
        trocar = st.form_submit_button("Salvar nova senha", type="primary")

    if trocar:
        if not auth.autenticar(USUARIO["usuario"], atual):
            st.error("A senha atual está incorreta.")
        elif nova != confirmacao:
            st.error("As duas senhas novas não são iguais.")
        elif len(nova) < 6:
            st.error("A senha precisa ter pelo menos 6 caracteres.")
        else:
            auth.alterar_senha(USUARIO["usuario"], nova)
            st.success("Senha alterada.")


# ---------- Admin: aprovação de cadastros ----------

def pagina_aprovacoes():
    st.title("Aprovação de cadastros")
    st.caption("Ninguém entra no sistema sem passar por aqui.")

    pendentes = auth.listar_usuarios(status="pendente")
    if not pendentes:
        st.success("Nenhum cadastro aguardando aprovação.")
    else:
        st.info(f"{len(pendentes)} cadastro(s) aguardando sua decisão.")

    for pendente in pendentes:
        with st.container(border=True):
            st.markdown(f"**{pendente['nome'] or pendente['usuario']}**")
            st.caption(
                f"Usuário: `{pendente['usuario']}` · solicitado em {pendente['criado_em']}"
            )
            areas = st.multiselect(
                "Áreas que este usuário poderá acessar",
                options=list(auth.AREAS),
                default=auth.AREAS_PADRAO,
                format_func=lambda chave: auth.AREAS[chave],
                key=f"areas_pendente_{pendente['id']}",
            )
            col_aprovar, col_recusar = st.columns(2)
            if col_aprovar.button(
                "Aprovar", key=f"aprovar_{pendente['id']}", type="primary",
                use_container_width=True,
            ):
                auth.aprovar_usuario(pendente["usuario"], USUARIO["usuario"], areas)
                st.success(f"{pendente['usuario']} aprovado.")
                st.rerun()
            if col_recusar.button(
                "Recusar", key=f"recusar_{pendente['id']}", use_container_width=True
            ):
                auth.recusar_usuario(pendente["usuario"], USUARIO["usuario"])
                st.warning(f"{pendente['usuario']} recusado.")
                st.rerun()

    recusados = auth.listar_usuarios(status="recusado")
    if recusados:
        st.divider()
        st.subheader("Cadastros recusados")
        st.caption("Você pode reverter uma recusa aprovando o cadastro de novo.")
        for recusado in recusados:
            col_nome, col_botao = st.columns([3, 1])
            col_nome.write(
                f"**{recusado['usuario']}** — {recusado['nome'] or 'sem nome'} "
                f"(recusado em {recusado['decidido_em'] or '—'})"
            )
            if col_botao.button(
                "Reconsiderar", key=f"reconsiderar_{recusado['id']}",
                use_container_width=True,
            ):
                auth.aprovar_usuario(recusado["usuario"], USUARIO["usuario"])
                st.success(f"{recusado['usuario']} aprovado com acesso básico.")
                st.rerun()


# ---------- Admin: usuários e liberação de acessos ----------

def _cartao_de_usuario(dado):
    """Um usuário aprovado, com suas áreas, papel e ações do admin."""
    sou_eu = dado["usuario"] == USUARIO["usuario"]
    e_admin = dado["papel"] == "admin"

    with st.container(border=True):
        titulo = f"**{dado['usuario']}**"
        if dado["nome"]:
            titulo += f" — {dado['nome']}"
        if e_admin:
            titulo += " · 🛡️ administrador"
        if sou_eu:
            titulo += " · (você)"
        st.markdown(titulo)

        if e_admin:
            st.caption("Administradores acessam todas as áreas automaticamente.")
        else:
            areas = st.multiselect(
                "Áreas liberadas",
                options=list(auth.AREAS),
                default=[a for a in dado["areas"] if a in auth.AREAS],
                format_func=lambda chave: auth.AREAS[chave],
                key=f"areas_{dado['id']}",
            )
            if st.button(
                "Salvar acessos", key=f"salvar_areas_{dado['id']}", type="primary"
            ):
                auth.definir_permissoes(dado["usuario"], areas)
                st.success(f"Acessos de {dado['usuario']} atualizados.")
                st.rerun()

        with st.expander("Mais ações"):
            if e_admin:
                # Sem esta trava dá para remover o último admin e ninguém
                # mais consegue aprovar cadastros ou liberar acessos.
                ultimo_admin = auth.total_de_admins_aprovados() <= 1
                if st.button(
                    "Rebaixar para usuário comum",
                    key=f"rebaixar_{dado['id']}",
                    disabled=ultimo_admin,
                    help="O sistema precisa de pelo menos um administrador."
                    if ultimo_admin else None,
                ):
                    auth.definir_papel(dado["usuario"], "usuario")
                    auth.definir_permissoes(dado["usuario"], auth.AREAS_PADRAO)
                    st.rerun()
            else:
                if st.button("Tornar administrador", key=f"promover_{dado['id']}"):
                    auth.definir_papel(dado["usuario"], "admin")
                    st.rerun()

            nova = st.text_input(
                "Definir nova senha", type="password", key=f"nova_senha_{dado['id']}"
            )
            if st.button("Redefinir senha", key=f"redefinir_{dado['id']}"):
                if len(nova) < 6:
                    st.error("A senha precisa ter pelo menos 6 caracteres.")
                else:
                    auth.alterar_senha(dado["usuario"], nova)
                    st.success(f"Senha de {dado['usuario']} redefinida.")

            if sou_eu:
                st.caption("Você não pode excluir o seu próprio usuário.")
            else:
                confirmar = st.checkbox(
                    "Confirmo que quero excluir este usuário",
                    key=f"confirmar_exclusao_{dado['id']}",
                )
                if st.button(
                    "Excluir usuário", key=f"excluir_{dado['id']}", disabled=not confirmar
                ):
                    auth.excluir_usuario(dado["usuario"])
                    st.warning(f"{dado['usuario']} excluído.")
                    st.rerun()


def pagina_usuarios():
    st.title("Usuários e acessos")
    st.caption("Quem usa o sistema e o que cada um pode abrir.")

    aprovados = auth.listar_usuarios(status="aprovado")
    pendentes = auth.total_pendentes()

    col1, col2, col3 = st.columns(3)
    col1.metric("Usuários ativos", len(aprovados))
    col2.metric("Administradores", sum(1 for a in aprovados if a["papel"] == "admin"))
    col3.metric("Aguardando aprovação", pendentes)
    if pendentes:
        st.info("Há cadastros pendentes — resolva na tela Aprovação de cadastros.")

    st.divider()
    for dado in aprovados:
        _cartao_de_usuario(dado)

    st.divider()
    with st.expander("Cadastrar usuário direto (já aprovado)"):
        st.caption(
            "Atalho para criar um acesso sem passar pela fila de aprovação — "
            "útil quando você mesmo está configurando a conta de alguém."
        )
        with st.form("novo_usuario_admin"):
            nome = st.text_input("Nome")
            usuario = st.text_input("Usuário")
            senha = st.text_input("Senha", type="password")
            areas = st.multiselect(
                "Áreas liberadas",
                options=list(auth.AREAS),
                default=auth.AREAS_PADRAO,
                format_func=lambda chave: auth.AREAS[chave],
            )
            como_admin = st.checkbox("Criar como administrador")
            criar = st.form_submit_button("Criar usuário", type="primary")

        if criar:
            usuario = usuario.strip()
            if not usuario or not senha:
                st.error("Preencha usuário e senha.")
            elif len(senha) < 6:
                st.error("A senha precisa ter pelo menos 6 caracteres.")
            elif auth.existe_usuario(usuario):
                st.error("Já existe alguém com esse usuário.")
            else:
                auth.cadastrar_usuario(
                    usuario, senha, nome=nome.strip() or None,
                    papel="admin" if como_admin else "usuario",
                    status="aprovado", areas=areas,
                )
                st.success(f"Usuário {usuario} criado e liberado.")
                st.rerun()


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

    if resumo["sem_contagem_inicial"]:
        st.info(
            f"{resumo['sem_contagem_inicial']} insumo(s) ainda não têm contagem física. "
            "Sem um ponto de partida, o cálculo começa do zero e o estoque deles fica "
            "negativo — registre uma contagem para o número passar a valer."
        )
    if resumo["estoque_negativo"]:
        st.error(
            f"{resumo['estoque_negativo']} insumo(s) com estoque negativo mesmo tendo "
            "contagem física. Isso costuma significar compra não lançada ou ficha técnica errada."
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


# ---------- Importar Ficha Técnica ----------

def _plano_da_ficha():
    """Monta o plano de importação com os ajustes de prato feitos na tela."""
    prato = st.session_state.get("ficha_planilha_prato")
    producao = st.session_state.get("ficha_planilha_producao")
    if not prato:
        return None
    de_para = dict(ficha_import.DE_PARA_PADRAO)
    de_para.update(st.session_state.get("ficha_de_para_extra", {}))
    return ficha_import.montar_plano(prato, producao or [], de_para)


def pagina_ficha_import():
    st.title("📥 Importar Ficha Técnica")
    st.caption(
        "Envie as planilhas de ficha técnica e o sistema cadastra insumo, prato "
        "e receita de uma vez. Nada é gravado antes de você conferir a prévia."
    )

    col1, col2 = st.columns(2)
    arquivo_prato = col1.file_uploader(
        "Ficha dos pratos finais", type=["xlsx"], key="up_ficha_prato"
    )
    arquivo_producao = col2.file_uploader(
        "Ficha de produção (molhos e bases)", type=["xlsx"], key="up_ficha_producao"
    )

    if arquivo_prato is not None:
        try:
            st.session_state["ficha_planilha_prato"] = ficha_import.ler_planilha(arquivo_prato)
        except Exception as e:
            st.error(f"Não consegui ler a planilha de pratos: {e}")
    if arquivo_producao is not None:
        try:
            st.session_state["ficha_planilha_producao"] = ficha_import.ler_planilha(arquivo_producao)
        except Exception as e:
            st.error(f"Não consegui ler a planilha de produção: {e}")

    if not st.session_state.get("ficha_planilha_prato"):
        st.info("Envie ao menos a planilha dos pratos finais para ver a prévia.")
        return

    if not st.session_state.get("ficha_planilha_producao"):
        st.warning(
            "Sem a planilha de produção, os molhos e bases citados nas receitas "
            "viram insumo em vez de serem abertos nos ingredientes de compra."
        )

    plano = _plano_da_ficha()
    if plano is None or not plano["fichas"]:
        st.error("Não encontrei nenhuma ficha técnica preenchida nessas planilhas.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Pratos", len(plano["pratos"]),
                delta=f"{len(plano['pratos_novos'])} novos", border=True)
    col2.metric("Insumos", len(plano["insumos"]),
                delta=f"{len(plano['insumos_novos'])} novos", border=True)
    col3.metric("Linhas de ficha", len(plano["fichas"]), border=True)
    col4.metric("Pontos de atenção", len(plano["avisos"]), border=True)

    if plano["pratos_sem_ficha"]:
        st.subheader("Pratos do sistema que ficariam sem ficha")
        st.caption(
            "Esses pratos já recebem venda, mas nenhuma aba da planilha "
            "corresponde a eles — sem ficha, vender não desconta nada do "
            "estoque. Ligue cada um à aba certa, se houver."
        )
        abas = sorted({f["aba"] for f in plano["fichas"]})
        extras = dict(st.session_state.get("ficha_de_para_extra", {}))
        for prato_sem in plano["pratos_sem_ficha"]:
            escolha = st.selectbox(
                f"Aba da planilha que descreve '{prato_sem}'",
                ["— deixar sem ficha —"] + abas,
                key=f"liga_{prato_sem}",
            )
            if escolha != "— deixar sem ficha —":
                extras[escolha] = prato_sem
        if extras != st.session_state.get("ficha_de_para_extra", {}):
            st.session_state["ficha_de_para_extra"] = extras
            st.rerun()

    if plano["avisos"]:
        with st.expander(f"⚠️ {len(plano['avisos'])} ponto(s) de atenção na leitura"):
            st.caption(
                "São as linhas em que a planilha estava ambígua e eu tive que "
                "decidir. Vale conferir antes de gravar."
            )
            for aviso in plano["avisos"]:
                st.markdown(f"- {aviso}")

    with st.expander(f"🥬 {len(plano['insumos_novos'])} insumo(s) que serão criados"):
        st.dataframe(
            pd.DataFrame(
                [{"Insumo": n, "Unidade": plano["insumos"][n]} for n in plano["insumos_novos"]]
            ),
            hide_index=True, width="stretch",
        )

    with st.expander(f"🍽️ {len(plano['pratos_novos'])} prato(s) que serão criados"):
        st.dataframe(pd.DataFrame({"Prato": plano["pratos_novos"]}),
                     hide_index=True, width="stretch")

    with st.expander(f"📋 {len(plano['fichas'])} linha(s) de ficha técnica"):
        st.dataframe(
            pd.DataFrame([
                {"Prato": f["prato"], "Insumo": f["insumo"],
                 "Quantidade": f["quantidade"],
                 "Unidade": plano["insumos"][f["insumo"]], "Aba": f["aba"]}
                for f in plano["fichas"]
            ]),
            hide_index=True, width="stretch", height=400,
        )

    if plano["orfaos"]:
        st.info(
            "Insumos que existem no sistema e que nenhuma receita da planilha "
            "usa: " + ", ".join(plano["orfaos"]) +
            ". Eles não serão apagados — se quiser tirar, use a tela de Insumos."
        )

    st.divider()
    corrigir_unidades = True
    if plano["unidades_divergentes"]:
        st.subheader("Unidades que não batem")
        st.caption(
            "Esses insumos já existem contados numa unidade e a ficha usa outra. "
            "Deixar como está faz o painel mostrar saldo na unidade errada."
        )
        st.dataframe(
            pd.DataFrame([
                {"Insumo": d["insumo"], "Hoje no sistema": d["atual"],
                 "Na planilha": d["planilha"]}
                for d in plano["unidades_divergentes"]
            ]),
            hide_index=True, width="stretch",
        )
        corrigir_unidades = st.checkbox(
            "Passar esses insumos para a unidade da planilha", value=True
        )

    substituir = st.checkbox(
        "Substituir a ficha atual dos pratos importados",
        value=True,
        help=(
            "Recomendado. Sem isso, um insumo que saiu da receita continuaria "
            "sendo descontado para sempre."
        ),
    )
    confirmado = st.checkbox(
        f"Confirmo a importação de {len(plano['fichas'])} linha(s) de ficha técnica"
    )
    if st.button("📥 Cadastrar tudo", type="primary", disabled=not confirmado):
        try:
            feito = ficha_import.aplicar_plano(plano, substituir, corrigir_unidades)
        except Exception as e:
            st.error(f"Erro ao gravar: {e}")
            return
        recado = (
            f"{feito['insumos']} insumo(s), {feito['pratos']} prato(s) e "
            f"{feito['fichas']} linha(s) de ficha técnica cadastrados!"
        )
        if feito["unidades"]:
            recado += f" {feito['unidades']} unidade(s) de medida corrigida(s)."
        st.success(recado)
        for chave_sessao in ("ficha_planilha_prato", "ficha_planilha_producao",
                             "ficha_de_para_extra"):
            st.session_state.pop(chave_sessao, None)


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


def _explicacao_da_conta():
    with st.expander("Como esta conta é feita"):
        st.markdown(
            """
            Entre duas contagens físicas dá para fechar a conta do que
            aconteceu com cada insumo. Tudo que estava disponível teve um de
            três destinos, e os três somam exatamente 100%:

            ```
            disponível  =  estoque da contagem anterior + compras do período
            disponível  =  usado (vendas × ficha técnica)
                         + sobra (contagem atual)
                         + perda (o que falta para fechar)
            ```

            A **perda** é o que não se explica por venda nem por sobra:
            quebra, desperdício, produto estragado, porção servida maior que
            a da ficha técnica, furo. É exatamente o número que a contagem
            mensal existe para revelar — sem ela, essa diferença fica
            invisível.

            Um insumo só aparece aqui depois de ter **duas** contagens. Antes
            disso não existe período fechado para reconciliar.
            """
        )


def _grafico_perdas(itens):
    dados = [i for i in itens if i["pct_perda"] is not None][:12]
    if not dados:
        return
    df = pd.DataFrame([
        {"insumo": i["insumo"], "perda": i["pct_perda"], "quantidade": i["perda"],
         "unidade": i["unidade_medida"]}
        for i in dados
    ])
    grafico = (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            x=alt.X("perda:Q", title="Perda no período (% do disponível)"),
            y=alt.Y("insumo:N", sort="-x", title=None),
            # Vermelho só a partir de 5%: abaixo disso a perda é normal e
            # pintar tudo de alerta faria o alerta perder o sentido.
            color=alt.condition(
                alt.datum.perda >= LIMITE_PERDA_ALTA,
                alt.value(COR_ALERTA),
                alt.value(COR),
            ),
            tooltip=[
                alt.Tooltip("insumo:N", title="Insumo"),
                alt.Tooltip("perda:Q", title="Perda", format=".1f"),
                alt.Tooltip("quantidade:Q", title="Quantidade perdida", format=".2f"),
                alt.Tooltip("unidade:N", title="Unidade"),
            ],
        )
        .properties(height=max(180, 34 * len(df)))
    )
    st.altair_chart(grafico, width="stretch")


def pagina_perdas():
    st.title("🧾 Perdas e Reconciliação")
    st.caption(
        "O que foi comprado, o que virou venda e o que se perdeu pelo caminho — "
        "entre uma contagem física e a seguinte."
    )

    itens = crud.reconciliacao_de_perdas()
    pendentes = crud.insumos_sem_reconciliacao()

    if not itens:
        st.info(
            "Ainda não há nenhum período fechado para reconciliar.\n\n"
            "Esta conta compara **duas** contagens físicas do mesmo insumo: "
            "a primeira é o ponto de partida e a segunda revela o que se "
            "perdeu no caminho. Com apenas uma contagem registrada, ainda não "
            "há o que comparar."
        )
        if pendentes:
            st.write(
                f"**{len(pendentes)} insumo(s)** aguardando a próxima contagem: "
                + ", ".join(pendentes[:12])
                + ("…" if len(pendentes) > 12 else "")
            )
        st.caption(
            "Registre a contagem do mês que vem em **Contagem Física** e esta "
            "tela passa a funcionar sozinha."
        )
        _explicacao_da_conta()
        return

    resumo = crud.resumo_de_perdas()
    col1, col2, col3 = st.columns(3)
    col1.metric("Insumos reconciliados", resumo["insumos_reconciliados"])
    col2.metric(
        "Perda média",
        f"{resumo['pct_perda_medio']}%" if resumo["pct_perda_medio"] is not None else "—",
    )
    col3.metric(
        "Maior perda",
        f"{resumo['pior_pct']}%" if resumo["pior_pct"] is not None else "—",
        delta=resumo["pior_insumo"] or None,
        delta_color="off",
    )

    criticos = [i for i in itens if (i["pct_perda"] or 0) >= LIMITE_PERDA_ALTA]
    if criticos:
        st.error(
            f"⚠️ {len(criticos)} insumo(s) com perda de {LIMITE_PERDA_ALTA}% ou mais: "
            + ", ".join(f"{i['insumo']} ({i['pct_perda']}%)" for i in criticos[:5])
        )

    sobras = [i for i in itens if i["perda"] < 0]
    if sobras:
        st.warning(
            f"{len(sobras)} insumo(s) com **mais** estoque do que o esperado: "
            + ", ".join(i["insumo"] for i in sobras[:5])
            + ". Isso não é sobra boa — costuma ser venda não lançada, compra "
            "não registrada ou erro de contagem."
        )

    st.subheader("Perda por insumo")
    _grafico_perdas(sorted(itens, key=lambda i: -(i["pct_perda"] or 0)))

    st.subheader("A conta de cada insumo")
    st.caption("As três colunas de percentual somam 100% do que estava disponível.")
    df = pd.DataFrame([
        {
            "Insumo": i["insumo"],
            "Un.": i["unidade_medida"],
            "Disponível": i["disponivel"],
            "Usado": i["consumo"],
            "% usado": i["pct_usado"],
            "Sobrou": i["estoque_final_contado"],
            "% sobra": i["pct_sobra"],
            "Perdido": i["perda"],
            "% perda": i["pct_perda"],
            "Período": f"{_data_br(i['inicio'])} → {_data_br(i['fim'])} ({i['dias']}d)",
        }
        for i in sorted(itens, key=lambda i: -(i["pct_perda"] or 0))
    ])
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "% usado": st.column_config.NumberColumn(format="%.1f%%"),
            "% sobra": st.column_config.NumberColumn(format="%.1f%%"),
            "% perda": st.column_config.NumberColumn(format="%.1f%%"),
            "Disponível": st.column_config.NumberColumn(format="%.2f"),
            "Usado": st.column_config.NumberColumn(format="%.2f"),
            "Sobrou": st.column_config.NumberColumn(format="%.2f"),
            "Perdido": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    if pendentes:
        with st.expander(f"{len(pendentes)} insumo(s) ainda sem período fechado"):
            st.caption(
                "Estes têm menos de duas contagens físicas. Eles entram nesta "
                "tela assim que a próxima contagem for registrada."
            )
            st.write(", ".join(pendentes))

    _explicacao_da_conta()


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
PG_FICHA_IMPORT = st.Page(
    pagina_ficha_import, title="Importar Ficha Técnica",
    icon=":material/upload:", url_path="importar-ficha",
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
PG_PERDAS = st.Page(
    pagina_perdas, title="Perdas e Reconciliação", icon=":material/scale:",
    url_path="perdas",
)
PG_CONTAGEM = st.Page(
    pagina_contagem, title="Contagem Física", icon=":material/fact_check:", url_path="contagem"
)

PG_MINHA_CONTA = st.Page(
    pagina_minha_conta, title="Minha conta", icon=":material/person:", url_path="minha-conta"
)
PG_APROVACOES = st.Page(
    pagina_aprovacoes, title="Aprovação de cadastros", icon=":material/how_to_reg:",
    url_path="aprovacoes",
)
PG_USUARIOS = st.Page(
    pagina_usuarios, title="Usuários e acessos", icon=":material/manage_accounts:",
    url_path="usuarios",
)

# Cada página só entra no menu se a área dela estiver liberada para quem entrou.
# Não é só esconder do menu: o Streamlit não registra a rota, então nem
# digitando a URL o usuário chega numa tela que não é dele.
PAGINAS_POR_AREA = {
    "dashboard": PG_DASHBOARD,
    "painel": PG_PAINEL,
    "insumos": PG_INSUMOS,
    "pratos": PG_PRATOS,
    "ficha": PG_FICHA,
    "ficha_import": PG_FICHA_IMPORT,
    "compra": PG_COMPRA,
    "nfe": PG_NFE,
    "zig": PG_ZIG,
    "venda": PG_VENDA,
    "contagem": PG_CONTAGEM,
    "perdas": PG_PERDAS,
}


def _liberadas(*areas):
    return [PAGINAS_POR_AREA[a] for a in areas if a in MINHAS_AREAS]


menu = {}
if _liberadas("dashboard", "painel", "perdas"):
    menu["Visão geral"] = _liberadas("dashboard", "painel", "perdas")
if _liberadas("insumos", "pratos", "ficha", "ficha_import"):
    menu["Cadastros"] = _liberadas("insumos", "pratos", "ficha", "ficha_import")
if _liberadas("compra", "nfe", "zig", "venda", "contagem"):
    menu["Lançamentos"] = _liberadas("compra", "nfe", "zig", "venda", "contagem")

menu["Conta"] = [PG_MINHA_CONTA]
if E_ADMIN:
    menu["Administração"] = [PG_APROVACOES, PG_USUARIOS]

# Um usuário aprovado mas ainda sem nenhuma área cai aqui: sem página
# nenhuma o st.navigation quebraria, então ele fica só com a conta dele.
if not any(chave in menu for chave in ("Visão geral", "Cadastros", "Lançamentos")):
    st.session_state["_sem_areas"] = True

navegacao = st.navigation(menu)

if MODO_DEMO:
    st.warning(
        "**Ambiente de demonstração.** Os dados são fictícios e o login está "
        "desligado de propósito, para você olhar à vontade. Pode lançar venda, "
        "importar nota e fazer contagem — nada aqui é um restaurante de "
        "verdade, e tudo volta ao começo quando o app reinicia.",
        icon=":material/science:",
    )

with st.sidebar:
    st.divider()
    rotulo = USUARIO["nome"] or USUARIO["usuario"]
    st.caption(f"Conectado como **{rotulo}**" + (" · 🛡️ admin" if E_ADMIN else ""))
    # Na vitrine o botão de sair não faria nada visível: o visitante entra
    # sozinho de novo na interação seguinte.
    if not MODO_DEMO and st.button("Sair", icon=":material/logout:", use_container_width=True):
        st.session_state.pop("usuario", None)
        st.rerun()
    if MODO_DEMO:
        st.caption(
            "Demonstração com dados fictícios · "
            "[código no GitHub](https://github.com/Luisinho13/estoque-restaurante)"
        )

    if E_ADMIN:
        pendentes = auth.total_pendentes()
        if pendentes:
            st.warning(f"👤 {pendentes} cadastro(s) aguardando aprovação")

    if "painel" in MINHAS_AREAS or "dashboard" in MINHAS_AREAS:
        alertas = crud.resumo_dashboard(30)["abaixo_do_minimo"]
        if alertas:
            st.error(f"⚠️ {alertas} insumo(s) abaixo do mínimo")
    st.caption(f"Hoje: {datetime.date.today().strftime('%d/%m/%Y')}")

if st.session_state.pop("_sem_areas", False):
    st.info(
        "Seu acesso foi aprovado, mas nenhuma área do sistema foi liberada "
        "para você ainda. Peça ao administrador."
    )

navegacao.run()
