"""
app.py
Interface do sistema de estoque, feita em Streamlit.

Rodar com: streamlit run app.py
"""

import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import database
import auth
import bar_import
import contagem_import
import cozinha_fria
import crud
import exemplos
import ficha_import
import nfe_import
import zig_import

MODO_DEMO = database.modo_demo()

st.set_page_config(
    page_title="Estoque do Restaurante",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

PASTA_DO_APP = Path(__file__).parent
LOGO = PASTA_DO_APP / "assets" / "logo.svg"
st.logo(str(LOGO), icon_image=str(PASTA_DO_APP / "assets" / "logo-icone.svg"), size="large")


def _titulo(icone: str, texto: str):
    """Título de tela: o mesmo ícone do menu, na cor do tema, e o nome.

    Antes cada tela abria com um emoji diferente do ícone que a leva no
    menu. Um só jeito de abrir as telas ajuda quem procura onde está.
    """
    st.title(f":primary[:material/{icone}:] {texto}")

# Depois de um push, o Streamlit Cloud troca os arquivos, mas o processo que
# já estava no ar pode seguir com a versão antiga dos módulos na memória: o
# app.py é relido a cada execução, os módulos importados não. Em 24/09 isso
# rodou o app.py novo com o ficha_import antigo — deu KeyError, por sorte
# antes de gravar. Com crud antigo e tela nova, um lançamento gravaria pela
# regra velha sem erro nenhum. Cada módulo guarda a data do arquivo que ele
# carregou; se o arquivo no disco mudou desde então, o processo está velho.
MODULOS_DO_APP = (database, auth, bar_import, contagem_import, cozinha_fria, crud,
                  exemplos, ficha_import, nfe_import, zig_import)


def _modulos_desatualizados():
    velhos = []
    for modulo in MODULOS_DO_APP:
        no_disco = Path(modulo.__file__).stat().st_mtime
        carregado = getattr(modulo, "_data_do_arquivo_carregado", None)
        if carregado is None:
            modulo._data_do_arquivo_carregado = no_disco
        elif carregado != no_disco:
            velhos.append(modulo.__name__)
    return velhos


_velhos = _modulos_desatualizados()
if _velhos:
    _titulo("inventory", "Controle de Estoque")
    st.error(
        "**O sistema foi atualizado e precisa ser reiniciado** antes de usar. "
        "Até lá nada é gravado, para não misturar a versão nova com a antiga. "
        "Quem administra o app: *Manage app* → ⋮ → *Reboot app*.",
        icon=":material/restart_alt:",
    )
    st.caption("Módulos desatualizados: " + ", ".join(_velhos))
    st.stop()

# O banco na nuvem dorme quando fica sem uso, e acordá-lo leva alguns
# segundos. Quando nem assim ele responde, quem abriu o app precisa ver o
# que aconteceu e um botão — e não uma tela de exceção, que não diz nada a
# quem está lançando a venda no fim do expediente.
try:
    # O spinner existe para a espera não ser uma tela em branco: acordar o
    # banco leva alguns segundos, e sem sinal nenhum parece travamento.
    with st.spinner("Conectando ao banco de dados…"):
        # Desfaz o que a execução anterior deixou aberto (ver o docstring).
        database.comecar_execucao()
        database.garantir_tabelas()  # uma vez por processo, não a cada clique
except database.BancoIndisponivel:
    _titulo("inventory", "Controle de Estoque")
    st.error(
        "**O banco de dados não respondeu.** Ele hiberna quando fica um "
        "tempo sem uso e leva alguns segundos para acordar. Normalmente "
        "basta tentar de novo.",
        icon=":material/cloud_off:",
    )
    if st.button("Tentar de novo", type="primary", icon=":material/refresh:"):
        st.rerun()
    st.caption(
        "Se continuar assim depois de algumas tentativas, o problema não é "
        "hibernação: verifique o banco no Neon e os secrets do app."
    )
    st.stop()

COR = "#2E7D6F"
COR_ALERTA = "#C1443F"

# Acima disso a perda deixa de ser normal e vira alerta. Um restaurante bem
# tocado perde de 1% a 4%; 5% já pede explicação.
LIMITE_PERDA_ALTA = 5.0

# Opção dos filtros de setor (venda e saída) que mostra cozinha e bar juntos.
TODOS_OS_SETORES = "Todos"


def _data_br(data_iso: str) -> str:
    """'2026-08-18' vira '18/08/2026'."""
    return datetime.date.fromisoformat(data_iso).strftime("%d/%m/%Y")


# ---------- Login e cadastro ----------

def _cabecalho_login():
    st.image(str(LOGO), width=220)
    st.caption(
        "Estoque calculado a partir das compras, das vendas e da produção. "
        "Entre com o usuário que o administrador liberou."
    )


def _aba_entrar():
    with st.form("login", border=False):
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
    with st.form("cadastro", border=False):
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
    st.space("large")
    _, meio, _ = st.columns([1, 1.1, 1])
    with meio, st.container(border=True):
        _cabecalho_login()
        aba_entrar, aba_cadastrar = st.tabs(["Entrar", "Criar cadastro"])
        with aba_entrar:
            _aba_entrar()
        with aba_cadastrar:
            _aba_cadastrar()
    st.caption(
        "<div style='text-align:center'>Criado por Luis Felipe · © 2026</div>",
        unsafe_allow_html=True,
    )


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
    _titulo("person", "Minha conta")

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

    if E_ADMIN:
        st.divider()
        st.subheader("Onde os dados estão sendo gravados")
        # Já aconteceu de um lançamento sumir porque o app caiu calado no
        # SQLite em vez do Postgres. Agora a escolha do banco é congelada
        # na partida do processo e fica escrita aqui, para a pergunta
        # "em qual banco isso caiu?" ter resposta sem abrir o servidor.
        st.info(database.descricao_do_backend(), icon=":material/database:")

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
    _titulo("how_to_reg", "Aprovação de cadastros")
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
    _titulo("manage_accounts", "Usuários e acessos")
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


def _tabela_em_lote(linhas, coluna_item, coluna_valor, rotulo_valor, chave,
                    formato, busca_rotulo, passo=0.5, grupo=""):
    """Tabela editável com filtro, para preencher muitos itens de uma vez.

    Devolve `{nome do item: valor}` só com o que foi realmente digitado.

    Duas armadilhas resolvidas aqui, ambas do tipo que não dá erro:

    **O filtro trocaria os valores de lugar.** O `st.data_editor` guarda as
    edições por *índice de linha*, não por item. Filtrar muda quais linhas
    ocupam cada índice, então um valor digitado antes do filtro seria
    reaplicado em outro insumo depois dele — silenciosamente. Por isso os
    valores são mantidos aqui, num dicionário por nome, e o widget ganha
    uma chave que inclui o texto do filtro: ao filtrar, o editor recomeça
    limpo e é remontado a partir do dicionário, que é a fonte da verdade.

    **Branco e zero são coisas diferentes.** Célula vazia significa "não
    mexer" e zero significa "é zero mesmo". Como NaN é *truthy* em Python,
    o teste tem que ser `pd.isna()`, nunca `not valor`.

    A chave deve incluir a data quando a tela tem uma, para que trocar de
    dia não carregue os números do dia anterior.

    `grupo` serve quando a tela mostra só parte dos itens de cada vez (uma
    seção da planilha de contagem): ele entra na chave do widget pelo mesmo
    motivo do filtro, enquanto os valores continuam num dicionário só.
    Quem chama pode pré-carregar `st.session_state[f"{chave}_valores"]` com
    todos os itens, já que `linhas` traz só o grupo visível.
    """
    chave_valores = f"{chave}_valores"
    if chave_valores not in st.session_state:
        st.session_state[chave_valores] = {
            l[coluna_item]: float(l[coluna_valor])
            for l in linhas
            if l.get(coluna_valor) is not None and not pd.isna(l[coluna_valor])
        }
    valores = st.session_state[chave_valores]

    busca = st.text_input(busca_rotulo, key=f"{chave}_busca",
                          placeholder="digite para filtrar")
    termo = busca.strip().lower()
    visiveis = [l for l in linhas if termo in l[coluna_item].lower()] if termo else linhas

    if not visiveis:
        st.caption("Nenhum item com esse nome.")
        return valores

    # A contagem de preenchidos NÃO entra aqui: esta legenda é desenhada
    # antes do editor, então mostraria o número anterior à edição desta
    # interação — sempre um passo atrasado. Ela aparece depois da tabela,
    # onde o número já está certo.
    #
    # O "None" cinza das células vazias é do próprio Streamlit, que usa
    # essa palavra como marca de célula numérica em branco. Não dá para
    # trocar pelo column_config, então resta dizer o que ela significa.
    st.caption(
        f"Mostrando {len(visiveis)} de {len(linhas)}. "
        "Célula com None em cinza está vazia."
    )

    exibidas = [{**l, coluna_valor: valores.get(l[coluna_item])} for l in visiveis]
    df = pd.DataFrame(exibidas)
    # Coluna toda em None vira dtype 'object', e aí o editor escreve o texto
    # "None" em cada célula em vez de deixá-la vazia. Convertida para número,
    # None vira NaN e a célula aparece em branco, que é o que "não preenchido"
    # deve parecer.
    df[coluna_valor] = pd.to_numeric(df[coluna_valor], errors="coerce")
    tabela = st.data_editor(
        df,
        width="stretch",
        hide_index=True,
        height=min(620, 60 + 35 * len(exibidas)),
        # A chave muda com o filtro de propósito: ver o docstring.
        key=f"{chave}_editor_{grupo}_{termo}",
        disabled=[c for c in exibidas[0] if c != coluna_valor],
        column_config={
            coluna_valor: st.column_config.NumberColumn(
                rotulo_valor, min_value=0, step=passo, format=formato
            ),
        },
    )

    # O que está visível volta para o dicionário; o que está filtrado fora
    # permanece como estava.
    for _, linha in tabela.iterrows():
        nome = linha[coluna_item]
        valor = linha[coluna_valor]
        if pd.isna(valor):
            valores.pop(nome, None)
        else:
            valores[nome] = float(valor)
    return valores


def _guardar_resultado(chave, valores, resultado):
    """Guarda o que a gravação de uma tabela em lote produziu, para mostrar depois.

    A mensagem não pode ser desenhada só na execução do botão. Nela a
    tabela é remontada com os valores digitados já embutidos nos dados; o
    `data_editor` percebe que os dados mudaram, descarta as edições
    pendentes e dispara mais uma execução — que redesenhava a página sem a
    confirmação e sem o relatório de divergências. O dado era gravado, mas
    quem gravou não via nada. Guardado aqui, o resultado sobrevive a essa
    execução extra e só some quando a tabela é editada de novo.
    """
    st.session_state[f"{chave}_resultado"] = {"valores": dict(valores), **resultado}


def _resultado_guardado(chave, valores):
    """O resultado da última gravação, se a tabela não mudou desde ela."""
    resultado = st.session_state.get(f"{chave}_resultado")
    if resultado and resultado["valores"] == valores:
        return resultado
    st.session_state.pop(f"{chave}_resultado", None)
    return None


def _como_itens(valores, chave_item, chave_valor):
    """O dicionário da tabela vira a lista que as funções de lote esperam."""
    return [
        {chave_item: nome, chave_valor: valor}
        for nome, valor in sorted(valores.items())
    ]


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


DIAS_DA_SEMANA = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")


def _atalho(area, pagina, rotulo, icone):
    """Link para outra tela, só se ela estiver liberada para quem entrou."""
    if area in MINHAS_AREAS:
        st.page_link(pagina, label=rotulo, icon=icone)


def _tabela_curta(linhas, colunas, altura_por_linha=35, maximo=8):
    """Tabela pequena, sem índice, que rola a partir de `maximo` linhas."""
    df = pd.DataFrame(linhas)[list(colunas)].rename(columns=colunas)
    st.dataframe(
        df, hide_index=True, width="stretch",
        height=min(len(df), maximo) * altura_por_linha + 38,
        column_config={
            "Saldo": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def _painel_do_dia():
    """O topo do dashboard: a rotina de hoje e o que pede ação.

    Design, etapa 2 (pedido do usuário em 30/09/2026, aprovado o visual):
    quem abre o sistema de manhã quer saber, sem procurar, se a venda de
    ontem entrou, o que a cozinha precisa lançar e o que precisa comprar.
    """
    dia = crud.resumo_do_dia()
    hoje = datetime.date.fromisoformat(dia["hoje"])
    ontem = _data_br(dia["ontem"])[:5]
    st.subheader(f"Hoje, {DIAS_DA_SEMANA[hoje.weekday()]} {hoje.strftime('%d/%m')}")

    vendas = dia["vendas_ontem"]
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if vendas["total"]:
            st.metric(
                f"Venda de ontem ({ontem})", f"{vendas['total']:g} itens",
                delta=f"{vendas['cozinha']:g} cozinha · {vendas['bar']:g} bar",
                delta_color="off", delta_arrow="off", border=True,
            )
        elif dia["ontem_fechado"]:
            st.metric(f"Venda de ontem ({ontem})", "Fechado", border=True,
                      help="O dia foi marcado como sem movimento.")
        else:
            st.metric(f"Venda de ontem ({ontem})", "Falta lançar", delta="pendente",
                      delta_color="inverse", delta_arrow="off", border=True)
            _atalho("venda", PG_VENDA, "Lançar a venda", ":material/point_of_sale:")
    negativas = len(dia["producoes_no_negativo"])
    col2.metric(
        "Produções lançadas hoje", dia["lancados_hoje"]["producoes"],
        delta=f"{negativas} no negativo" if negativas else "nenhuma no negativo",
        delta_color="inverse" if negativas else "normal", delta_arrow="off", border=True,
        help="Produção no negativo: os pratos já gastaram e ela não foi lançada.",
    )
    col3.metric(
        "Compras lançadas hoje", dia["lancados_hoje"]["compras"],
        delta=f"{len(dia['comprar'])} para repor" if dia["comprar"] else "nada para repor",
        delta_color="inverse" if dia["comprar"] else "normal", delta_arrow="off",
        border=True,
    )
    if dia["dias_sem_contagem"] is None:
        col4.metric("Última contagem", "nunca", border=True)
    else:
        quando = ("hoje" if dia["contou_hoje"]
                  else f"há {dia['dias_sem_contagem']} d")
        col4.metric(
            "Última contagem", quando, delta=_data_br(dia["ultima_contagem"]),
            delta_color="off", delta_arrow="off", border=True,
            help="O ideal é reconciliar com uma contagem física 1x por mês.",
        )

    esquerda, direita = st.columns(2)
    with esquerda.container(border=True):
        st.markdown("**:material/soup_kitchen: Lançar produção**")
        if dia["producoes_no_negativo"]:
            st.caption(
                "Os pratos já gastaram e a produção não foi lançada. Lance o que "
                "foi feito, ou o saldo continua caindo."
            )
            _tabela_curta(dia["producoes_no_negativo"],
                          {"insumo": "Produção", "estoque_atual": "Saldo",
                           "unidade_medida": "Un."})
            _atalho("producao", PG_PRODUCAO, "Lançar produção", ":material/soup_kitchen:")
        else:
            st.success("Nenhuma produção no negativo.", icon=":material/check_circle:")
    with direita.container(border=True):
        st.markdown("**:material/shopping_cart: Comprar ou conferir**")
        if dia["comprar"]:
            st.caption(
                f"Negativo, abaixo do mínimo ou acabando em até "
                f"{crud.DIAS_PARA_COMPRAR} dias pelo consumo da última semana. "
                "Negativo costuma ser compra não lançada."
            )
            _tabela_curta(dia["comprar"],
                          {"insumo": "Insumo", "estoque_atual": "Saldo",
                           "unidade_medida": "Un.", "motivo": "Por quê"})
        else:
            st.success("Nada acabando nos próximos dias.", icon=":material/check_circle:")
    if vendas["pratos"]:
        with st.expander(f"O que mais saiu ontem ({ontem})", icon=":material/trophy:"):
            _tabela_curta(vendas["pratos"][:10],
                          {"prato": "Prato", "setor": "Setor", "quantidade": "Qtd."},
                          maximo=10)


def pagina_dashboard():
    _titulo("inventory", "Controle de Estoque")
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

    _painel_do_dia()

    st.divider()
    st.subheader("Análise do período")
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
    _titulo("inventory_2", "Painel de Estoque")
    st.caption(
        "Estoque teórico atual de cada insumo, calculado a partir de compras, "
        "produções e vendas."
    )

    insumos = listar_insumos()
    if not insumos:
        st.info("Nenhum insumo cadastrado ainda. Vá em 'Insumos'.")
        return

    mostrar = st.segmented_control(
        "Mostrar", ["Todos", "Crus", "Produções"], default="Todos", key="painel_tipo",
    ) or "Todos"
    dados = crud.calcular_estoque_todos_insumos()
    if mostrar != "Todos":
        tipo = "producao" if mostrar == "Produções" else "cru"
        dados = [d for d in dados if d["tipo"] == tipo]
    if not dados:
        st.info("Nenhum insumo desse tipo.")
        return
    df = pd.DataFrame(dados)
    df["tipo"] = df["tipo"].map({"cru": "Cru", "producao": "Produção"})
    df = df.rename(columns={
        "tipo": "Tipo",
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
        {"Estoque atual": "{:.2f}", "Estoque mínimo": "{:.2f}"}
    )
    st.dataframe(estilo, width="stretch")

    alertas = df[df["Abaixo do mínimo?"]]
    if not alertas.empty:
        st.warning(f"⚠️ {len(alertas)} insumo(s) abaixo do estoque mínimo!")

    st.divider()
    st.caption(
        "Excluir um insumo diretamente daqui apaga também ficha técnica, produções, "
        "compras e contagens físicas ligadas a ele. Não tem como desfazer."
    )

    for item in dados:
        nome = item["insumo"]
        col1, col2, col3, col4 = st.columns([4, 2, 2, 1])
        with col1:
            st.write(f"**{nome}**")
        with col2:
            st.write(f"{item['estoque_atual']:.2f}")
        with col3:
            st.write(item["unidade_medida"])
        with col4:
            if st.button("🗑️", key=f"painel_del_{nome}", help=f"Excluir {nome}"):
                st.session_state["painel_excluir_pendente"] = nome
                st.rerun()

    pendente = st.session_state.get("painel_excluir_pendente")
    if pendente:
        st.warning(
            f"⚠️ Excluir **{pendente}** apaga também ficha técnica, produções, compras "
            f"e contagens físicas ligadas a ele. Não tem como desfazer."
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button(f"Sim, excluir '{pendente}' definitivamente",
                         icon=":material/delete_forever:"):
                crud.excluir_insumo(pendente)
                st.success(f"Insumo '{pendente}' excluído.")
                del st.session_state["painel_excluir_pendente"]
                st.rerun()
        with col2:
            if st.button("Cancelar"):
                del st.session_state["painel_excluir_pendente"]
                st.rerun()


# ---------- Saída de Estoque por Período ----------

# As vendas são lançadas dia a dia, à mão, porque a Zig não expõe API. Um
# dia isolado não responde nada; a pergunta real é "quanto saiu do estoque
# nesta semana", feita na segunda de manhã. Por isso o padrão da tela é a
# semana corrente, contada a partir da segunda-feira.

def _intervalo_do_periodo(rotulo: str, hoje: datetime.date):
    segunda = crud.segunda_da_semana(hoje)
    if rotulo == "Esta semana":
        return segunda, hoje
    if rotulo == "Semana passada":
        return segunda - datetime.timedelta(days=7), segunda - datetime.timedelta(days=1)
    if rotulo == "Últimos 7 dias":
        return hoje - datetime.timedelta(days=6), hoje
    return hoje - datetime.timedelta(days=29), hoje


PERIODOS = ["Esta semana", "Semana passada", "Últimos 7 dias", "Últimos 30 dias"]


def _escolher_periodo():
    """Atalhos de período mais a opção de digitar as datas na mão."""
    hoje = crud.hoje()
    rotulo = st.segmented_control(
        "Período", PERIODOS + ["Escolher datas"], default="Esta semana",
        key="saida_periodo",
    ) or "Esta semana"

    if rotulo != "Escolher datas":
        return _intervalo_do_periodo(rotulo, hoje)

    escolhido = st.date_input(
        "De / até",
        value=(crud.segunda_da_semana(hoje), hoje),
        max_value=hoje,
        key="saida_datas",
    )
    # Enquanto a pessoa está escolhendo, o date_input de intervalo devolve
    # só a primeira data. Aí ainda não há período para calcular.
    if not isinstance(escolhido, (tuple, list)) or len(escolhido) != 2:
        return None, None
    return escolhido[0], escolhido[1]


def _grafico_dia_a_dia(dados):
    df = pd.DataFrame(dados)
    df["data"] = pd.to_datetime(df["data"])
    grafico = (
        alt.Chart(df)
        .mark_bar(color=COR, cornerRadiusEnd=3)
        .encode(
            x=alt.X("data:T", title=None),
            y=alt.Y("pratos_vendidos:Q", title="Pratos vendidos"),
            tooltip=[
                alt.Tooltip("data:T", title="Data", format="%d/%m/%Y"),
                alt.Tooltip("pratos_vendidos:Q", title="Pratos"),
            ],
        )
        .properties(height=240)
    )
    st.altair_chart(grafico, width="stretch")


def _aviso_de_buracos(buracos, dias):
    """Dia sem lançamento não dá erro — some do consumo e infla o estoque."""
    if not buracos:
        st.success(
            f"Todos os {dias} dia(s) do período têm venda lançada.",
            icon=":material/task_alt:",
        )
        return
    lista = ", ".join(_data_br(d) for d in buracos[:10])
    resto = f" (+{len(buracos) - 10})" if len(buracos) > 10 else ""
    st.warning(
        f"**{len(buracos)} de {dias} dia(s) sem venda lançada**: {lista}{resto}. "
        "Se o restaurante abriu nesses dias, o consumo abaixo está menor que o "
        "real e o estoque teórico, maior.",
        icon=":material/event_busy:",
    )


def pagina_saida():
    _titulo("trending_down", "Saída de Estoque no Período")
    st.caption(
        "As vendas são lançadas dia a dia. Aqui elas são somadas para "
        "responder a pergunta da segunda-feira: quanto saiu do estoque."
    )

    if not listar_insumos():
        st.info("Nenhum insumo cadastrado ainda. Vá em 'Insumos'.")
        return

    inicio, fim = _escolher_periodo()
    if inicio is None:
        st.info("Escolha as duas datas do período.")
        return
    if inicio > fim:
        st.error("A data inicial é depois da final.")
        return

    inicio_iso, fim_iso = str(inicio), str(fim)
    st.caption(f"De {_data_br(inicio_iso)} até {_data_br(fim_iso)}")

    # A saída do bar é a venda dos drinks mais o que as caldas, o xarope e a
    # espuma gastaram; a da cozinha, o mesmo com pratos e molhos. "Todos" é
    # o restaurante inteiro, como sempre foi.
    setor = None
    if "bar" in crud.setores_dos_pratos().values():
        escolha = st.radio(
            "Setor", [TODOS_OS_SETORES] + list(crud.SETORES.values()),
            horizontal=True, key="saida_setor",
            help="Bar: o que os drinks vendidos e os preparos do bar tiraram do "
                 "estoque. Cozinha: o mesmo com pratos e molhos.",
        )
        setor = {rotulo: cod for cod, rotulo in crud.SETORES.items()}.get(escolha)

    resumo = crud.resumo_do_periodo(inicio_iso, fim_iso, setor)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Pratos vendidos", int(resumo["pratos_vendidos"]), border=True)
    col2.metric("Insumos movimentados", resumo["insumos_movimentados"], border=True)
    col3.metric(
        "Dias lançados",
        f"{resumo['dias_lancados']}/{resumo['dias']}",
        border=True,
        help="Dias do período com pelo menos uma venda lançada.",
    )
    col4.metric("Compras no período", resumo["compras_lancadas"], border=True)

    _aviso_de_buracos(resumo["dias_sem_lancamento"], resumo["dias"])

    saidas = crud.saida_por_periodo(inicio_iso, fim_iso, setor)
    if not saidas:
        st.info(
            "Nenhuma venda lançada neste período — não há saída de estoque "
            "para mostrar."
        )
        return

    st.divider()
    aba_insumos, aba_pratos, aba_dias = st.tabs(
        ["Por insumo", "Por prato", "Dia a dia"]
    )

    with aba_insumos:
        st.caption(
            "Quanto de cada insumo saiu no período (vendas × ficha técnica), "
            "e quanto ainda resta em estoque."
        )
        df = pd.DataFrame(saidas)
        df["Status"] = df.apply(
            lambda linha: "🟠 Abaixo do mínimo" if linha["abaixo_do_minimo"] else "🟢 Ok",
            axis=1,
        )
        visivel = df[[
            "insumo", "saida", "unidade_medida", "media_diaria",
            "estoque_atual", "estoque_minimo", "Status",
        ]].rename(columns={
            "insumo": "Insumo",
            "saida": "Saiu no período",
            "unidade_medida": "Un.",
            "media_diaria": "Média/dia",
            "estoque_atual": "Estoque atual",
            "estoque_minimo": "Mínimo",
        })
        st.dataframe(
            visivel,
            width="stretch",
            hide_index=True,
            column_config={
                "Saiu no período": st.column_config.NumberColumn(format="%.2f"),
                "Média/dia": st.column_config.NumberColumn(format="%.2f"),
                "Estoque atual": st.column_config.NumberColumn(format="%.1f"),
                "Mínimo": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        st.download_button(
            "Baixar em CSV",
            data=visivel.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"saida-estoque-{setor or 'todos'}-{inicio_iso}-a-{fim_iso}.csv",
            mime="text/csv",
            icon=":material/download:",
        )

    with aba_pratos:
        st.caption("Quais pratos geraram essa saída.")
        pratos = crud.pratos_vendidos_no_periodo(inicio_iso, fim_iso, setor)
        if pratos:
            st.dataframe(
                pd.DataFrame(pratos).rename(
                    columns={"prato": "Prato", "vendidos": "Vendidos"}
                ),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("Sem vendas no período.")

    with aba_dias:
        st.caption("Quanto cada dia do período pesou.")
        por_dia = crud.vendas_por_dia_no_periodo(inicio_iso, fim_iso, setor)
        if por_dia:
            _grafico_dia_a_dia(por_dia)
            tabela = pd.DataFrame(por_dia)
            tabela["data"] = tabela["data"].map(_data_br)
            st.dataframe(
                tabela.rename(columns={"data": "Data", "pratos_vendidos": "Pratos"}),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("Sem vendas no período.")


# ---------- Cadastrar Insumo ----------

def _estoques_minimos(insumos):
    """Define o estoque mínimo de vários insumos de uma vez.

    O mínimo é o que faz o sistema avisar antes de faltar: é ele que pinta
    o semáforo do painel e dispara o alerta da barra lateral. Com o mínimo
    em zero, esse aviso nunca acontece e o sistema vira só um registro do
    passado. Definir um a um, em mais de cem insumos, é uma tarefa que na
    prática não é feita — daí a tabela.
    """
    st.subheader("Estoque mínimo")

    dados = crud.calcular_estoque_todos_insumos()
    sem_minimo = [d for d in dados if not d["estoque_minimo"]]
    if sem_minimo:
        st.warning(
            f"{len(sem_minimo)} de {len(dados)} insumo(s) estão com mínimo zero. "
            "Enquanto estiverem assim, o painel nunca vai avisar que eles "
            "estão acabando.",
            icon=":material/notifications_off:",
        )

    with st.expander("Definir mínimos em lote", expanded=bool(sem_minimo)):
        st.caption(
            "Preencha só o que quiser mudar; o que ficar em branco continua "
            "como está. O consumo médio por dia ajuda a escolher o número — "
            "um mínimo razoável cobre o prazo de entrega do fornecedor."
        )
        cobertura = {c["insumo"]: c for c in crud.cobertura_estoque(30)}
        linhas = [
            {
                "Insumo": d["insumo"],
                "Un.": d["unidade_medida"],
                "Estoque": d["estoque_atual"],
                "Consumo/dia": cobertura.get(d["insumo"], {}).get("consumo_medio_diario", 0),
                "Mínimo atual": d["estoque_minimo"],
                "Novo mínimo": None,
            }
            for d in dados
        ]
        valores = _tabela_em_lote(
            linhas, "Insumo", "Novo mínimo", "Novo mínimo", "minimos",
            "%.2f", "Filtrar insumo",
        )

        itens = _como_itens(valores, "insumo", "estoque_minimo")
        if not itens:
            st.caption("Nenhum mínimo preenchido ainda.")
            return

        st.write(f"**{len(itens)} insumo(s) preenchido(s).**")
        if st.button("💾 Gravar mínimos", type="primary", key="gravar_minimos"):
            try:
                total = crud.atualizar_estoques_minimos(itens)
            except Exception as e:
                st.error(f"Nada foi gravado: {e}")
                return
            st.success(f"{total} mínimo(s) atualizado(s).", icon=":material/check_circle:")
            # A coluna "Novo mínimo" volta a ficar em branco: os valores
            # já viraram o mínimo atual, mostrado na coluna ao lado.
            st.session_state.pop("minimos_valores", None)
            st.rerun()


def pagina_insumos():
    _titulo("nutrition", "Insumos")
    st.subheader("Cadastrar novo insumo")
    with st.form("form_insumo"):
        nome = st.text_input("Nome do insumo")
        tipo = st.radio(
            "Tipo", list(crud.TIPOS_DE_INSUMO), horizontal=True,
            format_func=crud.TIPOS_DE_INSUMO.get,
            help=(
                "Cru é o que se compra e entra pela nota. Produção é o que a "
                "cozinha faz (molho, base, carne porcionada): entra pela tela "
                "Lançar Produção e tira do estoque os ingredientes da receita."
            ),
        )
        unidade = st.selectbox("Unidade de medida", ["kg", "g", "l", "ml", "un"])
        minimo = st.number_input("Estoque mínimo", min_value=0.0, step=0.5)
        enviado = st.form_submit_button("Cadastrar")

    if enviado:
        if nome:
            try:
                crud.cadastrar_insumo(nome, unidade, minimo, tipo)
                recado = f"Insumo '{nome}' cadastrado!"
                if tipo == "producao":
                    recado += " Agora cadastre a receita dele em Ficha Técnica."
                st.success(recado)
            except Exception as e:
                st.error(f"Erro: {e}")
        else:
            st.error("Informe o nome do insumo.")

    insumos_existentes = listar_insumos()
    if not insumos_existentes:
        st.divider()
        st.info("Nenhum insumo cadastrado ainda.")
        return

    st.divider()
    _crus_e_producoes()

    st.divider()
    _estoques_minimos(insumos_existentes)

    st.divider()
    st.subheader("Excluir insumo")
    st.caption(
        "⚠️ Isso apaga o insumo e todo o histórico ligado a ele "
        "(ficha técnica, produções, compras e contagens). Não tem como desfazer."
    )

    insumo_excluir = st.selectbox("Selecione o insumo para excluir", insumos_existentes)
    confirmar = st.checkbox(f"Confirmo que quero excluir '{insumo_excluir}' permanentemente")
    if st.button("Excluir insumo", icon=":material/delete:", disabled=not confirmar):
        try:
            crud.excluir_insumo(insumo_excluir)
            st.success(f"Insumo '{insumo_excluir}' excluído.")
            st.rerun()
        except Exception as e:
            st.error(f"Erro: {e}")


def _crus_e_producoes():
    """As duas listas lado a lado e a troca de tipo de um insumo."""
    st.subheader("Crus e produções")
    st.caption(
        "A venda desconta o que está na ficha do prato. Se o prato leva um "
        "molho, sai o molho; os ingredientes do molho saem quando a produção "
        "dele é lançada."
    )
    tipos = crud.tipos_dos_insumos()
    unidades = unidades_dos_insumos()
    producoes = crud.listar_producoes()
    crus = sorted(n for n, t in tipos.items() if t == "cru")

    aba_crus, aba_producoes = st.tabs(
        [f"Crus ({len(crus)})", f"Produções ({len(producoes)})"]
    )
    with aba_crus:
        st.dataframe(
            pd.DataFrame([{"Insumo": n, "Unidade": unidades[n]} for n in crus]),
            hide_index=True, width="stretch", height=300,
        )
    with aba_producoes:
        if not producoes:
            st.info("Nenhuma produção cadastrada ainda.")
        else:
            st.dataframe(
                pd.DataFrame([
                    {
                        "Produção": p["nome"],
                        "Unidade": p["unidade_medida"],
                        "1 receita rende": p["rendimento"],
                        "Itens na receita": p["itens_na_ficha"],
                    }
                    for p in producoes
                ]),
                hide_index=True, width="stretch", height=300,
                column_config={
                    "1 receita rende": st.column_config.NumberColumn(format="%.3f"),
                },
            )
            sem_receita = [p["nome"] for p in producoes if not p["itens_na_ficha"]]
            if sem_receita:
                st.warning(
                    "Sem receita cadastrada, e por isso fora da tela de produção: "
                    + ", ".join(sem_receita) + ".",
                    icon=":material/receipt_long:",
                )

    with st.expander("Mudar um insumo de cru para produção, ou o contrário"):
        nome = st.selectbox("Insumo", sorted(tipos), key="tipo_insumo_nome")
        atual = tipos[nome]
        st.caption(f"Hoje: **{crud.TIPOS_DE_INSUMO[atual]}**.")
        novo = "cru" if atual == "producao" else "producao"
        if novo == "cru":
            st.warning(
                "Voltar para cru apaga a receita de produção dele. As produções "
                "já lançadas ficam no histórico.",
            )
        if st.button(f"Marcar como {crud.TIPOS_DE_INSUMO[novo].lower()}",
                     key="tipo_insumo_trocar"):
            try:
                crud.definir_tipo_do_insumo(nome, novo)
            except Exception as e:
                st.error(f"Erro: {e}")
            else:
                # O rerun redesenha as listas com o tipo novo; a confirmação
                # vai pela sessão para não sumir junto.
                st.session_state["tipo_insumo_recado"] = (
                    f"'{nome}' agora é {crud.TIPOS_DE_INSUMO[novo].lower()}."
                )
                st.rerun()
        recado = st.session_state.pop("tipo_insumo_recado", None)
        if recado:
            st.success(recado, icon=":material/check_circle:")

# ---------- Cadastrar Prato ----------

def pagina_pratos():
    _titulo("restaurant", "Pratos")
    st.subheader("Cadastrar novo prato")
    with st.form("form_prato"):
        nome = st.text_input("Nome do prato")
        setor = st.radio("Setor", list(crud.SETORES), format_func=crud.SETORES.get,
                         horizontal=True, help="Drink é do bar.")
        enviado = st.form_submit_button("Cadastrar")

    if enviado:
        if nome:
            try:
                crud.cadastrar_prato(nome, setor)
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
    if st.button("Excluir prato", icon=":material/delete:", disabled=not confirmar_prato):
        try:
            crud.excluir_prato(prato_excluir)
            st.success(f"Prato '{prato_excluir}' excluído.")
            st.rerun()
        except Exception as e:
            st.error(f"Erro: {e}")


# ---------- Ficha Técnica ----------

def _rotulos_de_insumo(excluir: str = None) -> dict[str, str]:
    """Rótulo mostrado na lista -> nome do insumo.

    A unidade vai no rótulo porque é o que evita digitar 150 onde a ficha
    espera 0,15: quem escolhe "Queijo mussarela (kg)" sabe em que escrever.
    """
    tipos = crud.tipos_dos_insumos()
    rotulos = {}
    for nome, unidade in sorted(unidades_dos_insumos().items()):
        if nome == excluir:
            continue
        marca = ", produção" if tipos.get(nome) == "producao" else ""
        rotulos[f"{nome} ({unidade}{marca})"] = nome
    return rotulos


def _editor_de_ficha(itens, chave, rotulo_quantidade, excluir=None):
    """Tabela da ficha com linhas que se acrescentam e apagam.

    Devolve (linhas prontas para gravar, problemas). Linha inteira em branco
    é ignorada — é a linha nova que o editor sempre oferece no fim.
    """
    rotulos = _rotulos_de_insumo(excluir)
    por_nome = {nome: rotulo for rotulo, nome in rotulos.items()}
    df = pd.DataFrame(
        [{"Insumo": por_nome.get(i["insumo"]), "Quantidade": i["quantidade"]} for i in itens],
        columns=["Insumo", "Quantidade"],
    )
    df["Quantidade"] = pd.to_numeric(df["Quantidade"], errors="coerce")
    tabela = st.data_editor(
        df,
        key=chave,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "Insumo": st.column_config.SelectboxColumn(
                "Insumo", options=list(rotulos), required=True, width="large",
            ),
            "Quantidade": st.column_config.NumberColumn(
                rotulo_quantidade, min_value=0.0, step=0.001, format="%.3f",
            ),
        },
    )

    linhas, problemas = [], []
    for _, linha in tabela.iterrows():
        rotulo = linha["Insumo"]
        quantidade = linha["Quantidade"]
        sem_insumo = rotulo is None or pd.isna(rotulo)
        sem_quantidade = quantidade is None or pd.isna(quantidade)
        if sem_insumo and sem_quantidade:
            continue
        if sem_insumo:
            problemas.append(f"Uma linha tem quantidade {quantidade:g} mas nenhum insumo.")
            continue
        nome = rotulos[rotulo]
        if sem_quantidade or quantidade <= 0:
            problemas.append(f"'{nome}' está sem quantidade.")
            continue
        linhas.append({"insumo": nome, "quantidade": float(quantidade)})

    nomes = [l["insumo"] for l in linhas]
    repetidos = sorted({n for n in nomes if nomes.count(n) > 1})
    if repetidos:
        problemas.append("Aparecem duas vezes: " + ", ".join(repetidos) + ". Deixe uma linha só.")
    return linhas, problemas


def _versao_do_editor(chave):
    """Muda a cada gravação, para o editor recomeçar a partir do que ficou gravado."""
    return st.session_state.get(f"{chave}_versao", 0)


def _gravado(chave, recado):
    st.session_state[f"{chave}_versao"] = _versao_do_editor(chave) + 1
    st.session_state[f"{chave}_recado"] = recado
    st.rerun()


def _recado_gravado(chave):
    recado = st.session_state.pop(f"{chave}_recado", None)
    if recado:
        st.success(recado, icon=":material/check_circle:")


def pagina_ficha_tecnica():
    _titulo("receipt_long", "Ficha Técnica")
    st.caption(
        "A ficha do **prato** diz o que 1 porção vendida tira do estoque. A "
        "ficha da **produção** diz o que 1 receita de molho, base ou porcionado "
        "gasta — é ela que tira o cru do estoque, quando a produção é lançada."
    )

    tipo = st.segmented_control(
        "Editar a ficha de", ["Prato", "Produção"], default="Prato", key="ficha_tipo",
    ) or "Prato"

    if tipo == "Prato":
        _ficha_de_prato()
    else:
        _ficha_de_producao()


def _ficha_de_prato():
    pratos = listar_pratos()
    if not pratos:
        st.info("Cadastre um prato antes, na tela Pratos.")
        return

    prato = st.selectbox("Prato", pratos, key="ficha_prato")
    chave = "ficha_prato_editor"
    _recado_gravado(chave)

    st.caption(
        "Para acrescentar, use a linha em branco no fim da tabela. Para tirar, "
        "marque a linha pela caixa da esquerda e apague com a lixeira. Nada "
        "muda no estoque até você clicar em Gravar."
    )
    linhas, problemas = _editor_de_ficha(
        crud.ficha_do_prato(prato),
        f"{chave}_{prato}_{_versao_do_editor(chave)}",
        "Por porção",
    )

    for problema in problemas:
        st.error(problema)
    if not linhas and not problemas:
        st.warning(
            "Ficha vazia: gravar assim faz a venda deste prato não descontar nada.",
            icon=":material/warning:",
        )

    if st.button("💾 Gravar ficha do prato", type="primary", disabled=bool(problemas)):
        try:
            total = crud.salvar_ficha_do_prato(prato, linhas)
        except Exception as e:
            st.error(f"Nada foi gravado: {e}")
            return
        _gravado(chave, f"Ficha de '{prato}' gravada com {total} insumo(s).")


def _ficha_de_producao():
    producoes = crud.listar_producoes()
    if not producoes:
        st.info(
            "Nenhuma produção cadastrada. Cadastre o molho ou a base na tela "
            "Insumos, com o tipo Produção, ou importe a planilha de produção."
        )
        return

    nomes = [p["nome"] for p in producoes]
    producao = st.selectbox("Produção", nomes, key="ficha_producao")
    ficha = crud.ficha_da_producao(producao)
    unidade = ficha["unidade_medida"]
    chave = "ficha_producao_editor"
    _recado_gravado(chave)

    usado_em = crud.onde_o_insumo_e_usado(producao)
    if usado_em:
        st.caption("Usado em: " + ", ".join(usado_em) + ".")
    else:
        st.caption("Nenhum prato ou produção usa este item ainda.")

    versao = _versao_do_editor(chave)
    rendimento = st.number_input(
        f"Quanto 1 receita rende ({unidade})",
        min_value=0.0, step=0.1, format="%.3f",
        value=float(ficha["rendimento"] or 0),
        key=f"ficha_rendimento_{producao}_{versao}",
        help=(
            "Só serve para já vir preenchido na tela de produção. O que sai "
            "do estoque é a receita abaixo vezes o número de receitas feitas."
        ),
    )
    st.caption(
        "Ingredientes de **1 receita**, na unidade de cada insumo. Uma produção "
        "pode levar outra (o molho de queijo leva bechamel)."
    )
    linhas, problemas = _editor_de_ficha(
        ficha["itens"], f"{chave}_{producao}_{versao}", "Por receita", excluir=producao,
    )

    if rendimento <= 0:
        problemas.append("Informe quanto 1 receita rende.")
    for problema in problemas:
        st.error(problema)
    if not linhas and not problemas:
        st.warning(
            "Receita vazia: sem ela, esta produção não pode ser lançada.",
            icon=":material/warning:",
        )

    if st.button("💾 Gravar receita", type="primary", disabled=bool(problemas)):
        try:
            total = crud.salvar_ficha_da_producao(producao, linhas, rendimento)
        except Exception as e:
            st.error(f"Nada foi gravado: {e}")
            return
        _gravado(chave, f"Receita de '{producao}' gravada com {total} ingrediente(s).")

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
    _titulo("upload", "Importar Ficha Técnica")
    st.caption(
        "Envie as planilhas de ficha técnica e o sistema cadastra insumo, prato, "
        "produção e receita de uma vez. Nada é gravado antes de você conferir a prévia."
    )
    st.info(
        "Depois da primeira importação, a fonte da verdade é o sistema: ajuste "
        "fichas na tela Ficha Técnica. Importar de novo substitui a ficha de cada "
        "prato e de cada produção da planilha, **inclusive o que foi editado à mão**.",
        icon=":material/info:",
    )

    aba_cozinha, aba_bar, aba_fria = st.tabs(["🍳 Cozinha", "🍸 Bar", "🥩 Cozinha fria"])
    with aba_cozinha:
        _importar_ficha_da_cozinha()
    with aba_bar:
        _importar_ficha_do_bar()
    with aba_fria:
        _separar_cozinha_fria()


def _separar_cozinha_fria():
    """Peça e porcionado viram itens separados (ver cozinha_fria.py)."""
    st.caption(
        "A carne limpa e porcionada na cozinha fria vira **produção**: a peça "
        "comprada continua como insumo, o porcionado vira um item à parte, os "
        "pratos passam a descontar o porcionado, e a peça sai quando o "
        "porcionamento é lançado em *Lançar Produção* (1 receita = 1 kg de "
        "peça). A perda da limpeza deixa de sumir na contagem. Bombom de "
        "alcatra, carne do fondue, filé aperitivo e frango do fondue têm "
        "produção própria, separada do porcionado comum da peça."
    )
    recado = st.session_state.pop("fria_recado", None)
    if recado:
        st.success(recado, icon=":material/check_circle:")
    try:
        plano = cozinha_fria.montar_plano()
    except Exception as e:
        st.error(f"Não consegui montar a separação: {e}")
        return

    if plano["problemas"]:
        st.error("Não dá para gravar ainda:\n\n- " + "\n- ".join(plano["problemas"]))
        return
    if not cozinha_fria.ha_o_que_fazer(plano):
        st.success(
            "A cozinha fria já está separada: "
            + ", ".join(p["nome"] for p in plano["producoes"]) + ".",
            icon=":material/done_all:",
        )
        return

    st.dataframe(
        pd.DataFrame([
            {
                "Produção": p["nome"],
                "Consome (por receita)": f"1 kg de {p['peca']}",
                "Situação": "já existe" if p["existe"] and p["tipo_atual"] == "producao"
                else "vira produção" if p["existe"] else "nova",
            }
            for p in plano["producoes"]
        ]),
        hide_index=True, width="stretch",
    )
    st.info(
        "O rendimento é **1 kg por kg de peça**: cada pacote feito é 1 kg. Se "
        "a balança disser outra coisa, corrija *Quanto rendeu* na hora de "
        "lançar; o número fixo fica em Ficha Técnica → Produção.",
        icon=":material/scale:",
    )
    trocas = plano["fichas_de_prato"] + plano["fichas_de_producao"]
    if trocas:
        with st.expander(f"Fichas que passam a descontar o porcionado ({len(trocas)})"):
            st.dataframe(
                pd.DataFrame([
                    {"Prato ou receita": dono, "Antes": cru, "Depois": destino,
                     "Quantidade": quantidade}
                    for dono, cru, destino, quantidade in trocas
                ]),
                hide_index=True, width="stretch",
            )
    if plano["linhas_da_contagem"]:
        with st.expander(
            f"Linhas da contagem que vão para o porcionado ({len(plano['linhas_da_contagem'])})"
        ):
            st.dataframe(
                pd.DataFrame([
                    {"Linha": descricao, "Antes": de, "Depois": para}
                    for descricao, de, para in plano["linhas_da_contagem"]
                ]),
                hide_index=True, width="stretch",
            )
    if plano["contagens_a_mover"]:
        with st.expander(
            f"O que já foi contado nessas linhas muda junto ({len(plano['contagens_a_mover'])})"
        ):
            st.caption(
                "O total gravado de cada insumo nesses dias é refeito a partir "
                "das linhas, para o corte novo começar com o que foi contado nele."
            )
            st.dataframe(
                pd.DataFrame([
                    {"Dia": _data_br(data), "Linha": descricao, "Contado": quantidade,
                     "Saía de": de, "Passa para": para}
                    for data, descricao, quantidade, de, para in plano["contagens_a_mover"]
                ]),
                hide_index=True, width="stretch",
            )
    if plano["cortes_sem_prato"]:
        st.warning(
            "Nenhum prato cita " + ", ".join(f"**{c}**" for c in plano["cortes_sem_prato"])
            + ". A produção é criada, mas só sai do estoque quando algum prato "
            "a citar: acrescente na ficha do prato em Ficha Técnica.",
            icon=":material/warning:",
        )
    st.info(
        "Depois disto, **todo porcionamento precisa ser lançado** em Lançar "
        "Produção, como os molhos: sem ele, o porcionado vai para negativo "
        "conforme os pratos saem, e a peça fica parada no estoque.",
        icon=":material/soup_kitchen:",
    )
    if st.button("🥩 Separar a cozinha fria", type="primary", key="fria_aplicar"):
        try:
            feito = cozinha_fria.aplicar_plano(plano)
        except Exception as e:
            st.error(f"Nada foi gravado: {e}")
            return
        st.session_state["fria_recado"] = (
            f"{feito['producoes_criadas']} produção(ões) criada(s), "
            f"{feito['viraram_producao']} insumo(s) viraram produção, "
            f"{feito['fichas_trocadas']} linha(s) de ficha trocada(s), "
            f"{feito['linhas_remapeadas']} linha(s) da contagem remapeada(s) e "
            f"{feito['totais_refeitos']} total(is) contado(s) refeito(s)."
        )
        st.rerun()


def _importar_ficha_do_bar():
    """A planilha do bar: drinks viram pratos do setor bar, preparos viram produção."""
    st.caption(
        "A planilha de fichas do bar (*Ficha tecnica bar*, ou a *Preparos bar "
        "villa* para as caldas, o xarope e a espuma). Cada aba de drink, dose, "
        "garrafa, suco ou combo vira um prato do bar; caldas, xarope, espuma e "
        "chocolate quente viram produção do bar. A dose da planilha está em "
        "litro e o estoque conta garrafa e lata: a conversão usa o volume "
        "escrito no nome do insumo. Garrafa e combo descontam a garrafa inteira."
    )
    st.caption(
        "Junto com a planilha entram os **refrigerantes** da folha de contagem "
        "(um prato por refrigerante, que desconta 1 unidade) e a ligação dos "
        "produtos da Zig que ainda estão sem prato."
    )
    arquivo = st.file_uploader("Ficha do bar (drinks e preparos)", type=["xlsx"],
                               key="up_ficha_bar")
    if arquivo is not None:
        try:
            st.session_state["ficha_planilha_bar"] = bar_import.ler_planilha(arquivo)
        except Exception as e:
            st.error(f"Não consegui ler a planilha do bar: {e}")
    receitas = st.session_state.get("ficha_planilha_bar")
    if not receitas:
        st.info("Envie a planilha do bar para ver a prévia.")
        return
    plano = bar_import.montar_plano(receitas)
    if not plano["fichas"] and not plano["producoes"]:
        st.error("Não encontrei nenhuma ficha preenchida nessa planilha.")
        return
    _previa_e_gravacao(plano, "bar", ("ficha_planilha_bar",))


def _extras_do_bar(plano):
    """O que só a importação do bar faz: refrigerantes, Zig e o que saiu."""
    if plano.get("refrigerantes"):
        with st.expander(f"🥤 {len(plano['refrigerantes'])} refrigerante(s) da folha de contagem"):
            st.caption(
                "Cada um vira um prato do bar com o mesmo nome do insumo, que "
                "desconta 1 unidade por venda. Coca lata e Coca Zero lata ficam "
                "de fora: saíram da contagem."
            )
            st.write(", ".join(plano["refrigerantes"]))
    if plano.get("zig"):
        with st.expander(f"🔗 {len(plano['zig'])} produto(s) da Zig que passam a ter prato"):
            st.caption(
                "Hoje estão sem prato (marcados para não controlar). Depois "
                "disto, a importação de vendas da Zig desconta o estoque deles."
            )
            st.dataframe(
                pd.DataFrame([
                    {"Produto na Zig": z["nome_produto"], "SKU": z["sku"], "Prato": z["prato"]}
                    for z in plano["zig"]
                ]),
                hide_index=True, width="stretch",
            )
    for producao in plano.get("remover", []):
        st.warning(
            f"**{producao['nome']}** será excluída ({producao['motivo']}), com a "
            "receita e o que tiver sido lançado dela.",
            icon=":material/delete:",
        )


def _importar_ficha_da_cozinha():
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
            "viram insumo cru, sem receita, em vez de produção."
        )

    plano = _plano_da_ficha()
    if plano is None or not plano["fichas"]:
        st.error("Não encontrei nenhuma ficha técnica preenchida nessas planilhas.")
        return
    _previa_e_gravacao(plano, "cozinha", ("ficha_planilha_prato", "ficha_planilha_producao",
                                          "ficha_de_para_extra"))


def _previa_e_gravacao(plano, prefixo, chaves_para_limpar):
    """A prévia do plano de importação e o botão de gravar, da cozinha ou do bar.

    `prefixo` separa os widgets das duas abas, que estão na mesma página.
    """
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Pratos", len(plano["pratos"]),
                delta=f"{len(plano['pratos_novos'])} novos", border=True)
    col2.metric("Insumos", len(plano["insumos"]),
                delta=f"{len(plano['insumos_novos'])} novos", border=True)
    col3.metric("Produções", len(plano["producoes"]), border=True)
    col4.metric("Linhas de ficha", len(plano["fichas"]), border=True)
    col5.metric("Pontos de atenção", len(plano["avisos"]), border=True)

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
        with st.expander(f"⚠️ {len(plano['avisos'])} ponto(s) de atenção na leitura",
                         expanded=prefixo == "bar"):
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

    with st.expander(f"🍳 {len(plano['producoes'])} produção(ões) com receita própria"):
        if plano["viram_producao"]:
            st.caption(
                "Já existiam como insumo cru (a contagem criou) e passam a ser "
                "produção: " + ", ".join(plano["viram_producao"]) + "."
            )
        st.dataframe(
            pd.DataFrame([
                {"Produção": p["nome"], "Unidade": p["unidade"],
                 "1 receita rende": p["rendimento"], "Ingredientes": len(p["itens"]),
                 "Aba": p["aba"]}
                for p in plano["producoes"]
            ]),
            hide_index=True, width="stretch",
        )
        st.dataframe(
            pd.DataFrame([
                {"Produção": p["nome"], "Ingrediente": i["insumo"],
                 "Por receita": i["quantidade"], "Unidade": plano["insumos"][i["insumo"]]}
                for p in plano["producoes"] for i in p["itens"]
            ]),
            hide_index=True, width="stretch", height=300,
        )

    if prefixo == "bar":
        _extras_do_bar(plano)

    with st.expander(f"🍽️ {len(plano['pratos_novos'])} prato(s) que serão criados"):
        st.dataframe(pd.DataFrame({"Prato": plano["pratos_novos"]}),
                     hide_index=True, width="stretch")

    with st.expander(f"📋 {len(plano['fichas'])} linha(s) de ficha de prato"):
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
            "Passar esses insumos para a unidade da planilha", value=True,
            key=f"{prefixo}_corrigir_unidades",
        )

    substituir = st.checkbox(
        "Substituir a ficha atual dos pratos e das produções importados",
        value=True,
        help=(
            "Recomendado. Sem isso, um insumo que saiu da receita continuaria "
            "sendo descontado para sempre."
        ),
        key=f"{prefixo}_substituir",
    )
    confirmado = st.checkbox(
        f"Confirmo a importação de {len(plano['fichas'])} linha(s) de ficha técnica",
        key=f"{prefixo}_confirmado",
    )
    if st.button("📥 Cadastrar tudo", type="primary", disabled=not confirmado,
                 key=f"{prefixo}_cadastrar"):
        try:
            feito = ficha_import.aplicar_plano(
                plano, substituir, corrigir_unidades,
                depois=(lambda conn: bar_import.gravar_extras(conn, plano))
                if prefixo == "bar" else None,
            )
        except Exception as e:
            st.error(f"Erro ao gravar: {e}")
            return
        recado = (
            f"{feito['insumos']} insumo(s), {feito['pratos']} prato(s), "
            f"{feito['fichas']} linha(s) de ficha de prato e {feito['producoes']} "
            f"produção(ões) com {feito['linhas_producao']} ingrediente(s) cadastrados!"
        )
        if feito["unidades"]:
            recado += f" {feito['unidades']} unidade(s) de medida corrigida(s)."
        extras = feito.get("depois") or {}
        if extras.get("zig"):
            recado += f" {extras['zig']} produto(s) da Zig ligado(s) a prato."
        if extras.get("removidos"):
            recado += f" {extras['removidos']} produção(ões) que saíram excluída(s)."
        st.success(recado)
        for chave_sessao in chaves_para_limpar:
            st.session_state.pop(chave_sessao, None)


# ---------- Lançar Compra ----------

def pagina_compra():
    _titulo("shopping_cart", "Lançar Compra")
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
        data = st.date_input("Data da compra", value=crud.hoje())
        fornecedor = st.text_input("Fornecedor (opcional)")
        enviado = st.form_submit_button("Registrar")

    if enviado:
        try:
            crud.registrar_compra(insumo, quantidade, str(data), fornecedor or None)
            st.success("Compra registrada!")
        except Exception as e:
            st.error(f"Erro: {e}")


# ---------- Importar Nota Fiscal ----------

def _arquivo_de_exemplo(rotulo: str, dados: bytes, nome: str, tipo: str):
    """Oferece um arquivo fictício para baixar, só na vitrine.

    Sem isso, quem abre as telas de importação na demonstração não tem o
    que subir, e elas são metade do projeto. As datas do arquivo são
    geradas na hora, relativas a hoje, para o lançamento cair dentro da
    janela de análise do dashboard.
    """
    if not MODO_DEMO:
        return
    st.download_button(
        rotulo, data=dados, file_name=nome, mime=tipo,
        icon=":material/download:",
        help="Arquivo fictício, para experimentar a importação.",
    )


def pagina_nfe():
    _titulo("upload_file", "Importar Nota Fiscal")
    st.caption(
        "Envie o arquivo XML da nota fiscal. Produtos já mapeados são "
        "lançados automaticamente; produtos novos você mapeia uma vez aqui, "
        "e da próxima vez que aparecerem numa nota já são reconhecidos sozinhos."
    )

    _arquivo_de_exemplo(
        "Baixar uma nota de exemplo", exemplos.nota_fiscal_xml(),
        "nota-fiscal-exemplo.xml", "application/xml",
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
    # Um SELECT para a nota inteira, em vez de um por item a cada clique.
    mapas = crud.mapeamentos_nfe(dados["fornecedor_cnpj"])
    itens_sem_mapa = [i for i in dados["itens"] if i["codigo_produto"] not in mapas]
    for item in dados["itens"]:
        mapeamento = mapas.get(item["codigo_produto"])
        if mapeamento:
            st.write(
                f"✅ **{item['descricao']}** → já mapeado para "
                f"*{mapeamento['insumo_nome']}* "
                f"({item['quantidade']} × fator {mapeamento['fator_conversao']} = "
                f"{item['quantidade'] * mapeamento['fator_conversao']:.2f})"
            )

    if itens_sem_mapa:
        st.warning(f"{len(itens_sem_mapa)} item(ns) ainda não mapeado(s). Mapeie abaixo:")
        if not insumos:
            st.error("Cadastre ao menos um insumo antes de mapear produtos da nota.")
            return
        # Uma tabela e um botão para a nota toda. Antes era um formulário
        # por item, e cada "Salvar" refazia a página inteira.
        tabela = st.data_editor(
            pd.DataFrame([
                {
                    "Código": i["codigo_produto"],
                    "Produto na nota": i["descricao"],
                    "Na nota": f"{i['quantidade']:g} {i['unidade']}",
                    "Insumo": None,
                    "Fator": 1.0,
                }
                for i in itens_sem_mapa
            ]),
            hide_index=True, width="stretch", key=f"nfe_mapa_{dados['numero_nota']}",
            disabled=["Código", "Produto na nota", "Na nota"],
            column_config={
                "Insumo": st.column_config.SelectboxColumn(options=insumos),
                "Fator": st.column_config.NumberColumn(
                    min_value=0.0001, step=0.1,
                    help="Nota → unidade do insumo. Deixe 1 se a unidade já bate "
                         "(ex.: caixa com 12 e insumo em unidade = 12).",
                ),
            },
        )
        escolhidos = [
            {
                "codigo_produto": linha["Código"],
                "descricao_produto": linha["Produto na nota"],
                "insumo": linha["Insumo"],
                "fator_conversao": 1.0 if pd.isna(linha["Fator"]) else float(linha["Fator"]),
            }
            for _, linha in tabela.iterrows()
            if isinstance(linha["Insumo"], str) and linha["Insumo"]
        ]
        if st.button(f"Salvar mapeamentos ({len(escolhidos)})", disabled=not escolhidos,
                     key="nfe_salvar_mapas"):
            try:
                salvos = crud.salvar_mapeamentos_nfe(dados["fornecedor_cnpj"], escolhidos)
            except Exception as e:
                st.error(f"Nada foi gravado: {e}")
            else:
                st.success(f"{salvos} produto(s) mapeado(s).")
                st.rerun()
    else:
        st.success("Todos os itens da nota já estão mapeados!")

    st.divider()
    # A mesma proteção da nota manual: a nota lançada duas vezes dobra o
    # estoque sem deixar rastro. Antes esta tela nem guardava o número.
    duplicada = crud.nota_ja_lancada(dados["numero_nota"], dados["fornecedor_nome"])
    confirmado = True
    if duplicada:
        st.warning(
            f"A nota **{dados['numero_nota']}** já tem {duplicada['itens']} item(ns) "
            f"lançado(s) em {_data_br(duplicada['data'])}. Lançar de novo vai somar "
            "tudo outra vez no estoque. Para desfazer um lançamento, use a tela "
            "*Compras Lançadas*.",
            icon=":material/warning:",
        )
        confirmado = st.checkbox("Conferi, quero lançar mesmo assim", key="nfe_confirma")

    # O teste de `confirmado` repete o disabled de propósito: o clique dado
    # antes de a nota aparecer como lançada ainda chega nesta execução.
    if st.button("📥 Lançar compras desta nota no estoque", type="primary",
                 disabled=not confirmado) and confirmado:
        try:
            lancados, nao_mapeados = nfe_import.processar_itens_nfe(
                dados, dados["fornecedor_cnpj"]
            )
        except Exception as e:
            st.error(f"Nada foi lançado: {e}")
            return
        if lancados:
            st.success(f"{len(lancados)} compra(s) lançada(s) no estoque!")
            for descricao, insumo_nome, qtd in lancados:
                st.write(f"- {descricao} → {insumo_nome}: +{qtd:.2f}")
        if nao_mapeados:
            st.warning(
                f"{len(nao_mapeados)} item(ns) ainda sem mapeamento não foram lançados. "
                "Mapeie-os acima e clique de novo."
            )
        st.session_state.pop("nfe_confirma", None)


# ---------- Lançar Nota Fiscal (manual) ----------

COLUNAS_DA_NOTA = ["Insumo", "Quantidade"]


def _itens_digitados(tabela) -> list[dict]:
    """Transforma a tabela editável em itens de compra, descartando linha vazia.

    A tabela nasce com linhas em branco e ganha outras conforme se digita,
    então linha sem insumo ou sem quantidade é rascunho, não item.
    """
    itens = []
    for _, linha in tabela.iterrows():
        insumo = linha["Insumo"]
        quantidade = linha["Quantidade"]
        # Célula vazia pode chegar como None ou como NaN — e NaN é truthy,
        # então testar só `not insumo` deixaria passar linha em branco.
        if pd.isna(insumo) or not insumo:
            continue
        if pd.isna(quantidade) or float(quantidade) <= 0:
            continue
        itens.append({"insumo": insumo, "quantidade": float(quantidade)})
    return itens


def pagina_nf_manual():
    _titulo("edit_note", "Lançar Nota Fiscal (manual)")
    st.caption(
        "Para a nota que chega sem XML: em papel, em PDF, ou do fornecedor "
        "que não manda o arquivo. Os itens são digitados aqui e entram no "
        "estoque do mesmo jeito que os da importação automática."
    )

    insumos = listar_insumos()
    if not insumos:
        st.info("Cadastre um insumo antes de lançar notas.")
        return

    unidades = unidades_dos_insumos()

    col1, col2, col3 = st.columns([2, 1, 1])
    fornecedor = col1.text_input("Fornecedor", key="nf_fornecedor")
    numero = col2.text_input("Número da nota", key="nf_numero")
    data = col3.date_input("Data da nota", value=crud.hoje(), key="nf_data")

    st.write("**Itens da nota**")
    st.caption(
        "Uma linha por item. A quantidade é na unidade em que o insumo é "
        "controlado — se a nota vem em caixa e o insumo é em kg, converta aqui."
    )

    # A tabela começa sem nenhuma linha, e não com uma linha em branco: o
    # Streamlit escreve "None" em célula vazia, e uma nota que abre com
    # "None / None" parece defeito. Com num_rows="dynamic" a linha de
    # acrescentar já fica ali embaixo, que é o convite certo.
    tabela = st.data_editor(
        pd.DataFrame({
            "Insumo": pd.Series([], dtype="object"),
            "Quantidade": pd.Series([], dtype="float64"),
        }),
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        key="nf_itens",
        column_config={
            "Insumo": st.column_config.SelectboxColumn(
                "Insumo", options=insumos, required=False, width="large"
            ),
            "Quantidade": st.column_config.NumberColumn(
                "Quantidade", min_value=0.0, step=0.5, format="%.3f"
            ),
        },
    )

    itens = _itens_digitados(tabela)
    if not itens:
        st.info("Preencha ao menos um item para lançar a nota.")
        return

    previa = pd.DataFrame([
        {
            "Insumo": item["insumo"],
            "Quantidade": item["quantidade"],
            "Un.": unidades.get(item["insumo"], ""),
        }
        for item in itens
    ])
    st.write(f"**Prévia — {len(itens)} item(ns)**")
    st.dataframe(previa, width="stretch", hide_index=True)

    # Nota já lançada é o erro mais caro desta tela: ela dobra o estoque
    # sem deixar rastro. O número da nota existe justamente para pegar isso.
    duplicada = None
    try:
        duplicada = crud.nota_ja_lancada(numero.strip(), fornecedor.strip() or None)
    except Exception as e:
        st.error(f"Não consegui conferir se esta nota já foi lançada: {e}")

    confirmado = True
    if duplicada:
        st.warning(
            f"A nota **{numero}** já tem {duplicada['itens']} item(ns) lançado(s) "
            f"em {_data_br(duplicada['data'])}. Lançar de novo vai somar tudo "
            "outra vez no estoque.",
            icon=":material/warning:",
        )
        confirmado = st.checkbox("Conferi, quero lançar mesmo assim", key="nf_confirma")

    if not numero.strip():
        st.caption(
            "Sem o número da nota o sistema não consegue avisar se ela já foi "
            "lançada. Vale preencher."
        )

    if st.button("📥 Lançar nota no estoque", type="primary", disabled=not confirmado):
        try:
            total = crud.registrar_compras_em_lote(
                itens,
                str(data),
                fornecedor=fornecedor.strip() or None,
                numero_nota=numero.strip() or None,
                observacao="Nota lançada manualmente",
            )
        except Exception as e:
            st.error(f"Nada foi lançado: {e}")
        else:
            st.success(
                f"{total} compra(s) lançada(s) em {_data_br(str(data))}.",
                icon=":material/check_circle:",
            )
            # Leitura de volta: o estoque mostrado vem do banco depois do
            # commit, então confirma que a nota entrou de verdade.
            estoques = {e["insumo"]: e for e in crud.calcular_estoque_todos_insumos()}
            depois = pd.DataFrame([
                {
                    "Insumo": item["insumo"],
                    "Entrou": item["quantidade"],
                    "Un.": unidades.get(item["insumo"], ""),
                    "Estoque agora": estoques.get(item["insumo"], {}).get("estoque_atual"),
                }
                for item in itens
            ])
            st.dataframe(depois, width="stretch", hide_index=True)
            st.caption("Gravado em " + database.descricao_do_backend() + ".")


# ---------- Lançar Venda ----------

def _ficha_do_prato(prato: str, quantidade: float):
    """Mostra o que a venda tira do estoque, antes e depois de lançar."""
    impacto = crud.impacto_da_venda(prato, quantidade)
    if not impacto:
        st.warning(
            f"**{prato}** não tem ficha técnica. Lançar esta venda registra o "
            "prato vendido, mas **não desconta nada do estoque** — monte a "
            "ficha em *Ficha Técnica* para o consumo passar a ser calculado.",
            icon=":material/warning:",
        )
        return

    linhas = ", ".join(
        f"{i['insumo']} {i['consumo']:g} {i['unidade_medida']}" for i in impacto[:6]
    )
    resto = f" (+{len(impacto) - 6} insumo(s))" if len(impacto) > 6 else ""
    st.caption(f"Sai do estoque: {linhas}{resto}")


# No fragmento, digitar na tabela refaz só a tabela, com os dados da última
# execução completa, sem ir ao banco (mesmo motivo da tabela da contagem).
@st.fragment
def _venda_em_lote(pratos, setores, com_ficha, lancado, data_iso):
    """A tela do dia a dia: todos os pratos numa tabela, um envio só.

    Lançar prato a prato, num formulário por vez, são dezenas de envios
    por dia — a operação não sobrevive a isso, e o dia acaba não sendo
    lançado. A tabela vem preenchida com o que já está gravado naquela
    data, então reabrir a tela mostra o estado atual e permite corrigir.

    Com drinks cadastrados, a tabela mostra um setor por vez (cozinha ou
    bar), e o que foi digitado nos dois é gravado junto.
    """
    if lancado:
        st.info(
            f"{len(lancado)} prato(s) já lançado(s) em {_data_br(data_iso)}. "
            "Os valores vêm preenchidos; gravar de novo corrige, não duplica.",
            icon=":material/history:",
        )

    st.write(
        "**Preencha o que vendeu.** Em branco = não mexe. "
        "**0** apaga o lançamento daquele prato no dia."
    )
    chave = f"venda_lote_{data_iso}"
    # Carregado aqui, de todos os setores, porque a tabela pode estar
    # mostrando um setor só.
    st.session_state.setdefault(
        f"{chave}_valores", {nome: float(qtd) for nome, qtd in lancado.items()}
    )
    setor = TODOS_OS_SETORES
    if "bar" in setores.values():
        setor = st.radio(
            "Setor", [TODOS_OS_SETORES] + list(crud.SETORES.values()),
            horizontal=True, key="venda_setor",
            help="O bar pode lançar os drinks e a cozinha os pratos, cada um no seu. "
                 "O que foi digitado no outro setor continua guardado.",
        )
    codigo = {rotulo: cod for cod, rotulo in crud.SETORES.items()}.get(setor)
    visiveis = [n for n in pratos if codigo is None or setores.get(n, "cozinha") == codigo]
    linhas = [{"Prato": nome, "Qtd.": lancado.get(nome)} for nome in visiveis]
    valores = _tabela_em_lote(
        linhas, "Prato", "Qtd.", "Qtd.", chave,
        "%d", "Filtrar prato", passo=1, grupo=setor,
    )

    itens = _como_itens(valores, "prato", "quantidade")
    if not itens:
        st.caption("Nenhuma venda preenchida ainda.")
        return

    total = sum(i["quantidade"] for i in itens)
    por_setor = {}
    for item in itens:
        rotulo = crud.SETORES.get(setores.get(item["prato"], "cozinha"), "Cozinha")
        por_setor[rotulo] = por_setor.get(rotulo, 0) + 1
    detalhe = " + ".join(f"{n} {rotulo.lower()}" for rotulo, n in sorted(por_setor.items()))
    st.write(f"**{len(itens)} prato(s) preenchido(s)** ({detalhe}) · {total:g} unidade(s).")

    sem_ficha = [i["prato"] for i in itens
                 if i["quantidade"] > 0 and i["prato"] not in com_ficha]
    if sem_ficha:
        st.warning(
            f"{len(sem_ficha)} prato(s) sem ficha técnica não vão descontar nada "
            "do estoque: " + ", ".join(sem_ficha[:8])
            + ("…" if len(sem_ficha) > 8 else ""),
            icon=":material/warning:",
        )

    if st.button("💾 Gravar vendas do dia", type="primary", key="venda_lote_gravar"):
        try:
            resultado = crud.lancar_vendas_em_lote(itens, data_iso)
        except Exception as e:
            st.error(f"Nada foi gravado: {e}")
            return
        _guardar_resultado(chave, valores, resultado)
        # A lista "Lançado em", no fim da página, fica fora do fragmento:
        # sem refazer a página inteira, ela mostraria o dia antes da gravação.
        st.rerun()

    resultado = _resultado_guardado(chave, valores)
    if resultado:
        st.success(
            f"{resultado['gravados']} prato(s) gravado(s) em {_data_br(data_iso)}"
            + (f", {resultado['apagados']} apagado(s)." if resultado["apagados"] else "."),
            icon=":material/check_circle:",
        )
        # Leitura de volta: o que a tela mostra agora vem do banco.
        confere = crud.vendas_do_dia(data_iso)
        if confere:
            df = pd.DataFrame(confere).rename(columns={"prato": "Prato", "quantidade": "Qtd."})
            st.dataframe(df, width="stretch", hide_index=True)
            st.caption(
                f"{len(confere)} prato(s) · {df['Qtd.'].sum():g} unidade(s) gravadas em "
                + database.descricao_do_backend() + "."
            )


def _venda_um_prato(pratos, data_iso):
    """Lançamento avulso, para corrigir ou completar um prato só."""
    prato = st.selectbox("Prato", pratos, key="venda_prato")

    try:
        ja_lancado = crud.total_vendido_no_dia(prato, data_iso)
    except Exception as e:
        st.error(f"Não consegui consultar o que já está lançado: {e}")
        return

    if ja_lancado:
        st.info(
            f"**{prato}** já tem **{ja_lancado:g}** lançado(s) em "
            f"{_data_br(data_iso)}.",
            icon=":material/history:",
        )

    with st.form("form_venda"):
        quantidade = st.number_input("Quantidade vendida", min_value=1, step=1, value=1)
        # 'Substituir' é o padrão de propósito. O lançamento manual é feito
        # olhando o total do dia no PDV, então o número digitado É o total —
        # e, sendo substituição, clicar duas vezes no botão dá o mesmo
        # resultado que clicar uma. Era exatamente assim que nascia o
        # lançamento em dobro que inflava o consumo.
        modo = st.radio(
            "O que fazer com o que já está lançado neste dia",
            ["Substituir o total do dia", "Somar ao que já está lançado"],
            horizontal=True,
            help=(
                "Substituir deixa o dia valendo exatamente o número digitado — "
                "é o modo seguro para relançar sem duplicar. Somar serve quando "
                "você está completando um lançamento parcial."
            ),
        )
        enviado = st.form_submit_button("Registrar", type="primary")

    if not enviado:
        _ficha_do_prato(prato, quantidade)
    else:
        try:
            # O total volta lido do banco, depois do commit: o que a tela
            # mostra é o que ficou gravado, não o que o formulário mandou.
            total = crud.lancar_venda(
                prato, int(quantidade), data_iso,
                substituir=modo.startswith("Substituir"),
            )
        except Exception as e:
            st.error(f"A venda **não** foi registrada: {e}")
        else:
            st.success(
                f"Gravado. **{prato}** em {_data_br(data_iso)}: "
                f"**{total:g}** unidade(s) no total do dia.",
                icon=":material/check_circle:",
            )
            _ficha_do_prato(prato, total)


def _dia_fechado(data_iso):
    """Folga não é esquecimento: marcar o dia tira ele do lembrete."""
    if data_iso >= crud.hoje().isoformat():
        return
    if data_iso in crud.dias_sem_movimento(data_iso, data_iso):
        st.info(
            f"{_data_br(data_iso)} está marcado como **dia em que o restaurante "
            "não abriu**, por isso não aparece no lembrete de venda pendente.",
            icon=":material/door_front:",
        )
        if st.button("Desfazer: o restaurante abriu", key="venda_desmarcar_fechado"):
            crud.desmarcar_dia_sem_movimento(data_iso)
            st.rerun()
    elif st.button(
        "🚪 O restaurante não abriu neste dia", key="venda_marcar_fechado",
        help="Tira o dia do lembrete de venda pendente. Use só para folga ou "
             "fechamento, não para dia que ainda falta lançar.",
    ):
        crud.marcar_dia_sem_movimento(data_iso)
        st.rerun()


def pagina_venda():
    _titulo("point_of_sale", "Lançar Venda do Dia")
    st.caption(
        "Digite quantos de cada prato foram vendidos, olhando o resumo do PDV. "
        "O número lançado aqui é o que desconta do estoque."
    )

    pratos = listar_pratos()
    if not pratos:
        st.info("Cadastre um prato antes de lançar vendas.")
        return

    pendentes = crud.vendas_pendentes()
    if pendentes:
        st.warning(
            f"**{len(pendentes)} dia(s) sem venda lançada:** "
            + ", ".join(_data_br(d) for d in pendentes)
            + ". Escolha a data abaixo para lançar. Se o restaurante não abriu, "
            "marque o dia como fechado no fim da página.",
            icon=":material/event_busy:",
        )

    data = st.date_input("Data da venda", value=crud.hoje(), key="venda_data")
    data_iso = str(data)

    aba_lote, aba_um = st.tabs(["O dia inteiro (tabela)", "Um prato"])
    with aba_lote:
        lancado = {v["prato"]: v["quantidade"] for v in crud.vendas_do_dia(data_iso)}
        _venda_em_lote(pratos, crud.setores_dos_pratos(), crud.pratos_com_ficha(),
                       lancado, data_iso)
    with aba_um:
        _venda_um_prato(pratos, data_iso)

    st.divider()
    st.subheader(f"Lançado em {_data_br(data_iso)}")
    do_dia = crud.vendas_do_dia(data_iso)
    if not do_dia:
        st.caption("Nenhuma venda lançada neste dia ainda.")
        _dia_fechado(data_iso)
    else:
        df = pd.DataFrame(do_dia).rename(
            columns={"prato": "Prato", "quantidade": "Qtd."}
        )
        st.dataframe(df, width="stretch", hide_index=True)
        st.caption(
            f"{len(do_dia)} prato(s) · {df['Qtd.'].sum():g} unidade(s) no dia. "
            "Gravado em " + database.descricao_do_backend() + "."
        )


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
            mapear, remover = [], []
            for (_, linha_antes), (_, linha_depois) in zip(antes.iterrows(), depois.iterrows()):
                escolha = linha_depois["Prato no sistema"]
                if linha_depois["Remover"]:
                    remover.append(linha_antes["SKU"])
                elif escolha and escolha != linha_antes["Prato no sistema"]:
                    mapear.append({
                        "sku": linha_antes["SKU"],
                        "nome_produto": linha_antes["Produto na Zig"],
                        "prato": None if escolha == NAO_CONTROLAR else escolha,
                    })

            if not mapear and not remover:
                st.info("Nada foi alterado.")
            else:
                try:
                    feito = crud.salvar_mapeamentos_zig(mapear, remover)
                except Exception as e:
                    st.error(f"Nada foi gravado: {e}")
                else:
                    st.success(f"{feito['salvos']} alterado(s), {feito['removidos']} removido(s).")
                    st.rerun()


def pagina_zig():
    _titulo("receipt", "Importar Vendas do PDV")
    st.caption(
        "Envie a planilha de vendas exportada da Zig. Cada produto é ligado uma "
        "vez a um prato do sistema e, nas próximas importações, já é reconhecido "
        "sozinho — no lugar de digitar prato a prato."
    )

    pratos = listar_pratos()
    _arquivo_de_exemplo(
        "Baixar um relatório de exemplo", exemplos.vendas_pdv_xlsx(),
        "vendas-pdv-exemplo.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
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
    cancelados = dados.get("cancelados") or []
    if cancelados:
        with st.expander(
            f"🚫 {len(cancelados)} item(ns) com desconto total ficaram de fora "
            "(prato cancelado, não dá baixa no estoque)"
        ):
            st.caption(
                "A Zig registra o cancelamento como venda com 100% de desconto. "
                "Esses itens não descontam nada do estoque. Desconto parcial e "
                "item de preço zero sem desconto (como o fondue da sequência) "
                "continuam contando normalmente."
            )
            st.dataframe(
                pd.DataFrame(cancelados).rename(columns={
                    "data": "Dia", "nome": "Produto",
                    "quantidade": "Qtd.", "cliente": "Mesa",
                }),
                width="stretch", hide_index=True,
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
                mapear = [
                    {
                        "sku": linha["SKU"],
                        "nome_produto": linha["Produto na Zig"],
                        "prato": None if linha["Prato no sistema"] == NAO_CONTROLAR
                        else linha["Prato no sistema"],
                    }
                    for _, linha in editado.iterrows()
                    if linha["Prato no sistema"]
                ]
                if not mapear:
                    st.info("Nenhum produto foi escolhido ainda.")
                else:
                    try:
                        feito = crud.salvar_mapeamentos_zig(mapear)
                    except Exception as e:
                        st.error(f"Nada foi gravado: {e}")
                    else:
                        st.success(f"{feito['salvos']} produto(s) mapeado(s)!")
                        st.rerun()

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

# ---------- Itens da Contagem ----------

def _editor_de_fatores(itens):
    """Onde se diz quanto vale cada unidade contada, em lote."""
    gravados = st.session_state.pop("fatores_gravados", None)
    if gravados:
        st.success(f"{gravados} fator(es) gravado(s).", icon=":material/check_circle:")
    pendentes = [i for i in itens if i["fator_conversao"] is None]
    if pendentes:
        st.warning(
            f"**{len(pendentes)} linha(s) sem fator.** A planilha não diz o peso "
            "delas (um maço, uma unidade, uma caixa) e o insumo é controlado em "
            "outra unidade. Enquanto o fator estiver em branco, contar essa "
            "linha trava a gravação do insumo dela.",
            icon=":material/pending:",
        )
    else:
        st.success("Todas as linhas têm fator de conversão.", icon=":material/task_alt:")

    so_pendentes = st.toggle(
        "Mostrar só as linhas sem fator", value=bool(pendentes), key="fatores_so_pendentes"
    )
    mostrar = pendentes if so_pendentes else itens
    if not mostrar:
        return

    versao = st.session_state.get("fatores_versao", 0)
    linhas = [
        {
            "Item": i["descricao"],
            "Seção": i["secao"],
            "Conta em": i["unidade_contagem"],
            "Insumo": f"{i['insumo']} ({i['unidade_insumo']})",
            "Fator": i["fator_conversao"],
        }
        for i in mostrar
    ]
    st.caption(
        "**Fator** = quanto 1 unidade contada vale na unidade do insumo. "
        "Ex.: 1 maço de alecrim = 0,05 kg → fator 0,05."
    )
    valores = _tabela_em_lote(
        linhas, "Item", "Fator", "Fator", f"fatores_{versao}",
        "%.4f", "Filtrar item", passo=0.01, grupo=str(so_pendentes),
    )

    atuais = {i["descricao"]: i["fator_conversao"] for i in itens}
    ids = {i["descricao"]: i["id"] for i in itens}
    mudados = {ids[n]: v for n, v in valores.items() if n in ids and v != atuais.get(n)}
    if not mudados:
        return
    st.write(f"**{len(mudados)} fator(es) alterado(s).**")
    if st.button("💾 Gravar fatores", type="primary", key="fatores_gravar"):
        try:
            total = crud.atualizar_fatores_da_contagem(mudados)
        except Exception as e:
            st.error(f"Nada foi gravado: {e}")
            return
        st.session_state["fatores_versao"] = versao + 1
        # A tabela recomeça numa chave nova, lida do banco; a confirmação vai
        # para a execução seguinte, senão o rerun a apagaria.
        st.session_state["fatores_gravados"] = total
        st.rerun()


def _importar_planilha_de_contagem():
    arquivo = st.file_uploader(
        "Planilha de contagem (.xlsx, aba COMPRAS)", type=["xlsx"], key="contagem_planilha"
    )
    if not arquivo:
        return
    try:
        linhas = contagem_import.ler_planilha(arquivo)
        plano = contagem_import.montar_plano(linhas)
    except Exception as e:
        st.error(f"Não consegui ler a planilha: {e}")
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("Linhas de alimentos e bebidas", len(plano["itens"]))
    col2.metric("Insumos novos", len(plano["insumos_novos"]))
    col3.metric("Fator a definir", len(plano["a_definir"]))
    st.caption(
        "Limpeza, descartáveis, escritório e utensílios ficam de fora. "
        "Linha repetida em duas seções entra uma vez só."
    )

    if plano["problemas"]:
        st.error("A importação está bloqueada até resolver:\n\n- " + "\n- ".join(plano["problemas"]))
        return
    if plano["unidades_a_corrigir"]:
        st.info(
            "Estes insumos mudam de unidade, porque a planilha passou a contá-los "
            "de outro jeito. Nenhum deles tem compra, contagem nem ficha ainda, "
            "então a troca não altera nenhum número: "
            + ", ".join(
                f"{nome} ({de} → {para})"
                for nome, (de, para) in sorted(plano["unidades_a_corrigir"].items())
            ),
            icon=":material/straighten:",
        )
    if plano["renomear"]:
        st.info(
            "Estas linhas trocam de nome, e o que já foi contado nelas vai junto: "
            + "; ".join(
                f"{r['de']} → {r['para']}"
                + (f" (junta com o '{r['insumo_para']}' que a ficha do bar criou)"
                   if r.get("funde")
                   else f" (o insumo passa a se chamar '{r['insumo_para']}')"
                   if r["renomeia_insumo"] else f" (passa para '{r['insumo_para']}')")
                for r in plano["renomear"]
            ),
            icon=":material/edit:",
        )
    if plano["saem"]:
        with st.expander(f"Linhas que saem da contagem ({len(plano['saem'])})"):
            st.caption(
                "Estão no sistema e não estão mais nesta planilha (produto que saiu "
                "ou descrição reescrita). Sai só a linha da contagem: o insumo "
                "continua cadastrado, com compras e ficha."
            )
            st.write(", ".join(f"{s['descricao']} → {s['insumo']}" for s in plano["saem"]))
    if plano["ficam"]:
        st.info(
            f"{len(plano['ficam'])} linha(s) não estão mais na planilha, mas já têm "
            "contagem gravada e por isso ficam: "
            + ", ".join(f["descricao"] for f in plano["ficam"]),
            icon=":material/history:",
        )
    com_historico = [n for n in plano["insumos_sem_linha"] if n not in plano["excluiveis"]]
    if com_historico:
        st.caption(
            "Estes insumos ficam sem nenhuma linha na planilha e passam para a "
            "seção *Fora da planilha* da contagem. Como têm histórico, não são "
            "excluídos aqui; se não existem mais, dá para excluir na tela de "
            "Insumos: " + ", ".join(com_historico)
        )
    excluir_sem_linha = False
    if plano["excluiveis"]:
        excluir_sem_linha = st.checkbox(
            "Excluir também os insumos que ficam sem linha e não têm histórico "
            "nenhum (nem compra, contagem, ficha ou nota): "
            + ", ".join(plano["excluiveis"]),
            value=True, key="contagem_excluir_sem_linha",
            help="Sem isso, eles continuam aparecendo em 'Fora da planilha' na contagem.",
        )
    if plano["insumos_novos"]:
        with st.expander(f"Insumos que serão criados ({len(plano['insumos_novos'])})"):
            st.write(", ".join(
                f"{nome} ({unidade})" for nome, unidade in sorted(plano["insumos_novos"].items())
            ))
    with st.expander("Como cada linha vai ficar"):
        st.dataframe(
            pd.DataFrame([
                {
                    "Seção": i["secao"], "Item": i["descricao"], "Conta em": i["unidade_contagem"],
                    "Insumo": i["insumo"], "Un. insumo": i["unidade_insumo"], "Fator": i["fator"],
                }
                for i in plano["itens"]
            ]),
            width="stretch", hide_index=True,
        )

    if st.button("📥 Importar planilha", type="primary", key="contagem_importar"):
        try:
            resultado = contagem_import.aplicar_plano(plano, excluir_sem_linha)
        except Exception as e:
            st.error(f"Nada foi gravado: {e}")
            return
        recado = (
            f"{resultado['insumos_criados']} insumo(s) criado(s), "
            f"{resultado['unidades_corrigidas']} unidade(s) trocada(s), "
            f"{resultado['itens_criados']} linha(s) nova(s), "
            f"{resultado['itens_atualizados']} atualizada(s), "
            f"{resultado['linhas_renomeadas']} renomeada(s) e "
            f"{resultado['itens_removidos']} removida(s)."
        )
        if resultado["insumos_excluidos"]:
            recado += f" {resultado['insumos_excluidos']} insumo(s) sem histórico excluído(s)."
        st.success(recado, icon=":material/check_circle:")


def pagina_itens_contagem():
    _titulo("checklist", "Itens da Contagem")
    st.caption(
        "As linhas da planilha de estoque que a tela de Contagem Física "
        "mostra, e a conversão de cada uma para o insumo."
    )
    itens = crud.itens_da_contagem()

    aba_fatores, aba_importar = st.tabs(["Fatores de conversão", "Importar planilha"])
    with aba_fatores:
        if itens:
            _editor_de_fatores(itens)
        else:
            st.info(
                "Nenhuma planilha de contagem importada ainda. Sem ela, a "
                "Contagem Física lista os insumos direto, cada um na sua unidade."
            )
    with aba_importar:
        st.caption(
            "Importar de novo a mesma planilha atualiza as linhas em vez de "
            "duplicar, e não apaga fator que já foi preenchido aqui."
        )
        _importar_planilha_de_contagem()


# ---------- Contagem Física ----------

TODAS_AS_SECOES = "Todas as seções"
FORA_DA_PLANILHA = "Fora da planilha"


def _linhas_da_contagem(data_iso, insumos, unidades):
    """As linhas da tela de contagem: as da planilha e, no fim, os insumos
    que não estão nela, contados direto na unidade do insumo.

    Devolve também `alvo`, que diz para cada linha da tabela se ela é um
    item da planilha (e qual) ou um insumo contado direto.
    """
    itens = crud.itens_da_contagem()
    ja_por_item = crud.contagem_por_item_do_dia(data_iso)
    ja_por_insumo = crud.contagens_do_dia(data_iso)

    linhas, alvo = [], {}
    for item in itens:
        fator = item["fator_conversao"]
        if fator is None:
            destino = f"{item['insumo']} · ⚠️ fator a definir"
        elif fator == 1 and item["unidade_contagem"] == item["unidade_insumo"]:
            destino = item["insumo"]
        else:
            numero = f"{fator:g}".replace(".", ",")
            destino = f"{item['insumo']} · 1 = {numero} {item['unidade_insumo']}"
        linhas.append({
            "Seção": item["secao"],
            "Item": item["descricao"],
            "Un.": item["unidade_contagem"],
            "Contagem": ja_por_item.get(item["id"]),
            "Vai para": destino,
        })
        alvo[item["descricao"]] = ("item", item["id"])

    na_planilha = {item["insumo"] for item in itens}
    for nome in insumos:
        if nome in na_planilha:
            continue
        rotulo = nome if nome not in alvo else f"{nome} (insumo)"
        linhas.append({
            "Seção": FORA_DA_PLANILHA,
            "Item": rotulo,
            "Un.": unidades.get(nome, ""),
            "Contagem": ja_por_insumo.get(nome),
            "Vai para": nome,
        })
        alvo[rotulo] = ("insumo", nome)
    return itens, linhas, alvo


def _avisos_da_contagem(resumo):
    """O que a conversão encontrou e quem conta precisa saber antes de gravar."""
    if resumo["sem_fator"]:
        detalhe = "; ".join(
            f"**{insumo}** ({', '.join(linhas)})"
            for insumo, linhas in sorted(resumo["sem_fator"].items())
        )
        st.error(
            f"{len(resumo['sem_fator'])} insumo(s) **não serão gravados** porque uma "
            f"linha preenchida ainda não tem fator de conversão: {detalhe}. "
            "Defina o fator em *Itens da Contagem* e grave de novo — o que "
            "foi digitado continua aqui.",
            icon=":material/block:",
        )
    if resumo["em_branco"]:
        with st.expander(
            f"⚠️ {len(resumo['em_branco'])} insumo(s) com linha em branco, que conta como zero"
        ):
            st.caption(
                "Estes insumos têm mais de uma linha na planilha e só parte delas "
                "foi preenchida. As linhas em branco entram como **zero** no total "
                "do insumo. Se ainda não contou, preencha antes de gravar."
            )
            for insumo, linhas in sorted(resumo["em_branco"].items()):
                st.write(f"**{insumo}**: " + ", ".join(linhas))


def pagina_contagem():
    _titulo("fact_check", "Contagem Física")
    st.caption(
        "A contagem na ordem da planilha de estoque, na unidade de cada "
        "prateleira. O sistema converte cada linha para o insumo e a "
        "contagem vira a nova base do cálculo automático."
    )

    apagada = st.session_state.pop("contagem_apagada", None)
    if apagada:
        st.success(apagada, icon=":material/delete:")

    insumos = listar_insumos()
    if not insumos:
        st.info("Cadastre um insumo antes de registrar contagem.")
        return

    col_data, col_obs = st.columns([1, 2])
    data = col_data.date_input("Data da contagem", value=crud.hoje(), key="contagem_data")
    observacao = col_obs.text_input("Observação (opcional)", key="contagem_obs")
    data_iso = str(data)

    # A contagem é feita de manhã, antes do movimento: a convenção do
    # sistema é que ela mede o estoque *antes* dos lançamentos do próprio
    # dia, e por isso as vendas do dia da contagem já são descontadas dela.
    st.caption(
        "Conte antes de abrir. As vendas lançadas no mesmo dia da contagem "
        "já são descontadas desta base."
    )

    unidades = unidades_dos_insumos()
    teoricos = {e["insumo"]: e["estoque_atual"] for e in crud.calcular_estoque_todos_insumos()}
    itens, linhas, alvo = _linhas_da_contagem(data_iso, insumos, unidades)

    # A data entra na chave: trocar de dia não pode carregar os números
    # que já tinham sido digitados para o dia anterior. Os valores são
    # carregados aqui, de todas as seções, porque a tabela mostra uma
    # seção por vez e só conhece as linhas visíveis.
    chave = f"contagem_{data_iso}"
    if f"{chave}_valores" not in st.session_state:
        st.session_state[f"{chave}_valores"] = {
            l["Item"]: float(l["Contagem"]) for l in linhas if l["Contagem"] is not None
        }
        if st.session_state[f"{chave}_valores"]:
            st.session_state[f"{chave}_ja_gravado"] = True
    if st.session_state.get(f"{chave}_ja_gravado"):
        st.info(
            f"Já existe contagem gravada em {_data_br(data_iso)}. Os valores vêm "
            "preenchidos abaixo; gravar de novo corrige, não duplica.",
            icon=":material/history:",
        )
        _apagar_contagem(data_iso, chave)

    if itens:
        _contagem_pela_planilha(data_iso, itens, chave)
    _preencher_contagem(data_iso, observacao, itens, linhas, alvo, unidades, teoricos, chave)


def _contagem_pela_planilha(data_iso, itens, chave):
    """Traz para a tabela os números da coluna CONTAGEM da planilha.

    A equipe conta no papel ou na própria planilha; digitar tudo de novo
    no app eram quase quatrocentos números. Aqui os números só entram na
    tabela, no lugar do que estava nela, e quem conta confere e grava pelo
    botão de sempre, com as mesmas regras (linha irmã em branco vale zero,
    linha sem fator trava o insumo).
    """
    avisado = st.session_state.pop(f"{chave}_da_planilha", None)
    if avisado:
        st.success(avisado, icon=":material/table_view:")
    with st.expander("📄 Preencher com a planilha da contagem"):
        st.caption(
            f"Envie a planilha com a coluna CONTAGEM preenchida. Os números "
            f"entram na tabela abaixo, para {_data_br(data_iso)}, e só são "
            "gravados quando você apertar **Gravar contagem**."
        )
        arquivo = st.file_uploader(
            "Planilha preenchida (.xlsx, aba COMPRAS)", type=["xlsx"],
            key=f"{chave}_arquivo",
        )
        if not arquivo:
            return
        try:
            lido = contagem_import.contagem_da_planilha(
                contagem_import.ler_planilha(arquivo), itens
            )
        except Exception as e:
            st.error(f"Não consegui ler a planilha: {e}")
            return

        valores = lido["valores"]
        st.write(f"**{len(valores)} linha(s) com número** batem com a contagem do sistema.")
        if lido["invalidas"]:
            st.error(
                "Estas linhas têm na contagem algo que não é número, e ficam de fora: "
                + "; ".join(f"{l['descricao']} ({l['contagem_invalida']})"
                            for l in lido["invalidas"]),
                icon=":material/error:",
            )
        if lido["sem_linha"]:
            st.warning(
                f"{len(lido['sem_linha'])} linha(s) com número não existem na contagem "
                "do sistema e ficam de fora. Se são produtos novos, importe esta "
                "planilha em *Itens da Contagem* antes: "
                + "; ".join(f"{l['descricao']} ({l['contagem']:g})" for l in lido["sem_linha"]),
                icon=":material/warning:",
            )
        if not valores:
            return
        if st.button("Colocar os números na tabela", type="primary", key=f"{chave}_usar_planilha"):
            # As linhas da planilha são trocadas pelo que veio do arquivo;
            # o que foi digitado em "Fora da planilha" fica.
            da_planilha = {item["descricao"] for item in itens}
            atuais = st.session_state.get(f"{chave}_valores", {})
            st.session_state[f"{chave}_valores"] = {
                **{n: v for n, v in atuais.items() if n not in da_planilha},
                **valores,
            }
            # O editor guarda as edições por índice de linha; sem limpar,
            # uma edição antiga seria reaplicada por cima do arquivo.
            for nome in list(st.session_state):
                if nome.startswith(f"{chave}_editor_"):
                    del st.session_state[nome]
            st.session_state[f"{chave}_da_planilha"] = (
                f"{len(valores)} número(s) da planilha na tabela. Confira e grave."
            )
            st.rerun()


def _esquecer_contagem(chave):
    """Tira da sessão tudo o que a tela guardou da contagem de um dia."""
    for nome in list(st.session_state):
        if nome.startswith(f"{chave}_"):
            del st.session_state[nome]


def _apagar_contagem(data_iso, chave):
    """Apaga a contagem gravada no dia, com confirmação."""
    with st.expander(f"Apagar a contagem de {_data_br(data_iso)}"):
        st.caption(
            "Apaga todas as linhas e todos os totais gravados nesta data. Os "
            "insumos contados nela voltam a usar a contagem anterior como base "
            "(ou ficam sem contagem, se esta era a única). Compras, vendas e "
            "produções do dia continuam como estão. Não tem como desfazer."
        )
        certeza = st.checkbox(
            f"Sim, apagar a contagem de {_data_br(data_iso)}",
            key=f"contagem_apagar_{data_iso}",
        )
        if st.button("🗑️ Apagar contagem", disabled=not certeza,
                     key=f"contagem_apagar_botao_{data_iso}"):
            try:
                apagado = crud.apagar_contagem_do_dia(data_iso)
            except Exception as e:
                st.error(f"Nada foi apagado: {e}")
                return
            _esquecer_contagem(chave)
            st.session_state.pop(f"contagem_apagar_{data_iso}", None)
            st.session_state["contagem_apagada"] = (
                f"Contagem de {_data_br(data_iso)} apagada: {apagado['linhas']} "
                f"linha(s) da planilha e {apagado['insumos']} insumo(s)."
            )
            st.rerun()


# Cada célula editada no `data_editor` refaz a execução. Sem o fragmento,
# era a página inteira de novo: login, barra lateral, estoque de todos os
# insumos e a planilha da contagem relidos do banco a cada número digitado,
# numa tabela de quase seiscentas linhas. No fragmento, editar refaz só a
# tabela, com os dados da última execução completa — nenhuma ida ao banco
# até o botão de gravar. Trocar a data ou a observação refaz tudo.
@st.fragment
def _preencher_contagem(data_iso, observacao, itens, linhas, alvo, unidades, teoricos, chave):
    st.write("**Preencha o que foi contado, na unidade da linha. Deixe em branco o que não contou.**")
    secoes = list(dict.fromkeys(l["Seção"] for l in linhas))
    secao = TODAS_AS_SECOES
    if len(secoes) > 1:
        secao = st.selectbox(
            "Seção da planilha",
            [TODAS_AS_SECOES] + secoes,
            format_func=lambda s: s if s == TODAS_AS_SECOES
            else f"{s} · {sum(1 for l in linhas if l['Seção'] == s)} itens",
            key="contagem_secao",
            help="A mesma ordem da planilha de papel: conte uma seção, passe para a próxima. "
                 "O que foi digitado nas outras seções fica guardado.",
        )
    if not itens:
        # Sem planilha importada, toda linha é um insumo contado direto:
        # "Fora da planilha" e "Vai para" repetiriam o óbvio em cada linha.
        visiveis = [{k: v for k, v in l.items() if k not in ("Seção", "Vai para")}
                    for l in linhas]
    elif secao == TODAS_AS_SECOES:
        visiveis = linhas
    else:
        visiveis = [{k: v for k, v in l.items() if k != "Seção"}
                    for l in linhas if l["Seção"] == secao]

    valores = _tabela_em_lote(
        visiveis, "Item", "Contagem", "Contagem", chave,
        "%.3f", "Filtrar item", grupo=secao,
    )

    # Um nome que não está mais em `alvo` sobrou de uma versão anterior
    # da lista (item renomeado ou apagado) e não tem para onde ir.
    por_item = {alvo[n][1]: v for n, v in valores.items() if alvo.get(n, ("",))[0] == "item"}
    por_insumo = {alvo[n][1]: v for n, v in valores.items() if alvo.get(n, ("",))[0] == "insumo"}
    if not por_item and not por_insumo:
        st.caption("Nenhuma contagem preenchida ainda.")
        return

    try:
        resumo = crud.resumo_da_contagem(por_item, por_insumo, itens)
    except ValueError as e:
        st.error(str(e))
        return

    st.write(
        f"**{len(por_item) + len(por_insumo)} linha(s) preenchida(s)** de {len(linhas)} · "
        f"{len(resumo['totais'])} insumo(s) prontos para gravar."
    )
    _avisos_da_contagem(resumo)

    with st.expander(f"Ver o total de cada insumo ({len(resumo['totais'])})"):
        st.dataframe(
            pd.DataFrame([
                {
                    "Insumo": nome,
                    "Contado": total,
                    "Un.": unidades.get(nome, ""),
                    "Teórico": teoricos.get(nome),
                    "De onde veio": "; ".join(resumo["composicao"][nome]) or "direto",
                }
                for nome, total in sorted(resumo["totais"].items())
            ]),
            width="stretch", hide_index=True,
            column_config={"Contado": st.column_config.NumberColumn(format="%.3f")},
        )

    if st.button("💾 Gravar contagem", type="primary", disabled=not resumo["totais"]):
        try:
            resumo = crud.registrar_contagem_pela_planilha(
                por_item, por_insumo, data_iso, observacao.strip() or None
            )
        except Exception as e:
            st.error(f"Nada foi gravado: {e}")
            return

        st.session_state[f"{chave}_ja_gravado"] = True
        # A diferença entre o que o sistema calculava e o que foi contado é
        # a informação que a contagem existe para produzir. Mostrar na hora
        # evita que ela só apareça na tela de perdas, um mês depois.
        diferencas = [
            {
                "Insumo": nome,
                "Teórico": teoricos[nome],
                "Contado": contado,
                "Diferença": round(contado - teoricos[nome], 3),
                "Un.": unidades.get(nome, ""),
            }
            for nome, contado in resumo["totais"].items()
            if teoricos.get(nome) is not None
        ]
        _guardar_resultado(chave, valores, {
            "gravados": len(resumo["totais"]),
            "divergentes": [d for d in diferencas if abs(d["Diferença"]) > 0.001],
        })
        # O aviso de contagem já gravada e o botão de apagar ficam fora do
        # fragmento; refazer a página inteira faz os dois aparecerem.
        st.rerun()

    resultado = _resultado_guardado(chave, valores)
    if resultado:
        st.success(
            f"{resultado['gravados']} insumo(s) gravado(s) em {_data_br(data_iso)}. "
            "Esta é a nova base do cálculo.",
            icon=":material/check_circle:",
        )
        divergentes = resultado["divergentes"]
        if divergentes:
            st.write(f"**{len(divergentes)} insumo(s) diferentes do calculado**")
            st.dataframe(
                pd.DataFrame(sorted(divergentes, key=lambda d: -abs(d["Diferença"]))),
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "Diferença negativa: havia menos no estoque do que o sistema "
                "calculava — perda, quebra ou porção maior que a ficha. "
                "Positiva: sobrou mais, o que costuma ser venda ou compra não "
                "lançada. A tela de Perdas detalha isso entre duas contagens."
            )
        else:
            st.caption("Nenhuma divergência em relação ao calculado.")


def _explicacao_da_conta():
    with st.expander("Como esta conta é feita"):
        st.markdown(
            """
            Entre duas contagens físicas dá para fechar a conta do que
            aconteceu com cada insumo. Tudo que estava disponível teve um de
            três destinos, e os três somam exatamente 100%:

            ```
            disponível  =  estoque da contagem anterior
                         + compras e produções do período
            disponível  =  usado (vendas × ficha do prato
                                  + o que as produções gastaram)
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
    _titulo("scale", "Perdas e Reconciliação")
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


# ---------- Lançar Produção ----------

# Produzir é um movimento com dois lados: entra o molho, sai o que a receita
# gasta. Quem lança diz quantas receitas fez — é isso que decide o cru que
# sai — e confere quanto rendeu, que vem preenchido pelo rendimento da ficha.

def pagina_producao():
    _titulo("soup_kitchen", "Lançar Produção")
    st.caption(
        "Molho, base, carne porcionada: o que a cozinha produziu entra no "
        "estoque, e os ingredientes da receita saem."
    )

    producoes = crud.listar_producoes()
    com_receita = [p for p in producoes if p["itens_na_ficha"]]
    if not com_receita:
        st.info(
            "Nenhuma produção com receita cadastrada. Cadastre a receita em "
            "Ficha Técnica → Produção."
        )
        _historico_de_producao()
        return

    recado = st.session_state.pop("producao_recado", None)
    if recado:
        st.success(recado, icon=":material/check_circle:")

    por_nome = {p["nome"]: p for p in com_receita}
    col1, col2 = st.columns([3, 1])
    producao = col1.selectbox("O que foi produzido", list(por_nome), key="producao_nome")
    data = col2.date_input(
        "Data", value=crud.hoje(), max_value=crud.hoje(), format="DD/MM/YYYY",
        key="producao_data",
    )
    item = por_nome[producao]
    unidade = item["unidade_medida"]

    if producao in cozinha_fria.PORCIONADOS:
        st.caption(
            "Porcionamento: **1 receita = 1 kg de peça**. Em *Quantas receitas*, "
            "os kg de peça que foram limpos; em *Quanto rendeu*, o peso do "
            "porcionado pronto. A diferença é a perda da limpeza."
        )
    col1, col2 = st.columns(2)
    receitas = col1.number_input(
        "Quantas receitas", min_value=0.0, value=1.0, step=0.5, format="%.2f",
        key="producao_receitas",
        help="Meia receita é 0,5. É este número que decide o que sai do estoque.",
    )
    sugerido = round((item["rendimento"] or 0) * receitas, 3)
    # A chave leva a produção e o número de receitas: trocar qualquer um dos
    # dois recalcula a sugestão, em vez de manter o número da escolha anterior.
    rendeu = col2.number_input(
        f"Quanto rendeu ({unidade})", min_value=0.0, value=float(sugerido), step=0.5,
        format="%.3f", key=f"producao_rendeu_{producao}_{receitas}",
        help=(
            f"Vem preenchido com o rendimento da ficha "
            f"({item['rendimento'] or 0:g} {unidade} por receita). "
            "Se pesou ou contou diferente, corrija."
        ),
    )
    observacao = st.text_input("Observação (opcional)", key="producao_obs")

    if receitas <= 0:
        st.info("Informe quantas receitas foram feitas.")
        _historico_de_producao()
        return

    impacto = crud.impacto_da_producao(producao, receitas)
    estoques = {e["insumo"]: e for e in crud.calcular_estoque_todos_insumos()}
    st.markdown(f"**Sai do estoque** ({receitas:g} receita(s) de {producao}):")
    st.dataframe(
        pd.DataFrame([
            {
                "Insumo": i["insumo"],
                "Sai": i["consumo"],
                "Un.": i["unidade_medida"],
                "Estoque agora": estoques.get(i["insumo"], {}).get("estoque_atual"),
            }
            for i in impacto
        ]),
        hide_index=True, width="stretch",
        column_config={
            "Sai": st.column_config.NumberColumn(format="%.3f"),
            "Estoque agora": st.column_config.NumberColumn(format="%.1f"),
        },
    )
    st.markdown(f"**Entra no estoque:** {rendeu:g} {unidade} de {producao}.")

    # Produção soma, não substitui: fazer duas levas no mesmo dia é normal.
    # Por isso o clique duplo não é inofensivo aqui como é na venda, e a
    # segunda leva do dia pede confirmação.
    ja_lancado = crud.producoes_do_dia(producao, data.isoformat())
    confirmado = True
    if ja_lancado["levas"]:
        st.warning(
            f"Já há {ja_lancado['levas']} leva(s) de {producao} em "
            f"{data.strftime('%d/%m/%Y')}, somando {ja_lancado['produzido']:g} {unidade}.",
            icon=":material/content_copy:",
        )
        # O número de levas entra na chave: depois de lançar, a caixa volta
        # desmarcada e a leva seguinte pede confirmação de novo. Tirar a
        # chave da sessão não bastava — o navegador devolvia o valor marcado
        # na execução seguinte, e o botão ficava liberado (visto no teste
        # pelo navegador em 24/09).
        confirmado = st.checkbox(
            "É outra leva, quero somar",
            key=f"producao_outra_leva_{producao}_{data.isoformat()}_{ja_lancado['levas']}",
        )

    if st.button("🍳 Lançar produção", type="primary",
                 disabled=rendeu <= 0 or not confirmado):
        try:
            crud.registrar_producao(producao, receitas, rendeu, data.isoformat(), observacao)
        except Exception as e:
            st.error(f"Nada foi gravado: {e}")
        else:
            st.session_state["producao_recado"] = (
                f"Lançado: {rendeu:g} {unidade} de {producao} em "
                f"{data.strftime('%d/%m/%Y')}, gastando {receitas:g} receita(s)."
            )
            st.rerun()

    _historico_de_producao()


def _historico_de_producao():
    st.divider()
    st.subheader("Produções dos últimos 30 dias")
    hoje = crud.hoje()
    levas = crud.producoes_no_periodo(
        (hoje - datetime.timedelta(days=29)).isoformat(), hoje.isoformat()
    )
    if not levas:
        st.caption("Nenhuma produção lançada no período.")
        return

    st.dataframe(
        pd.DataFrame([
            {
                "Data": _data_br(l["data"]),
                "Produção": l["producao"],
                "Receitas": l["receitas"],
                "Rendeu": l["quantidade_produzida"],
                "Un.": l["unidade_medida"],
                "Observação": l["observacao"],
            }
            for l in levas
        ]),
        hide_index=True, width="stretch",
        column_config={
            "Receitas": st.column_config.NumberColumn(format="%g"),
            "Rendeu": st.column_config.NumberColumn(format="%.3f"),
        },
    )

    with st.expander("Ver o que uma leva gastou, ou apagar uma leva lançada errado"):
        rotulos = {
            f"{_data_br(l['data'])} · {l['producao']} · {l['quantidade_produzida']:g} "
            f"{l['unidade_medida']} (nº {l['id']})": l["id"]
            for l in levas
        }
        escolhida = st.selectbox("Leva", list(rotulos), key="producao_leva")
        producao_id = rotulos[escolhida]
        st.dataframe(
            pd.DataFrame([
                {"Insumo": c["insumo"], "Gastou": c["quantidade"], "Un.": c["unidade_medida"]}
                for c in crud.consumo_da_producao(producao_id)
            ]),
            hide_index=True, width="stretch",
            column_config={"Gastou": st.column_config.NumberColumn(format="%.3f")},
        )
        confirmar = st.checkbox(
            "Apagar esta leva: o produzido sai do estoque e os ingredientes voltam",
            key=f"producao_apagar_{producao_id}",
        )
        if st.button("Apagar leva", disabled=not confirmar, key="producao_apagar"):
            try:
                crud.excluir_producao(producao_id)
            except Exception as e:
                st.error(f"Erro: {e}")
            else:
                st.session_state["producao_recado"] = f"Leva apagada: {escolhida}."
                st.rerun()

# ---------- Baixa de Estoque ----------

def pagina_baixa():
    _titulo("remove_shopping_cart", "Baixa de Estoque")
    st.caption(
        "Para o que sai do estoque sem ser venda nem produção: a garrafa que "
        "quebrou, o peixe que venceu, a refeição da equipe. Sem a baixa, isso "
        "só aparece como perda na contagem seguinte, sem explicação."
    )
    recado = st.session_state.pop("baixa_gravada", None)
    if recado:
        st.success(recado, icon=":material/check_circle:")

    insumos = listar_insumos()
    if not insumos:
        st.info("Cadastre um insumo antes de dar baixa.")
        return
    unidades = unidades_dos_insumos()

    col1, col2 = st.columns([1, 2])
    data = col1.date_input("Data", value=crud.hoje(), key="baixa_data")
    motivo = col2.selectbox("Motivo", crud.MOTIVOS_DE_BAIXA, key="baixa_motivo")
    observacao = st.text_input("Observação (opcional)", key="baixa_obs",
                               placeholder="ex.: caixa caiu no descarregamento")

    st.write("**O que saiu**")
    st.caption("Uma linha por insumo, na unidade em que ele é controlado.")
    # A versão entra na chave para a tabela voltar vazia depois de gravar.
    versao = st.session_state.get("baixa_versao", 0)
    tabela = st.data_editor(
        pd.DataFrame({
            "Insumo": pd.Series([], dtype="object"),
            "Quantidade": pd.Series([], dtype="float64"),
        }),
        num_rows="dynamic", width="stretch", hide_index=True,
        key=f"baixa_itens_{versao}",
        column_config={
            "Insumo": st.column_config.SelectboxColumn(
                "Insumo", options=insumos, required=False, width="large"
            ),
            "Quantidade": st.column_config.NumberColumn(
                "Quantidade", min_value=0.0, step=0.5, format="%.3f"
            ),
        },
    )
    itens = _itens_digitados(tabela)
    if not itens:
        st.info("Preencha ao menos um item.")
        return

    estoques = {e["insumo"]: e["estoque_atual"] for e in crud.calcular_estoque_todos_insumos()}
    st.dataframe(
        pd.DataFrame([
            {
                "Insumo": i["insumo"],
                "Sai": i["quantidade"],
                "Un.": unidades.get(i["insumo"], ""),
                "Estoque agora": estoques.get(i["insumo"]),
                "Fica": (estoques.get(i["insumo"]) or 0) - i["quantidade"],
            }
            for i in itens
        ]),
        width="stretch", hide_index=True,
        column_config={c: st.column_config.NumberColumn(format="%.3f")
                       for c in ("Sai", "Estoque agora", "Fica")},
    )
    if st.button(f"Dar baixa em {len(itens)} item(ns)", type="primary"):
        try:
            gravados = crud.registrar_baixas_em_lote(
                itens, str(data), motivo, observacao.strip() or None
            )
        except Exception as e:
            st.error(f"Nada foi gravado: {e}")
            return
        st.session_state["baixa_versao"] = versao + 1
        st.session_state["baixa_gravada"] = (
            f"Baixa de {gravados} item(ns) em {_data_br(str(data))} ({motivo}). "
            "Para desfazer, use *Corrigir Lançamentos*."
        )
        st.rerun()


# ---------- Corrigir Lançamentos ----------

def _escolher_para_apagar(linhas, colunas, chave, apagar, rotulo):
    """Tabela com uma caixa "Apagar" por linha, confirmação e botão.

    `linhas` precisa ter 'id'; `colunas` é {coluna na tela: chave na linha};
    `apagar` recebe a lista de ids e devolve quantos apagou.
    """
    if not linhas:
        st.caption(f"Nenhum(a) {rotulo} no período.")
        return
    versao = st.session_state.get(f"{chave}_versao", 0)
    df = pd.DataFrame([
        {"Apagar": False, **{coluna: l[campo] for coluna, campo in colunas.items()}}
        for l in linhas
    ])
    tabela = st.data_editor(
        df, hide_index=True, width="stretch", key=f"{chave}_tabela_{versao}",
        disabled=[c for c in df.columns if c != "Apagar"],
        column_config={
            "Apagar": st.column_config.CheckboxColumn(width="small"),
            "Quantidade": st.column_config.NumberColumn(format="%.3f"),
        },
    )
    ids = [linhas[i]["id"] for i, marcada in enumerate(tabela["Apagar"]) if marcada]
    if not ids:
        st.caption("Marque na coluna *Apagar* o que foi lançado errado.")
        return
    certeza = st.checkbox(
        f"Sim, apagar {len(ids)} lançamento(s). Não tem como desfazer.",
        key=f"{chave}_certeza_{versao}",
    )
    if st.button("Apagar", icon=":material/delete:", disabled=not certeza,
                 key=f"{chave}_apagar_{versao}") and certeza:
        try:
            apagados = apagar(ids)
        except Exception as e:
            st.error(f"Nada foi apagado: {e}")
            return
        st.session_state[f"{chave}_versao"] = versao + 1
        st.session_state["corrigir_recado"] = f"{apagados} lançamento(s) apagado(s)."
        st.rerun()


def _marcar_repetidas(compras):
    """Mesmo dia, insumo, quantidade, fornecedor e nota: quase sempre é o
    mesmo lançamento feito duas vezes."""
    def assinatura(c):
        return (c["data"], c["insumo"], c["quantidade"], c["fornecedor"], c["numero_nota"])

    vezes = {}
    for c in compras:
        vezes[assinatura(c)] = vezes.get(assinatura(c), 0) + 1
    for c in compras:
        c["repetida"] = "⚠️ em dobro?" if vezes[assinatura(c)] > 1 else ""
    return sum(1 for c in compras if c["repetida"])


def _nota_repetida(nota):
    """Aviso e botão para a nota que entrou mais de uma vez."""
    chave = f"nota_repetida_{nota['apagar'][0]}"
    with st.container(border=True):
        st.warning(
            f"A nota **{nota['nota']}** de {nota['fornecedor'] or 'fornecedor sem nome'}, "
            f"em {_data_br(nota['data'])}, foi lançada **{nota['vezes']} vezes** "
            f"({nota['itens']} itens cada). As {len(nota['apagar'])} linhas a mais "
            "somam a nota de novo no estoque.",
            icon=":material/content_copy:",
        )
        certeza = st.checkbox(
            f"Manter uma cópia e apagar as outras {nota['vezes'] - 1}", key=chave
        )
        if st.button(f"🗑️ Apagar {len(nota['apagar'])} linha(s) repetida(s)",
                     disabled=not certeza, key=f"{chave}_botao") and certeza:
            try:
                apagados = crud.apagar_compras(nota["apagar"])
            except Exception as e:
                st.error(f"Nada foi apagado: {e}")
                return
            st.session_state.pop(chave, None)
            st.session_state["corrigir_recado"] = (
                f"{apagados} linha(s) repetida(s) da nota {nota['nota']} apagada(s)."
            )
            st.rerun()


def pagina_corrigir():
    _titulo("delete_sweep", "Corrigir Lançamentos")
    st.caption(
        "Para apagar o que foi lançado em dobro ou errado. Apagar uma compra "
        "tira do estoque o que ela tinha somado; apagar uma produção ou uma "
        "baixa devolve o que ela tinha tirado. A venda se corrige na própria "
        "tela de venda, lançando o número certo do dia."
    )
    recado = st.session_state.pop("corrigir_recado", None)
    if recado:
        st.success(recado, icon=":material/delete:")

    hoje = crud.hoje()
    col1, col2 = st.columns(2)
    inicio = col1.date_input("De", value=hoje - datetime.timedelta(days=30), key="corrigir_de")
    fim = col2.date_input("Até", value=hoje, key="corrigir_ate")
    if inicio > fim:
        st.error("A data inicial é depois da final.")
        return

    aba_compras, aba_producoes, aba_baixas = st.tabs(["Compras", "Produções", "Baixas"])
    with aba_compras:
        compras = crud.compras_no_periodo(str(inicio), str(fim))
        for nota in crud.notas_repetidas(compras):
            _nota_repetida(nota)
        repetidas = _marcar_repetidas(compras)
        if repetidas:
            st.warning(
                f"{repetidas} compra(s) aparecem repetidas: mesmo dia, insumo, "
                "quantidade, fornecedor e nota. Confira e apague a sobra.",
                icon=":material/content_copy:",
            )
        for c in compras:
            c["data_br"] = _data_br(c["data"])
        _escolher_para_apagar(
            compras,
            {"Data": "data_br", "Insumo": "insumo", "Quantidade": "quantidade",
             "Un.": "unidade_medida", "Fornecedor": "fornecedor", "Nota": "numero_nota",
             "Repetida": "repetida", "Observação": "observacao"},
            "corrigir_compras", crud.apagar_compras, "compra",
        )
    with aba_producoes:
        levas = crud.producoes_no_periodo(str(inicio), str(fim))
        for l in levas:
            l["data_br"] = _data_br(l["data"])
        _escolher_para_apagar(
            levas,
            {"Data": "data_br", "Produção": "producao", "Receitas": "receitas",
             "Quantidade": "quantidade_produzida", "Un.": "unidade_medida",
             "Observação": "observacao"},
            "corrigir_producoes", crud.apagar_producoes, "produção",
        )
    with aba_baixas:
        baixas = crud.baixas_no_periodo(str(inicio), str(fim))
        for b in baixas:
            b["data_br"] = _data_br(b["data"])
        _escolher_para_apagar(
            baixas,
            {"Data": "data_br", "Insumo": "insumo", "Quantidade": "quantidade",
             "Un.": "unidade_medida", "Motivo": "motivo", "Observação": "observacao"},
            "corrigir_baixas", crud.apagar_baixas, "baixa",
        )


# ---------- Navegação ----------

PG_DASHBOARD = st.Page(
    pagina_dashboard, title="Dashboard", icon=":material/dashboard:", default=True
)
PG_PAINEL = st.Page(
    pagina_painel, title="Painel de Estoque", icon=":material/inventory_2:", url_path="painel"
)
PG_SAIDA = st.Page(
    pagina_saida, title="Saída de Estoque", icon=":material/trending_down:",
    url_path="saida",
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
PG_NF_MANUAL = st.Page(
    pagina_nf_manual, title="Lançar Nota Fiscal", icon=":material/edit_note:",
    url_path="nota-manual",
)
PG_VENDA = st.Page(
    pagina_venda, title="Lançar Venda do Dia", icon=":material/point_of_sale:", url_path="venda"
)
PG_PRODUCAO = st.Page(
    pagina_producao, title="Lançar Produção", icon=":material/soup_kitchen:",
    url_path="producao",
)
PG_BAIXA = st.Page(
    pagina_baixa, title="Baixa de Estoque", icon=":material/remove_shopping_cart:",
    url_path="baixa",
)
PG_CORRIGIR = st.Page(
    pagina_corrigir, title="Corrigir Lançamentos", icon=":material/delete_sweep:",
    url_path="corrigir",
)
PG_ZIG = st.Page(
    pagina_zig, title="Importar Vendas (PDV)", icon=":material/receipt:", url_path="vendas-pdv"
)
PG_PERDAS = st.Page(
    pagina_perdas, title="Perdas e Reconciliação", icon=":material/scale:",
    url_path="perdas",
)
PG_ITENS_CONTAGEM = st.Page(
    pagina_itens_contagem, title="Itens da Contagem", icon=":material/checklist:",
    url_path="itens-contagem",
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
    "saida": PG_SAIDA,
    "insumos": PG_INSUMOS,
    "pratos": PG_PRATOS,
    "ficha": PG_FICHA,
    "ficha_import": PG_FICHA_IMPORT,
    "itens_contagem": PG_ITENS_CONTAGEM,
    "compra": PG_COMPRA,
    "nfe": PG_NFE,
    "nf_manual": PG_NF_MANUAL,
    "zig": PG_ZIG,
    "venda": PG_VENDA,
    "producao": PG_PRODUCAO,
    "baixa": PG_BAIXA,
    "contagem": PG_CONTAGEM,
    "corrigir": PG_CORRIGIR,
    "perdas": PG_PERDAS,
}


def _liberadas(*areas):
    return [PAGINAS_POR_AREA[a] for a in areas if a in MINHAS_AREAS]


# A ordem segue o uso: o que se consulta, o que se lança todo dia, a
# contagem da semana e, por último, os cadastros, que mudam pouco.
SECOES_DO_MENU = {
    "Visão geral": ("dashboard", "painel", "saida", "perdas"),
    "Lançamentos do dia": ("venda", "producao", "baixa", "compra", "nf_manual", "nfe",
                           "zig", "corrigir"),
    "Contagem": ("contagem", "itens_contagem"),
    "Cadastros": ("insumos", "pratos", "ficha", "ficha_import"),
}
menu = {}
for secao, areas in SECOES_DO_MENU.items():
    if _liberadas(*areas):
        menu[secao] = _liberadas(*areas)

menu["Conta"] = [PG_MINHA_CONTA]
if E_ADMIN:
    menu["Administração"] = [PG_APROVACOES, PG_USUARIOS]

# Um usuário aprovado mas ainda sem nenhuma área cai aqui: sem página
# nenhuma o st.navigation quebraria, então ele fica só com a conta dele.
if not any(chave in menu for chave in SECOES_DO_MENU):
    st.session_state["_sem_areas"] = True

# expanded: sem ele o Streamlit esconde o que passa de dez itens atrás
# de "View more", e a tela de contagem e os cadastros sumiam do menu.
navegacao = st.navigation(menu, expanded=True)

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
    # Com lançamento manual, o dia esquecido é a falha mais provável e a
    # única que não dá erro. O lembrete fica aqui, visível em qualquer tela,
    # para o buraco aparecer no dia seguinte e não na conferência da semana.
    if "venda" in MINHAS_AREAS:
        pendentes = crud.vendas_pendentes()
        if pendentes:
            dias = ", ".join(_data_br(d)[:5] for d in pendentes[-5:])
            antes = f"{len(pendentes) - 5} dia(s) antes e " if len(pendentes) > 5 else ""
            st.warning(f"📅 Venda não lançada: {antes}{dias}")
            st.page_link(PG_VENDA, label="Lançar agora", icon=":material/point_of_sale:")
    st.caption(f"Hoje: {crud.hoje().strftime('%d/%m/%Y')}")
    st.caption("Criado por Luis Felipe · © 2026 · Todos os direitos reservados")

if st.session_state.pop("_sem_areas", False):
    st.info(
        "Seu acesso foi aprovado, mas nenhuma área do sistema foi liberada "
        "para você ainda. Peça ao administrador."
    )


def _operacao_interrompida():
    """A conexão caiu ou uma consulta passou do tempo no meio da tela.

    Antes, isso era uma tela carregando sem fim (relato de 30/09/2026):
    agora a conexão tem limite de tempo, e o erro chega aqui. As gravações
    são tudo ou nada, então o que estava sendo gravado não ficou pela
    metade — ou foi inteiro, ou não foi.
    """
    database.descartar_conexao()
    st.error(
        "**A conexão com o banco caiu no meio da operação.** Nada fica gravado "
        "pela metade: o que estava sendo salvo ou foi inteiro, ou não foi. "
        "Tente de novo; se era uma gravação, confira o resultado depois.",
        icon=":material/cloud_off:",
    )
    if st.button("Tentar de novo", type="primary", icon=":material/refresh:",
                 key="tentar_de_novo_conexao"):
        st.rerun()


try:
    navegacao.run()
except database.BancoIndisponivel:
    _operacao_interrompida()
except Exception as erro:
    # OperationalError inclui a queda da conexão e o comando que passou do
    # tempo. Qualquer outro erro é defeito e continua aparecendo como tal.
    if not database.erro_de_conexao(erro):
        raise
    _operacao_interrompida()
