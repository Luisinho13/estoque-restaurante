"""
crud.py
Funções de negócio do sistema: cadastros, lançamentos e cálculo do
estoque teórico (o coração do projeto — é o que elimina a contagem semanal).

Lógica do cálculo de estoque teórico para um insumo:
    1. Pega a última contagem física registrada (se houver) como ponto de partida.
    2. Soma as entradas feitas depois dessa contagem: compras e, para item
       feito na cozinha, o que foi produzido.
    3. Subtrai as saídas, também depois dessa contagem: vendas × ficha do
       prato e o que cada produção gastou dos ingredientes.
    4. Resultado = estoque teórico atual, sem precisar contar nada fisicamente.

A venda desconta só o que está na ficha do prato. Se a parmegiana leva
molho ao sugo, a venda tira o molho, não o tomate: o tomate sai quando o
molho é produzido.
"""

import datetime

from database import get_connection

SEM_CONTAGEM = "sem contagem física ainda"

# O servidor do Streamlit Cloud roda em UTC, e o restaurante fecha de
# madrugada. Às 23h de Brasília o `date.today()` do servidor já virou o
# dia seguinte — quem lançasse as vendas no fim do expediente veria a data
# de amanhã preenchida no formulário, e o movimento da noite cairia no dia
# errado. A data do sistema passa a ser sempre a de Brasília.
try:
    from zoneinfo import ZoneInfo

    FUSO = ZoneInfo("America/Sao_Paulo")
except Exception:
    # Container sem a base de fusos instalada. O horário de Brasília é
    # UTC-3 fixo desde que o Brasil acabou com o horário de verão, em 2019.
    FUSO = datetime.timezone(datetime.timedelta(hours=-3))


def hoje() -> datetime.date:
    """A data de hoje no fuso do restaurante, não no do servidor."""
    return datetime.datetime.now(FUSO).date()


# ---------- Cadastros ----------

TIPOS_DE_INSUMO = {"cru": "Cru (comprado)", "producao": "Produção (feito na cozinha)"}


def cadastrar_insumo(nome: str, unidade_medida: str, estoque_minimo: float = 0,
                     tipo: str = "cru", rendimento: float = None):
    if tipo not in TIPOS_DE_INSUMO:
        raise ValueError(f"Tipo de insumo desconhecido: '{tipo}'.")
    conn = get_connection()
    conn.execute(
        """INSERT INTO insumos (nome, unidade_medida, estoque_minimo, tipo, rendimento)
           VALUES (?, ?, ?, ?, ?)""",
        (nome, unidade_medida, estoque_minimo, tipo,
         rendimento if tipo == "producao" else None),
    )
    conn.commit()
    conn.close()


def definir_tipo_do_insumo(nome: str, tipo: str):
    """Marca um insumo como cru ou produção.

    Voltar para cru apaga a ficha de produção dele: um item comprado não
    tem receita, e a ficha esquecida lá faria a tela de produção oferecer
    algo que ninguém produz. As produções já lançadas ficam, porque são
    história do estoque.
    """
    if tipo not in TIPOS_DE_INSUMO:
        raise ValueError(f"Tipo de insumo desconhecido: '{tipo}'.")
    conn = get_connection()
    try:
        insumo = conn.execute("SELECT id FROM insumos WHERE nome = ?", (nome,)).fetchone()
        if not insumo:
            raise ValueError(f"Insumo '{nome}' não encontrado.")
        if tipo == "cru":
            conn.execute("DELETE FROM ficha_producao WHERE producao_id = ?", (insumo["id"],))
            conn.execute("UPDATE insumos SET tipo = 'cru', rendimento = NULL WHERE id = ?",
                         (insumo["id"],))
        else:
            conn.execute("UPDATE insumos SET tipo = 'producao' WHERE id = ?", (insumo["id"],))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()


def tipos_dos_insumos() -> dict[str, str]:
    """Nome do insumo -> 'cru' ou 'producao'."""
    conn = get_connection()
    linhas = conn.execute("SELECT nome, tipo FROM insumos").fetchall()
    conn.close()
    return {linha["nome"]: linha["tipo"] for linha in linhas}


def cadastrar_prato(nome: str):
    conn = get_connection()
    conn.execute("INSERT INTO pratos (nome) VALUES (?)", (nome,))
    conn.commit()
    conn.close()


def definir_ficha_tecnica(prato_nome: str, insumo_nome: str, quantidade_por_prato: float):
    """Define quanto de um insumo é usado para preparar 1 unidade de um prato."""
    conn = get_connection()
    prato = conn.execute("SELECT id FROM pratos WHERE nome = ?", (prato_nome,)).fetchone()
    insumo = conn.execute("SELECT id FROM insumos WHERE nome = ?", (insumo_nome,)).fetchone()
    if not prato or not insumo:
        conn.close()
        raise ValueError("Prato ou insumo não encontrado.")

    conn.execute(
        """
        INSERT INTO ficha_tecnica (prato_id, insumo_id, quantidade_por_prato)
        VALUES (?, ?, ?)
        ON CONFLICT(prato_id, insumo_id)
        DO UPDATE SET quantidade_por_prato = excluded.quantidade_por_prato
        """,
        (prato["id"], insumo["id"], quantidade_por_prato),
    )
    conn.commit()
    conn.close()


def excluir_insumo(nome: str):
    """
    Exclui um insumo e todo o histórico ligado a ele (ficha técnica, ficha
    e lançamentos de produção, compras e contagens físicas). Use com
    cuidado: não tem como desfazer.
    """
    conn = get_connection()
    insumo = conn.execute("SELECT id FROM insumos WHERE nome = ?", (nome,)).fetchone()
    if not insumo:
        conn.close()
        raise ValueError(f"Insumo '{nome}' não encontrado.")

    insumo_id = insumo["id"]
    conn.execute("DELETE FROM ficha_tecnica WHERE insumo_id = ?", (insumo_id,))
    conn.execute(
        "DELETE FROM ficha_producao WHERE producao_id = ? OR insumo_id = ?",
        (insumo_id, insumo_id),
    )
    # As levas produzidas deste item somem com o que elas gastaram; e o que
    # este item gastou em levas de outras produções também sai.
    conn.execute(
        """DELETE FROM producoes_consumo WHERE insumo_id = ? OR producao_id IN
               (SELECT id FROM producoes WHERE insumo_id = ?)""",
        (insumo_id, insumo_id),
    )
    conn.execute("DELETE FROM producoes WHERE insumo_id = ?", (insumo_id,))
    conn.execute("DELETE FROM compras WHERE insumo_id = ?", (insumo_id,))
    conn.execute("DELETE FROM contagens_fisicas WHERE insumo_id = ?", (insumo_id,))
    conn.execute(
        """DELETE FROM contagens_itens WHERE item_id IN
               (SELECT id FROM itens_contagem WHERE insumo_id = ?)""",
        (insumo_id,),
    )
    conn.execute("DELETE FROM itens_contagem WHERE insumo_id = ?", (insumo_id,))
    conn.execute("DELETE FROM mapeamento_produtos_nfe WHERE insumo_id = ?", (insumo_id,))
    conn.execute("DELETE FROM insumos WHERE id = ?", (insumo_id,))
    conn.commit()
    conn.close()


def excluir_prato(nome: str):
    """
    Exclui um prato e todo o histórico ligado a ele (ficha técnica e
    vendas diárias). Use com cuidado: não tem como desfazer.
    """
    conn = get_connection()
    prato = conn.execute("SELECT id FROM pratos WHERE nome = ?", (nome,)).fetchone()
    if not prato:
        conn.close()
        raise ValueError(f"Prato '{nome}' não encontrado.")

    prato_id = prato["id"]
    conn.execute("DELETE FROM ficha_tecnica WHERE prato_id = ?", (prato_id,))
    conn.execute("DELETE FROM vendas_diarias WHERE prato_id = ?", (prato_id,))
    conn.execute("DELETE FROM mapeamento_produtos_zig WHERE prato_id = ?", (prato_id,))
    conn.execute("DELETE FROM pratos WHERE id = ?", (prato_id,))
    conn.commit()
    conn.close()


# ---------- Ficha técnica: leitura e edição ----------

# Há duas fichas, e é a separação entre elas que faz a venda descontar só
# o que vai no prato:
#
# - a do **prato** (ficha_tecnica): por porção vendida. Pode citar insumo
#   cru ou produção — a parmegiana leva o bife empanado e o molho ao sugo;
# - a da **produção** (ficha_producao): por receita feita na cozinha. É ela
#   que tira o tomate e a cebola do estoque, no dia em que o molho é feito.
#
# A tela de edição grava a ficha inteira de uma vez: o que sumiu da tabela
# sai da ficha. Tudo ou nada, como as outras operações em lote.

def _itens_da_ficha(conn, itens: list[dict], proprio_id: int = None) -> list[tuple]:
    """Resolve e valida as linhas de uma ficha antes de gravar qualquer coisa."""
    vistos, resolvidos = set(), []
    for item in itens:
        nome = item["insumo"]
        quantidade = float(item["quantidade"])
        if quantidade <= 0:
            raise ValueError(f"A quantidade de '{nome}' precisa ser maior que zero.")
        if nome in vistos:
            raise ValueError(f"'{nome}' aparece duas vezes na ficha. Deixe uma linha só.")
        vistos.add(nome)
        insumo = conn.execute("SELECT id FROM insumos WHERE nome = ?", (nome,)).fetchone()
        if not insumo:
            raise ValueError(f"Insumo '{nome}' não encontrado.")
        if proprio_id is not None and insumo["id"] == proprio_id:
            raise ValueError(f"'{nome}' não pode ser ingrediente dele mesmo.")
        resolvidos.append((insumo["id"], quantidade))
    return resolvidos


def ficha_do_prato(prato_nome: str) -> list[dict]:
    """O que 1 porção do prato tira do estoque, linha a linha."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT i.nome AS insumo, ft.quantidade_por_prato AS quantidade,
               i.unidade_medida, i.tipo
        FROM ficha_tecnica ft
        JOIN pratos p ON p.id = ft.prato_id
        JOIN insumos i ON i.id = ft.insumo_id
        WHERE p.nome = ?
        ORDER BY i.nome
        """,
        (prato_nome,),
    ).fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


def salvar_ficha_do_prato(prato_nome: str, itens: list[dict]) -> int:
    """Troca a ficha do prato inteira pela lista `itens` ({'insumo', 'quantidade'}).

    Lista vazia apaga a ficha — o prato passa a não descontar nada, e a
    tela avisa isso antes de gravar.
    """
    conn = get_connection()
    try:
        prato = conn.execute("SELECT id FROM pratos WHERE nome = ?", (prato_nome,)).fetchone()
        if not prato:
            raise ValueError(f"Prato '{prato_nome}' não encontrado.")
        resolvidos = _itens_da_ficha(conn, itens)
        conn.execute("DELETE FROM ficha_tecnica WHERE prato_id = ?", (prato["id"],))
        for insumo_id, quantidade in resolvidos:
            conn.execute(
                """INSERT INTO ficha_tecnica (prato_id, insumo_id, quantidade_por_prato)
                   VALUES (?, ?, ?)""",
                (prato["id"], insumo_id, quantidade),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return len(resolvidos)


def listar_producoes() -> list[dict]:
    """Os itens feitos na cozinha, com o rendimento e o tamanho da ficha."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT i.nome, i.unidade_medida, i.rendimento,
               (SELECT COUNT(*) FROM ficha_producao fp
                WHERE fp.producao_id = i.id) AS itens_na_ficha
        FROM insumos i
        WHERE i.tipo = 'producao'
        ORDER BY i.nome
        """
    ).fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


def ficha_da_producao(producao_nome: str) -> dict:
    """Receita de uma produção: o que 1 receita gasta e quanto ela rende."""
    conn = get_connection()
    producao = conn.execute(
        "SELECT id, unidade_medida, rendimento, tipo FROM insumos WHERE nome = ?",
        (producao_nome,),
    ).fetchone()
    if not producao:
        conn.close()
        raise ValueError(f"Produção '{producao_nome}' não encontrada.")
    linhas = conn.execute(
        """
        SELECT i.nome AS insumo, fp.quantidade_por_receita AS quantidade,
               i.unidade_medida, i.tipo
        FROM ficha_producao fp
        JOIN insumos i ON i.id = fp.insumo_id
        WHERE fp.producao_id = ?
        ORDER BY i.nome
        """,
        (producao["id"],),
    ).fetchall()
    conn.close()
    return {
        "producao": producao_nome,
        "unidade_medida": producao["unidade_medida"],
        "rendimento": producao["rendimento"],
        "itens": [dict(linha) for linha in linhas],
    }


def _caminho_de_ciclo(conn, producao_id: int, ingredientes: list[int]) -> list[str] | None:
    """Procura uma volta do tipo "molho A leva molho B, que leva molho A".

    Uma volta dessas não trava a conta de estoque (a produção grava o que
    gastou no momento), mas é receita impossível e quase sempre ingrediente
    escolhido errado. Devolve os nomes do caminho, ou None.
    """
    arestas = {}
    for linha in conn.execute(
        "SELECT producao_id, insumo_id FROM ficha_producao WHERE producao_id <> ?",
        (producao_id,),
    ).fetchall():
        arestas.setdefault(linha["producao_id"], []).append(linha["insumo_id"])
    arestas[producao_id] = list(ingredientes)

    def visitar(atual, caminho):
        for proximo in arestas.get(atual, []):
            if proximo == producao_id:
                return caminho + [proximo]
            if proximo not in caminho:
                achado = visitar(proximo, caminho + [proximo])
                if achado:
                    return achado
        return None

    caminho = visitar(producao_id, [producao_id])
    if not caminho:
        return None
    nomes = {
        linha["id"]: linha["nome"]
        for linha in conn.execute("SELECT id, nome FROM insumos").fetchall()
    }
    return [nomes[i] for i in caminho]


def salvar_ficha_da_producao(producao_nome: str, itens: list[dict],
                             rendimento: float) -> int:
    """Troca a receita da produção inteira e grava o rendimento de 1 receita."""
    if rendimento is None or float(rendimento) <= 0:
        raise ValueError("Informe quanto 1 receita rende, maior que zero.")

    conn = get_connection()
    try:
        producao = conn.execute(
            "SELECT id, tipo FROM insumos WHERE nome = ?", (producao_nome,)
        ).fetchone()
        if not producao:
            raise ValueError(f"Produção '{producao_nome}' não encontrada.")
        if producao["tipo"] != "producao":
            raise ValueError(
                f"'{producao_nome}' está cadastrado como insumo cru. Marque-o "
                "como produção na tela de Insumos antes de dar uma receita a ele."
            )
        resolvidos = _itens_da_ficha(conn, itens, proprio_id=producao["id"])
        ciclo = _caminho_de_ciclo(conn, producao["id"], [i for i, _ in resolvidos])
        if ciclo:
            raise ValueError(
                "Essa receita fecha uma volta: " + " → ".join(ciclo) +
                ". Uma produção não pode depender dela mesma."
            )
        conn.execute("DELETE FROM ficha_producao WHERE producao_id = ?", (producao["id"],))
        for insumo_id, quantidade in resolvidos:
            conn.execute(
                """INSERT INTO ficha_producao (producao_id, insumo_id, quantidade_por_receita)
                   VALUES (?, ?, ?)""",
                (producao["id"], insumo_id, quantidade),
            )
        conn.execute("UPDATE insumos SET rendimento = ? WHERE id = ?",
                     (float(rendimento), producao["id"]))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return len(resolvidos)


def onde_o_insumo_e_usado(insumo_nome: str) -> list[str]:
    """Pratos e produções cuja ficha cita o insumo."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT p.nome AS nome FROM ficha_tecnica ft
        JOIN pratos p ON p.id = ft.prato_id
        JOIN insumos i ON i.id = ft.insumo_id
        WHERE i.nome = ?
        UNION
        SELECT pr.nome AS nome FROM ficha_producao fp
        JOIN insumos pr ON pr.id = fp.producao_id
        JOIN insumos i ON i.id = fp.insumo_id
        WHERE i.nome = ?
        ORDER BY nome
        """,
        (insumo_nome, insumo_nome),
    ).fetchall()
    conn.close()
    return [linha["nome"] for linha in linhas]

# ---------- Lançamentos ----------

def registrar_compra(insumo_nome: str, quantidade: float, data: str,
                      fornecedor: str = None, observacao: str = None,
                      numero_nota: str = None):
    conn = get_connection()
    insumo = conn.execute("SELECT id FROM insumos WHERE nome = ?", (insumo_nome,)).fetchone()
    if not insumo:
        conn.close()
        raise ValueError(f"Insumo '{insumo_nome}' não encontrado.")

    conn.execute(
        """INSERT INTO compras (insumo_id, quantidade, data, fornecedor, observacao, numero_nota)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (insumo["id"], quantidade, data, fornecedor, observacao, numero_nota),
    )
    conn.commit()
    conn.close()


def registrar_compras_em_lote(itens: list[dict], data: str, fornecedor: str = None,
                               numero_nota: str = None, observacao: str = None) -> int:
    """Lança de uma vez todos os itens de uma nota digitada à mão.

    `itens` é uma lista de {'insumo': nome, 'quantidade': float}. Os
    insumos são todos resolvidos **antes** de qualquer INSERT: se um nome
    estiver errado, nada é gravado. Meia nota lançada seria pior que nota
    nenhuma — o estoque ficaria alto sem ninguém saber de onde veio.
    """
    if not itens:
        raise ValueError("A nota não tem nenhum item para lançar.")

    conn = get_connection()
    try:
        resolvidos = []
        for item in itens:
            quantidade = float(item["quantidade"])
            if quantidade <= 0:
                raise ValueError(
                    f"A quantidade de '{item['insumo']}' precisa ser maior que zero."
                )
            insumo = conn.execute(
                "SELECT id FROM insumos WHERE nome = ?", (item["insumo"],)
            ).fetchone()
            if not insumo:
                raise ValueError(f"Insumo '{item['insumo']}' não encontrado.")
            resolvidos.append((insumo["id"], quantidade))

        for insumo_id, quantidade in resolvidos:
            conn.execute(
                """INSERT INTO compras
                       (insumo_id, quantidade, data, fornecedor, observacao, numero_nota)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (insumo_id, quantidade, data, fornecedor, observacao, numero_nota),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return len(resolvidos)


def nota_ja_lancada(numero_nota: str, fornecedor: str = None) -> dict | None:
    """Procura uma nota já lançada com esse número, para não lançar duas vezes.

    O número da nota sozinho não é único no mundo — dois fornecedores
    podem ter a nota 1234 —, então o fornecedor entra na busca quando é
    informado. Devolve um resumo do que foi lançado, ou None.
    """
    if not numero_nota:
        return None

    conn = get_connection()
    if fornecedor:
        linha = conn.execute(
            """SELECT COUNT(*) AS itens, MIN(data) AS data
               FROM compras WHERE numero_nota = ? AND fornecedor = ?""",
            (numero_nota, fornecedor),
        ).fetchone()
    else:
        linha = conn.execute(
            """SELECT COUNT(*) AS itens, MIN(data) AS data
               FROM compras WHERE numero_nota = ?""",
            (numero_nota,),
        ).fetchone()
    conn.close()

    if not linha or not linha["itens"]:
        return None
    return {"itens": linha["itens"], "data": linha["data"]}


def total_vendido_no_dia(prato_nome: str, data: str) -> float:
    """Soma a quantidade de um prato já lançada numa data (0 se não houver nada)."""
    conn = get_connection()
    prato = conn.execute("SELECT id FROM pratos WHERE nome = ?", (prato_nome,)).fetchone()
    if not prato:
        conn.close()
        raise ValueError(f"Prato '{prato_nome}' não encontrado.")

    total = conn.execute(
        "SELECT COALESCE(SUM(quantidade), 0) AS total FROM vendas_diarias WHERE prato_id = ? AND data = ?",
        (prato["id"], data),
    ).fetchone()["total"]
    conn.close()
    return total


def registrar_venda_diaria(prato_nome: str, quantidade: int, data: str):
    conn = get_connection()
    prato = conn.execute("SELECT id FROM pratos WHERE nome = ?", (prato_nome,)).fetchone()
    if not prato:
        conn.close()
        raise ValueError(f"Prato '{prato_nome}' não encontrado.")

    conn.execute(
        "INSERT INTO vendas_diarias (prato_id, quantidade, data) VALUES (?, ?, ?)",
        (prato["id"], quantidade, data),
    )
    conn.commit()
    conn.close()


def substituir_venda_diaria(prato_nome: str, quantidade: int, data: str):
    """
    Deixa a venda de um prato num dia valendo exatamente `quantidade`, apagando
    o que já havia sido lançado naquele dia. É o que a importação da Zig usa:
    reimportar o mesmo relatório corrige o dia em vez de somar em cima.
    """
    conn = get_connection()
    prato = conn.execute("SELECT id FROM pratos WHERE nome = ?", (prato_nome,)).fetchone()
    if not prato:
        conn.close()
        raise ValueError(f"Prato '{prato_nome}' não encontrado.")

    conn.execute(
        "DELETE FROM vendas_diarias WHERE prato_id = ? AND data = ?", (prato["id"], data)
    )
    conn.execute(
        "INSERT INTO vendas_diarias (prato_id, quantidade, data) VALUES (?, ?, ?)",
        (prato["id"], quantidade, data),
    )
    conn.commit()
    conn.close()


def lancar_venda(prato_nome: str, quantidade: int, data: str,
                 substituir: bool = False) -> float:
    """Lança a venda de um prato num dia e devolve o total gravado nesse dia.

    É o caminho único da tela de lançamento manual. Duas coisas que a
    versão anterior não fazia e custaram caro:

    - **devolve o total lido de volta do banco**, depois do commit, em vez
      de confiar no número que veio do formulário. A tela mostra o que
      está gravado; se o INSERT não tiver pegado, o número não muda e o
      problema aparece na hora, em vez de só na conferência da semana;
    - **recusa quantidade zero ou negativa**, que só criava linha inútil.

    `substituir=True` deixa o dia valendo exatamente `quantidade`, como
    faz a importação da Zig. `False` soma ao que já havia.
    """
    if quantidade <= 0:
        raise ValueError("A quantidade vendida precisa ser maior que zero.")

    conn = get_connection()
    prato = conn.execute("SELECT id FROM pratos WHERE nome = ?", (prato_nome,)).fetchone()
    if not prato:
        conn.close()
        raise ValueError(f"Prato '{prato_nome}' não encontrado.")

    prato_id = prato["id"]
    if substituir:
        conn.execute(
            "DELETE FROM vendas_diarias WHERE prato_id = ? AND data = ?", (prato_id, data)
        )
    conn.execute(
        "INSERT INTO vendas_diarias (prato_id, quantidade, data) VALUES (?, ?, ?)",
        (prato_id, quantidade, data),
    )
    conn.commit()

    total = conn.execute(
        """SELECT COALESCE(SUM(quantidade), 0) AS total
           FROM vendas_diarias WHERE prato_id = ? AND data = ?""",
        (prato_id, data),
    ).fetchone()["total"]
    conn.close()
    return total


def vendas_do_dia(data: str) -> list[dict]:
    """Tudo que está lançado num dia, prato a prato. É a conferência da tela."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT p.nome AS prato, SUM(v.quantidade) AS quantidade
        FROM vendas_diarias v
        JOIN pratos p ON p.id = v.prato_id
        WHERE v.data = ?
        GROUP BY p.id, p.nome
        ORDER BY p.nome
        """,
        (data,),
    ).fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


def impacto_da_venda(prato_nome: str, quantidade: float) -> list[dict]:
    """Quanto de cada insumo essa venda tira do estoque, pela ficha técnica.

    Serve para a tela mostrar o efeito do lançamento no mesmo instante.
    Prato sem ficha técnica devolve lista vazia — e essa lista vazia é
    informação: é exatamente o caso em que lançar a venda não mexe em
    nada no estoque.
    """
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT i.nome AS insumo, i.unidade_medida,
               ft.quantidade_por_prato
        FROM ficha_tecnica ft
        JOIN pratos p ON p.id = ft.prato_id
        JOIN insumos i ON i.id = ft.insumo_id
        WHERE p.nome = ?
        ORDER BY i.nome
        """,
        (prato_nome,),
    ).fetchall()
    conn.close()
    return [
        {
            "insumo": linha["insumo"],
            "unidade_medida": linha["unidade_medida"],
            "consumo": round(linha["quantidade_por_prato"] * quantidade, 3),
        }
        for linha in linhas
    ]


def registrar_contagem_fisica(insumo_nome: str, quantidade_contada: float, data: str,
                               observacao: str = None):
    conn = get_connection()
    insumo = conn.execute("SELECT id FROM insumos WHERE nome = ?", (insumo_nome,)).fetchone()
    if not insumo:
        conn.close()
        raise ValueError(f"Insumo '{insumo_nome}' não encontrado.")

    conn.execute(
        """INSERT INTO contagens_fisicas (insumo_id, quantidade_contada, data, observacao)
           VALUES (?, ?, ?, ?)""",
        (insumo["id"], quantidade_contada, data, observacao),
    )
    conn.commit()
    conn.close()


def contagens_do_dia(data: str) -> dict:
    """{nome do insumo: quantidade contada} numa data. Serve para pré-preencher a tela."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT i.nome, c.quantidade_contada
        FROM contagens_fisicas c
        JOIN insumos i ON i.id = c.insumo_id
        WHERE c.data = ?
        ORDER BY c.id
        """,
        (data,),
    ).fetchall()
    conn.close()
    # O último lançamento do dia é o que vale, caso exista mais de um.
    return {linha["nome"]: linha["quantidade_contada"] for linha in linhas}


# ---------- Contagem pela planilha ----------
# A contagem física é feita linha a linha da planilha do restaurante, na
# unidade em que cada coisa está na prateleira (peça, pacote, garrafa). O
# cálculo de estoque, porém, trabalha por insumo e na unidade da ficha
# técnica. As funções abaixo fazem essa ponte: cada linha tem um fator, e
# o insumo recebe a soma das suas linhas convertidas.

def itens_da_contagem() -> list[dict]:
    """As linhas da planilha de contagem, na ordem dela, com o insumo de cada uma."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT ic.id, ic.descricao, ic.secao, ic.ordem, ic.unidade_contagem,
               ic.fator_conversao, i.nome AS insumo, i.unidade_medida AS unidade_insumo
        FROM itens_contagem ic
        JOIN insumos i ON i.id = ic.insumo_id
        ORDER BY ic.ordem
        """
    ).fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


def contagem_por_item_do_dia(data: str) -> dict:
    """{id do item: quantidade na unidade da contagem} já gravados numa data."""
    conn = get_connection()
    linhas = conn.execute(
        "SELECT item_id, quantidade FROM contagens_itens WHERE data = ?", (data,)
    ).fetchall()
    conn.close()
    return {linha["item_id"]: linha["quantidade"] for linha in linhas}


def resumo_da_contagem(por_item: dict, por_insumo: dict, itens: list[dict] = None) -> dict:
    """Converte o que foi digitado em contagem por insumo, sem gravar nada.

    `por_item` é {id do item: quantidade na unidade da linha}; `por_insumo`
    é {nome do insumo: quantidade}, para os insumos que não estão na
    planilha e são contados direto.

    Duas regras, e é por causa delas que isto é uma função e não uma soma:

    - **Um insumo é contado se qualquer linha dele foi preenchida, e aí as
      linhas irmãs em branco valem zero.** O branco continua significando
      "não mexe" para o insumo como um todo; mas, se a alcatra em peça foi
      contada e a porcionada não, gravar só a peça como estoque total da
      alcatra seria uma contagem pela metade. As irmãs em branco voltam
      listadas em 'em_branco', para quem conta conferir antes de gravar.
    - **Linha preenchida sem fator trava o insumo inteiro.** Sem saber
      quantos kg tem um maço, não há número honesto para gravar; o insumo
      volta em 'sem_fator' e fica de fora, e os outros seguem.
    """
    itens = itens if itens is not None else itens_da_contagem()
    por_id = {item["id"]: item for item in itens}
    linhas_do_insumo = {}
    for item in itens:
        linhas_do_insumo.setdefault(item["insumo"], []).append(item)

    totais, sem_fator, em_branco, composicao = {}, {}, {}, {}
    contados = {por_id[i]["insumo"] for i in por_item if i in por_id}
    for insumo in sorted(contados):
        total, partes = 0.0, []
        for item in linhas_do_insumo[insumo]:
            quantidade = por_item.get(item["id"])
            if quantidade is None:
                em_branco.setdefault(insumo, []).append(item["descricao"])
                continue
            if quantidade < 0:
                raise ValueError(f"A contagem de '{item['descricao']}' não pode ser negativa.")
            if item["fator_conversao"] is None:
                sem_fator.setdefault(insumo, []).append(item["descricao"])
                continue
            total += quantidade * item["fator_conversao"]
            partes.append(f"{quantidade:g} {item['unidade_contagem']} de {item['descricao']}")
        if insumo in sem_fator:
            em_branco.pop(insumo, None)
            continue
        totais[insumo] = round(total, 4)
        composicao[insumo] = partes

    for insumo, quantidade in por_insumo.items():
        if quantidade < 0:
            raise ValueError(f"A contagem de '{insumo}' não pode ser negativa.")
        if insumo in linhas_do_insumo:
            raise ValueError(
                f"'{insumo}' é contado pelas linhas da planilha, não direto."
            )
        totais[insumo] = float(quantidade)
        composicao[insumo] = []

    return {
        "totais": totais,
        "sem_fator": sem_fator,
        "em_branco": em_branco,
        "composicao": composicao,
    }


def registrar_contagem_pela_planilha(por_item: dict, por_insumo: dict, data: str,
                                     observacao: str = None) -> dict:
    """Grava a contagem do dia linha a linha e o total de cada insumo.

    Guarda as duas coisas, na mesma transação: o que foi digitado em cada
    linha (`contagens_itens`, para a tela reabrir preenchida e para saber
    de onde saiu cada total) e o total convertido de cada insumo
    (`contagens_fisicas`, que é o que o cálculo de estoque usa).

    Vale o mesmo contrato da contagem por insumo: tudo ou nada, e gravar
    de novo no mesmo dia substitui em vez de somar. Insumo com linha sem
    fator não é gravado (ver `resumo_da_contagem`).
    """
    itens = itens_da_contagem()
    resumo = resumo_da_contagem(por_item, por_insumo, itens)
    if not resumo["totais"]:
        raise ValueError("Nenhuma contagem que dê para gravar.")

    ids_de_insumo = {}
    gravaveis = {i["id"] for i in itens if i["insumo"] in resumo["totais"]}

    conn = get_connection()
    try:
        for insumo in resumo["totais"]:
            linha = conn.execute("SELECT id FROM insumos WHERE nome = ?", (insumo,)).fetchone()
            if not linha:
                raise ValueError(f"Insumo '{insumo}' não encontrado.")
            ids_de_insumo[insumo] = linha["id"]

        for item_id in gravaveis:
            conn.execute(
                "DELETE FROM contagens_itens WHERE item_id = ? AND data = ?",
                (item_id, data),
            )
            if item_id in por_item:
                conn.execute(
                    "INSERT INTO contagens_itens (item_id, data, quantidade) VALUES (?, ?, ?)",
                    (item_id, data, float(por_item[item_id])),
                )

        for insumo, total in resumo["totais"].items():
            partes = resumo["composicao"][insumo]
            detalhe = "; ".join(partes) if len(partes) > 1 else None
            nota = " · ".join(t for t in (observacao, detalhe) if t) or None
            conn.execute(
                "DELETE FROM contagens_fisicas WHERE insumo_id = ? AND data = ?",
                (ids_de_insumo[insumo], data),
            )
            conn.execute(
                """INSERT INTO contagens_fisicas
                       (insumo_id, quantidade_contada, data, observacao)
                   VALUES (?, ?, ?, ?)""",
                (ids_de_insumo[insumo], total, data, nota),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return resumo


def atualizar_fatores_da_contagem(fatores: dict) -> int:
    """Grava o fator de várias linhas da contagem: {id do item: fator}.

    Um fator vazio volta a ser "a definir". Zero não é aceito: uma linha
    que converte para zero apagaria o insumo em silêncio em toda contagem.
    """
    if not fatores:
        raise ValueError("Nenhum fator preenchido para gravar.")
    conn = get_connection()
    try:
        for item_id, fator in fatores.items():
            if fator is not None and fator <= 0:
                raise ValueError("O fator precisa ser maior que zero.")
            cursor = conn.execute(
                "UPDATE itens_contagem SET fator_conversao = ? WHERE id = ?",
                (fator, item_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Item de contagem {item_id} não encontrado.")
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return len(fatores)


def lancar_vendas_em_lote(itens: list[dict], data: str) -> dict:
    """Lança a venda de vários pratos num dia só.

    `itens` é uma lista de {'prato': nome, 'quantidade': int}. Cada prato
    passa a valer exatamente a quantidade informada naquele dia:

    - quantidade maior que zero **substitui** o total do prato no dia;
    - quantidade zero **apaga** o lançamento daquele prato no dia, que é
      como se corrige um prato lançado por engano;
    - prato que não estiver na lista não é tocado.

    Devolve quantos pratos foram gravados e quantos foram apagados.
    """
    if not itens:
        raise ValueError("Nenhuma venda preenchida para gravar.")

    conn = get_connection()
    try:
        resolvidos = []
        for item in itens:
            quantidade = int(item["quantidade"])
            if quantidade < 0:
                raise ValueError(
                    f"A venda de '{item['prato']}' não pode ser negativa."
                )
            prato = conn.execute(
                "SELECT id FROM pratos WHERE nome = ?", (item["prato"],)
            ).fetchone()
            if not prato:
                raise ValueError(f"Prato '{item['prato']}' não encontrado.")
            resolvidos.append((prato["id"], quantidade))

        gravados = apagados = 0
        for prato_id, quantidade in resolvidos:
            conn.execute(
                "DELETE FROM vendas_diarias WHERE prato_id = ? AND data = ?",
                (prato_id, data),
            )
            if quantidade > 0:
                conn.execute(
                    "INSERT INTO vendas_diarias (prato_id, quantidade, data) VALUES (?, ?, ?)",
                    (prato_id, quantidade, data),
                )
                gravados += 1
            else:
                apagados += 1
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return {"gravados": gravados, "apagados": apagados}


def atualizar_estoques_minimos(itens: list[dict]) -> int:
    """Grava o estoque mínimo de vários insumos de uma vez.

    O mínimo é o que liga a camada de alerta do sistema — sem ele, o
    semáforo do painel fica sempre verde e o aviso de reposição nunca
    dispara. Definir um a um, em mais de cem insumos, é o tipo de tarefa
    que não acontece nunca.
    """
    if not itens:
        raise ValueError("Nenhum mínimo preenchido para gravar.")

    conn = get_connection()
    try:
        for item in itens:
            minimo = float(item["estoque_minimo"])
            if minimo < 0:
                raise ValueError(
                    f"O mínimo de '{item['insumo']}' não pode ser negativo."
                )
            cursor = conn.execute(
                "UPDATE insumos SET estoque_minimo = ? WHERE nome = ?",
                (minimo, item["insumo"]),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Insumo '{item['insumo']}' não encontrado.")
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return len(itens)


# ---------- O cálculo principal ----------

# ---------- Produção ----------

# Produzir um molho é um movimento de estoque com dois lados: entra o molho
# e saem os ingredientes da receita. Quem lança diz quantas receitas fez e
# quanto rendeu; o cru que sai é a ficha × receitas, e não depende do
# rendimento — que na planilha da cozinha está errado em vários molhos.
#
# O que a leva gastou é gravado em producoes_consumo no momento do
# lançamento, em vez de recalculado pela ficha a cada consulta. Se a
# receita for editada amanhã, a produção de hoje continua tendo gastado o
# que gastou.

def impacto_da_producao(producao_nome: str, receitas: float) -> list[dict]:
    """Quanto de cada ingrediente sai do estoque ao fazer `receitas` receitas."""
    ficha = ficha_da_producao(producao_nome)
    return [
        {
            "insumo": item["insumo"],
            "unidade_medida": item["unidade_medida"],
            "tipo": item["tipo"],
            "consumo": round(item["quantidade"] * receitas, 3),
        }
        for item in ficha["itens"]
    ]


def producoes_do_dia(producao_nome: str, data: str) -> dict:
    """Quantas levas daquela produção já estão lançadas na data."""
    conn = get_connection()
    linha = conn.execute(
        """
        SELECT COUNT(p.id) AS levas, COALESCE(SUM(p.quantidade_produzida), 0) AS produzido
        FROM producoes p JOIN insumos i ON i.id = p.insumo_id
        WHERE i.nome = ? AND p.data = ?
        """,
        (producao_nome, data),
    ).fetchone()
    conn.close()
    return {"levas": linha["levas"], "produzido": linha["produzido"]}


def registrar_producao(producao_nome: str, receitas: float, quantidade_produzida: float,
                       data: str, observacao: str = None) -> int:
    """Lança uma leva: entra o produzido, sai o que a receita gasta. Devolve o id.

    Recusa produção sem ficha. Ela até poderia entrar só com o produzido,
    mas aí o molho apareceria no estoque sem nenhum tomate ter saído, e
    ninguém perceberia.
    """
    receitas = float(receitas)
    quantidade_produzida = float(quantidade_produzida)
    if receitas <= 0:
        raise ValueError("Informe quantas receitas foram feitas, maior que zero.")
    if quantidade_produzida <= 0:
        raise ValueError("Informe quanto rendeu, maior que zero.")

    conn = get_connection()
    try:
        producao = conn.execute(
            "SELECT id, tipo FROM insumos WHERE nome = ?", (producao_nome,)
        ).fetchone()
        if not producao:
            raise ValueError(f"Produção '{producao_nome}' não encontrada.")
        if producao["tipo"] != "producao":
            raise ValueError(f"'{producao_nome}' não está cadastrado como produção.")
        ficha = conn.execute(
            """SELECT insumo_id, quantidade_por_receita FROM ficha_producao
               WHERE producao_id = ?""",
            (producao["id"],),
        ).fetchall()
        if not ficha:
            raise ValueError(
                f"'{producao_nome}' ainda não tem ficha de produção. Cadastre a "
                "receita na tela Ficha Técnica antes de lançar."
            )

        producao_id = conn.execute(
            """INSERT INTO producoes (insumo_id, data, receitas, quantidade_produzida, observacao)
               VALUES (?, ?, ?, ?, ?) RETURNING id""",
            (producao["id"], data, receitas, quantidade_produzida, observacao or None),
        ).fetchone()["id"]
        for linha in ficha:
            conn.execute(
                """INSERT INTO producoes_consumo (producao_id, insumo_id, quantidade)
                   VALUES (?, ?, ?)""",
                (producao_id, linha["insumo_id"], linha["quantidade_por_receita"] * receitas),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return producao_id


def producoes_no_periodo(inicio: str, fim: str) -> list[dict]:
    """As levas lançadas entre duas datas (inclusive), da mais recente para trás."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT p.id, p.data, i.nome AS producao, p.receitas,
               p.quantidade_produzida, i.unidade_medida,
               COALESCE(p.observacao, '') AS observacao
        FROM producoes p JOIN insumos i ON i.id = p.insumo_id
        WHERE p.data >= ? AND p.data <= ?
        ORDER BY p.data DESC, p.id DESC
        """,
        (inicio, fim),
    ).fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


def consumo_da_producao(producao_id: int) -> list[dict]:
    """O que uma leva já lançada gastou, como ficou gravado."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT i.nome AS insumo, pc.quantidade, i.unidade_medida
        FROM producoes_consumo pc JOIN insumos i ON i.id = pc.insumo_id
        WHERE pc.producao_id = ?
        ORDER BY i.nome
        """,
        (producao_id,),
    ).fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


def excluir_producao(producao_id: int):
    """Apaga uma leva lançada: o produzido sai e os ingredientes voltam."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM producoes_consumo WHERE producao_id = ?", (producao_id,))
        apagadas = conn.execute(
            "DELETE FROM producoes WHERE id = ?", (producao_id,)
        ).rowcount
        if not apagadas:
            raise ValueError("Essa produção não existe mais.")
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()


# ---------- Estoque teórico ----------

# Todo movimento que mexe no estoque, numa lista só: cada linha diz qual
# insumo, em que dia, quanto entrou e quanto saiu. As contas de estoque,
# saída e perda leem daqui, para que um tipo novo de movimento entre em
# um lugar e não em cinco.
#
# - compra: entra o insumo comprado;
# - produção: entra o item produzido;
# - venda: sai o que a ficha do prato manda (só o primeiro nível);
# - gasto de produção: sai o que cada leva gastou, como foi gravado.
SQL_MOVIMENTOS = """
    SELECT insumo_id, data, quantidade AS entrada, 0.0 AS saida
    FROM compras
    UNION ALL
    SELECT insumo_id, data, quantidade_produzida, 0.0
    FROM producoes
    UNION ALL
    SELECT ft.insumo_id, v.data, 0.0, v.quantidade * ft.quantidade_por_prato
    FROM vendas_diarias v
    JOIN ficha_tecnica ft ON ft.prato_id = v.prato_id
    UNION ALL
    SELECT pc.insumo_id, p.data, 0.0, pc.quantidade
    FROM producoes_consumo pc
    JOIN producoes p ON p.id = pc.producao_id
"""

def calcular_estoque_teorico(insumo_nome: str) -> dict:
    """
    Calcula o estoque teórico atual de um insumo:
    última contagem física + entradas - saídas, desde a data dessa contagem.
    """
    for estoque in _estoques("WHERE i.nome = ?", (insumo_nome,)):
        return estoque
    raise ValueError(f"Insumo '{insumo_nome}' não encontrado.")


# A conta do estoque para todos os insumos de uma vez. A versão antiga
# chamava a de um insumo em laço, o que dava 4 consultas por insumo —
# irrelevante num arquivo SQLite local, mas fatal num banco remoto: com 27
# insumos eram 109 idas ao servidor, cerca de 27 segundos só para montar o
# Dashboard. Aqui é uma consulta só.
#
# A lógica é a de sempre: baseline = última contagem física, mais entradas
# e menos saídas a partir dela, sempre com >= (vendas do próprio dia da
# contagem precisam ser descontadas). O que mudou em 24/09/2026 é só de
# onde vêm entradas e saídas: de SQL_MOVIMENTOS, que inclui a produção.
SQL_ESTOQUE_DE_TODOS = f"""
    WITH ultima AS (
        SELECT insumo_id, MAX(data) AS data_baseline
        FROM contagens_fisicas
        GROUP BY insumo_id
    ),
    movimentos AS ({SQL_MOVIMENTOS}),
    desde_a_contagem AS (
        SELECT m.insumo_id,
               SUM(m.entrada) AS total_entradas,
               SUM(m.saida) AS total_saidas
        FROM movimentos m
        LEFT JOIN ultima u ON u.insumo_id = m.insumo_id
        WHERE m.data >= COALESCE(u.data_baseline, '0000-00-00')
        GROUP BY m.insumo_id
    )
    SELECT
        i.nome,
        i.unidade_medida,
        i.estoque_minimo,
        i.tipo,
        u.data_baseline,
        COALESCE((
            SELECT c.quantidade_contada
            FROM contagens_fisicas c
            WHERE c.insumo_id = i.id AND c.data = u.data_baseline
            ORDER BY c.id DESC
            LIMIT 1
        ), 0) AS baseline,
        COALESCE(d.total_entradas, 0) AS total_entradas,
        COALESCE(d.total_saidas, 0) AS total_saidas
    FROM insumos i
    LEFT JOIN ultima u ON u.insumo_id = i.id
    LEFT JOIN desde_a_contagem d ON d.insumo_id = i.id
"""


def _estoques(filtro: str = "", parametros: tuple = ()) -> list[dict]:
    conn = get_connection()
    linhas = conn.execute(f"{SQL_ESTOQUE_DE_TODOS} {filtro} ORDER BY i.nome",
                          parametros).fetchall()
    conn.close()

    resultado = []
    for linha in linhas:
        estoque_atual = linha["baseline"] + linha["total_entradas"] - linha["total_saidas"]
        resultado.append({
            "insumo": linha["nome"],
            "unidade_medida": linha["unidade_medida"],
            "tipo": linha["tipo"],
            "estoque_minimo": linha["estoque_minimo"],
            "estoque_atual": round(estoque_atual, 1),
            "abaixo_do_minimo": estoque_atual < linha["estoque_minimo"],
            "baseline_usada": linha["data_baseline"] or SEM_CONTAGEM,
        })
    return resultado


def calcular_estoque_todos_insumos() -> list[dict]:
    return _estoques()


# ---------- Mapeamento de produtos de nota fiscal (NF-e) ----------

def mapear_produto_nfe(fornecedor_cnpj: str, codigo_produto: str, descricao_produto: str,
                        insumo_nome: str, fator_conversao: float = 1):
    """
    Liga um produto de um fornecedor (identificado pelo código dele na nota)
    a um insumo do sistema. Depois de mapeado uma vez, próximas notas do
    mesmo fornecedor com o mesmo código são reconhecidas automaticamente.

    fator_conversao: use se a unidade da nota for diferente da unidade do
    insumo (ex: nota vem em "cx" com 12 unidades, insumo é controlado em "un"
    -> fator_conversao = 12).
    """
    conn = get_connection()
    insumo = conn.execute("SELECT id FROM insumos WHERE nome = ?", (insumo_nome,)).fetchone()
    if not insumo:
        conn.close()
        raise ValueError(f"Insumo '{insumo_nome}' não encontrado.")

    conn.execute(
        """
        INSERT INTO mapeamento_produtos_nfe
            (fornecedor_cnpj, codigo_produto, descricao_produto, insumo_id, fator_conversao)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(fornecedor_cnpj, codigo_produto)
        DO UPDATE SET insumo_id = excluded.insumo_id,
                      fator_conversao = excluded.fator_conversao,
                      descricao_produto = excluded.descricao_produto
        """,
        (fornecedor_cnpj, codigo_produto, descricao_produto, insumo["id"], fator_conversao),
    )
    conn.commit()
    conn.close()


def buscar_mapeamento_nfe(fornecedor_cnpj: str, codigo_produto: str):
    """Retorna o mapeamento (insumo + fator de conversão) para um produto, ou None."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT m.fator_conversao, i.nome AS insumo_nome
        FROM mapeamento_produtos_nfe m
        JOIN insumos i ON i.id = m.insumo_id
        WHERE m.fornecedor_cnpj = ? AND m.codigo_produto = ?
        """,
        (fornecedor_cnpj, codigo_produto),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------- Mapeamento de produtos do PDV (Zig) ----------

def mapear_produto_zig(sku: str, nome_produto: str, prato_nome: str = None,
                       ignorar: bool = False):
    """
    Liga um produto do PDV (identificado pelo SKU da Zig) a um prato do sistema.
    `ignorar=True` marca produtos que não consomem estoque controlado (couvert,
    itens de loja), para que não voltem a aparecer como pendência a cada importação.

    O SKU é sensível a maiúsculas: na Zig, 'Fe' e 'FE' são produtos diferentes.
    """
    conn = get_connection()
    prato_id = None
    if prato_nome:
        prato = conn.execute("SELECT id FROM pratos WHERE nome = ?", (prato_nome,)).fetchone()
        if not prato:
            conn.close()
            raise ValueError(f"Prato '{prato_nome}' não encontrado.")
        prato_id = prato["id"]

    conn.execute(
        """
        INSERT INTO mapeamento_produtos_zig (sku, nome_produto, prato_id, ignorar)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(sku)
        DO UPDATE SET nome_produto = excluded.nome_produto,
                      prato_id = excluded.prato_id,
                      ignorar = excluded.ignorar
        """,
        (sku, nome_produto, prato_id, 1 if ignorar else 0),
    )
    conn.commit()
    conn.close()


def buscar_mapeamento_zig(sku: str):
    """Retorna {'prato_nome': str|None, 'ignorar': bool} para um SKU, ou None."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT m.ignorar, p.nome AS prato_nome
        FROM mapeamento_produtos_zig m
        LEFT JOIN pratos p ON p.id = m.prato_id
        WHERE m.sku = ?
        """,
        (sku,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"prato_nome": row["prato_nome"], "ignorar": bool(row["ignorar"])}


def listar_mapeamentos_zig() -> list[dict]:
    """Todos os mapeamentos já salvos, para revisão na tela de importação."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT m.sku, m.nome_produto, m.ignorar, p.nome AS prato_nome
        FROM mapeamento_produtos_zig m
        LEFT JOIN pratos p ON p.id = m.prato_id
        ORDER BY m.nome_produto
        """
    ).fetchall()
    conn.close()
    return [
        {
            "sku": linha["sku"],
            "nome_produto": linha["nome_produto"],
            "prato_nome": linha["prato_nome"],
            "ignorar": bool(linha["ignorar"]),
        }
        for linha in linhas
    ]


def remover_mapeamento_zig(sku: str):
    """Apaga o mapeamento de um SKU. O produto volta a aparecer como pendente."""
    conn = get_connection()
    conn.execute("DELETE FROM mapeamento_produtos_zig WHERE sku = ?", (sku,))
    conn.commit()
    conn.close()


# ---------- Consultas do dashboard ----------

def _data_inicio(dias: int) -> str:
    return (hoje() - datetime.timedelta(days=dias - 1)).isoformat()


def consumo_por_insumo(dias: int = 30) -> list[dict]:
    """Quanto de cada insumo saiu no período: venda × ficha e gasto de produção."""
    conn = get_connection()
    linhas = conn.execute(
        f"""
        SELECT i.nome AS insumo,
               i.unidade_medida,
               SUM(m.saida) AS consumo
        FROM ({SQL_MOVIMENTOS}) m
        JOIN insumos i ON i.id = m.insumo_id
        WHERE m.data >= ? AND m.saida > 0
        GROUP BY i.id, i.nome, i.unidade_medida
        ORDER BY consumo DESC
        """,
        (_data_inicio(dias),),
    ).fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


def vendas_por_dia(dias: int = 30) -> list[dict]:
    """Total de pratos vendidos por dia no período."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT data, SUM(quantidade) AS pratos_vendidos
        FROM vendas_diarias
        WHERE data >= ?
        GROUP BY data
        ORDER BY data
        """,
        (_data_inicio(dias),),
    ).fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


def top_pratos(dias: int = 30, limite: int = 5) -> list[dict]:
    """Pratos mais vendidos no período."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT p.nome AS prato, SUM(v.quantidade) AS vendidos
        FROM vendas_diarias v
        JOIN pratos p ON p.id = v.prato_id
        WHERE v.data >= ?
        GROUP BY p.id
        ORDER BY vendidos DESC
        LIMIT ?
        """,
        (_data_inicio(dias), limite),
    ).fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


def dias_desde_ultima_contagem() -> int | None:
    """Quantos dias se passaram desde a contagem física mais recente (None se nunca houve)."""
    conn = get_connection()
    linha = conn.execute("SELECT MAX(data) AS ultima FROM contagens_fisicas").fetchone()
    conn.close()
    if not linha or not linha["ultima"]:
        return None
    ultima = datetime.date.fromisoformat(linha["ultima"])
    return (hoje() - ultima).days


def resumo_dashboard(dias: int = 30) -> dict:
    """Números-chave do topo do dashboard."""
    conn = get_connection()
    total_insumos = conn.execute("SELECT COUNT(*) AS n FROM insumos").fetchone()["n"]
    total_pratos = conn.execute("SELECT COUNT(*) AS n FROM pratos").fetchone()["n"]
    inicio = _data_inicio(dias)
    pratos_vendidos = conn.execute(
        "SELECT COALESCE(SUM(quantidade), 0) AS n FROM vendas_diarias WHERE data >= ?",
        (inicio,),
    ).fetchone()["n"]
    compras_lancadas = conn.execute(
        "SELECT COUNT(*) AS n FROM compras WHERE data >= ?", (inicio,)
    ).fetchone()["n"]
    conn.close()

    estoques = calcular_estoque_todos_insumos()
    sem_baseline = [e for e in estoques if e["baseline_usada"] == SEM_CONTAGEM]
    return {
        "total_insumos": total_insumos,
        "total_pratos": total_pratos,
        "pratos_vendidos": pratos_vendidos,
        "compras_lancadas": compras_lancadas,
        "abaixo_do_minimo": sum(1 for e in estoques if e["abaixo_do_minimo"]),
        # Negativo só é sintoma de erro quando existe uma contagem de partida;
        # sem contagem, o cálculo começa do zero e fica negativo por definição.
        "estoque_negativo": sum(
            1 for e in estoques
            if e["estoque_atual"] < 0 and e["baseline_usada"] != SEM_CONTAGEM
        ),
        "sem_contagem_inicial": len(sem_baseline),
        "dias_sem_contagem": dias_desde_ultima_contagem(),
    }


def cobertura_estoque(dias: int = 30) -> list[dict]:
    """
    Para cada insumo, estima em quantos dias o estoque acaba, usando o consumo
    médio diário do período. É o número que diz o que precisa ser comprado antes
    de faltar — insumo sem consumo no período fica com dias_restantes None.
    """
    consumo = {c["insumo"]: c["consumo"] for c in consumo_por_insumo(dias)}
    resultado = []
    for estoque in calcular_estoque_todos_insumos():
        consumo_total = consumo.get(estoque["insumo"], 0)
        media_diaria = consumo_total / dias if consumo_total else 0
        resultado.append({
            **estoque,
            "consumo_periodo": round(consumo_total, 2),
            "consumo_medio_diario": round(media_diaria, 2),
            "dias_restantes": (
                round(estoque["estoque_atual"] / media_diaria, 1) if media_diaria > 0 else None
            ),
        })
    return resultado


def movimentacoes_recentes(limite: int = 15) -> list[dict]:
    """Últimos lançamentos de qualquer tipo, para o feed de atividade do dashboard."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT c.data, 'Compra' AS tipo, i.nome AS item,
               c.quantidade AS quantidade, i.unidade_medida AS unidade,
               COALESCE(c.fornecedor, '') AS detalhe
        FROM compras c JOIN insumos i ON i.id = c.insumo_id
        UNION ALL
        SELECT v.data, 'Venda', p.nome, v.quantidade, 'pratos', ''
        FROM vendas_diarias v JOIN pratos p ON p.id = v.prato_id
        UNION ALL
        SELECT pr.data, 'Produção', i.nome, pr.quantidade_produzida, i.unidade_medida,
               COALESCE(pr.observacao, '')
        FROM producoes pr JOIN insumos i ON i.id = pr.insumo_id
        UNION ALL
        SELECT cf.data, 'Contagem', i.nome, cf.quantidade_contada, i.unidade_medida,
               COALESCE(cf.observacao, '')
        FROM contagens_fisicas cf JOIN insumos i ON i.id = cf.insumo_id
        -- 'item' desempata: sem ele, lançamentos com a mesma data e o mesmo
        -- tipo saem em ordem arbitrária, e o LIMIT corta linhas diferentes
        -- em cada banco. O feed ficava instável sem nenhum motivo visível.
        ORDER BY data DESC, tipo, item
        LIMIT ?
        """,
        (limite,),
    ).fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


# ---------- Reconciliação de perdas ----------

# Entre duas contagens físicas dá para fechar a conta do que aconteceu com
# um insumo. Tudo que estava disponível no período teve um de três
# destinos, e os três somam exatamente o que havia:
#
#     disponível  =  estoque inicial + entradas (compras e produção)
#     disponível  =  consumo + sobra + perda
#
# O consumo é o teórico (vendas × ficha do prato, mais o que as produções
# gastaram) e a sobra é a contagem seguinte. As chaves continuam se
# chamando "compras" e "consumo" por compatibilidade; "compras" inclui o
# que a cozinha produziu. A perda é o que falta para fechar: quebra, desperdício, porção
# maior que a ficha, furo. É o número que a contagem mensal existe para
# revelar, e ele só aparece quando há duas contagens do mesmo insumo.
#
# Sobre as datas: o período vai de uma contagem (inclusive) até a seguinte
# (exclusive). Isso segue a convenção do resto do sistema — uma contagem
# mede o estoque antes dos movimentos do próprio dia, e por isso os
# movimentos do dia da contagem final já pertencem ao período seguinte.
SQL_RECONCILIACAO = f"""
    WITH movimentos AS ({SQL_MOVIMENTOS}),
    periodos AS (
        SELECT
            c.insumo_id,
            c.data AS inicio,
            c.quantidade_contada AS estoque_inicial,
            LEAD(c.data) OVER (
                PARTITION BY c.insumo_id ORDER BY c.data, c.id
            ) AS fim,
            LEAD(c.quantidade_contada) OVER (
                PARTITION BY c.insumo_id ORDER BY c.data, c.id
            ) AS estoque_final
        FROM contagens_fisicas c
    )
    SELECT
        i.nome AS insumo,
        i.unidade_medida,
        p.inicio,
        p.fim,
        p.estoque_inicial,
        p.estoque_final,
        COALESCE((
            SELECT SUM(m.entrada) FROM movimentos m
            WHERE m.insumo_id = p.insumo_id
              AND m.data >= p.inicio AND m.data < p.fim
        ), 0) AS compras,
        COALESCE((
            SELECT SUM(m.saida) FROM movimentos m
            WHERE m.insumo_id = p.insumo_id
              AND m.data >= p.inicio AND m.data < p.fim
        ), 0) AS consumo
    FROM periodos p
    JOIN insumos i ON i.id = p.insumo_id
    WHERE p.fim IS NOT NULL
    ORDER BY p.fim DESC, i.nome
"""


def _percentual(parte, total):
    """Percentual de 'parte' sobre 'total', ou None quando não faz sentido."""
    if not total:
        return None
    return round(parte / total * 100, 1)


def reconciliacao_de_perdas(apenas_ultimo_periodo: bool = True) -> list[dict]:
    """Fecha a conta de cada insumo entre duas contagens físicas.

    Devolve, por período, quanto do disponível foi usado, quanto sobrou e
    quanto se perdeu, em quantidade e em percentual. Um insumo só aparece
    depois de ter duas contagens — antes disso não existe período fechado
    para reconciliar.

    Perda negativa significa que foi encontrado *mais* do que o esperado.
    Isso não é lucro: costuma ser venda não lançada, compra não registrada
    ou erro na contagem. Por isso o sinal é preservado em vez de zerado.
    """
    conn = get_connection()
    linhas = conn.execute(SQL_RECONCILIACAO).fetchall()
    conn.close()

    resultado = []
    for linha in linhas:
        inicial = linha["estoque_inicial"]
        compras = linha["compras"]
        consumo = linha["consumo"]
        final = linha["estoque_final"]

        disponivel = inicial + compras
        esperado = disponivel - consumo
        perda = esperado - final

        resultado.append({
            "insumo": linha["insumo"],
            "unidade_medida": linha["unidade_medida"],
            "inicio": linha["inicio"],
            "fim": linha["fim"],
            "dias": _dias_entre(linha["inicio"], linha["fim"]),
            "estoque_inicial": round(inicial, 2),
            "compras": round(compras, 2),
            "disponivel": round(disponivel, 2),
            "consumo": round(consumo, 2),
            "estoque_final_esperado": round(esperado, 2),
            "estoque_final_contado": round(final, 2),
            "perda": round(perda, 2),
            "pct_usado": _percentual(consumo, disponivel),
            "pct_sobra": _percentual(final, disponivel),
            "pct_perda": _percentual(perda, disponivel),
        })

    if apenas_ultimo_periodo:
        # Um insumo pode ter vários períodos fechados; aqui fica só o mais
        # recente de cada um, que é o que interessa na tela principal.
        vistos, ultimos = set(), []
        for item in resultado:  # já vem ordenado do período mais recente
            if item["insumo"] not in vistos:
                vistos.add(item["insumo"])
                ultimos.append(item)
        return ultimos

    return resultado


def _dias_entre(inicio: str, fim: str) -> int:
    d1 = datetime.date.fromisoformat(inicio)
    d2 = datetime.date.fromisoformat(fim)
    return (d2 - d1).days


def resumo_de_perdas(apenas_ultimo_periodo: bool = True) -> dict:
    """Números-chave da reconciliação, para o topo da tela de perdas."""
    itens = reconciliacao_de_perdas(apenas_ultimo_periodo)
    if not itens:
        return {
            "insumos_reconciliados": 0,
            "com_perda": 0,
            "com_sobra": 0,
            "pior_insumo": None,
            "pior_pct": None,
            "pct_perda_medio": None,
        }

    com_perda = [i for i in itens if i["perda"] > 0]
    piores = [i for i in com_perda if i["pct_perda"] is not None]
    pior = max(piores, key=lambda i: i["pct_perda"]) if piores else None
    percentuais = [i["pct_perda"] for i in itens if i["pct_perda"] is not None]

    return {
        "insumos_reconciliados": len(itens),
        "com_perda": len(com_perda),
        "com_sobra": sum(1 for i in itens if i["perda"] < 0),
        "pior_insumo": pior["insumo"] if pior else None,
        "pior_pct": pior["pct_perda"] if pior else None,
        "pct_perda_medio": round(sum(percentuais) / len(percentuais), 1) if percentuais else None,
    }


def insumos_sem_reconciliacao() -> list[str]:
    """Insumos que ainda não têm duas contagens, e por isso não reconciliam."""
    conn = get_connection()
    linhas = conn.execute(
        """SELECT i.nome, COUNT(c.id) AS contagens
           FROM insumos i
           LEFT JOIN contagens_fisicas c ON c.insumo_id = i.id
           GROUP BY i.id, i.nome
           HAVING COUNT(c.id) < 2
           ORDER BY i.nome"""
    ).fetchall()
    conn.close()
    return [linha["nome"] for linha in linhas]


# ---------- Saída de estoque por período ----------

# Sem integração com o PDV, a venda é lançada à mão, dia a dia. Um dia
# isolado não diz nada — o que responde "quanto saiu do estoque" é a soma
# de vários dias, que é o número olhado na segunda-feira de manhã.
#
# O período é fechado nas duas pontas (>= início e <= fim), diferente do
# resto do sistema, onde o fim é aberto. Aqui as duas datas são escolhidas
# por quem olha, e um período que exclui o último dia escolhido seria uma
# armadilha.

def segunda_da_semana(data: datetime.date = None) -> datetime.date:
    """A segunda-feira da semana de `data` (ou de hoje)."""
    data = data or hoje()
    return data - datetime.timedelta(days=data.weekday())


def saida_por_periodo(inicio: str, fim: str) -> list[dict]:
    """Quanto de cada insumo saiu do estoque entre duas datas, com o saldo atual.

    A saída é o consumo teórico: vendas lançadas × ficha do prato, mais o
    que as produções do período gastaram. Vem junto o estoque atual de
    cada insumo, porque as duas perguntas são feitas ao mesmo tempo —
    quanto saiu e quanto ainda tem.
    """
    conn = get_connection()
    linhas = conn.execute(
        f"""
        SELECT i.nome AS insumo,
               i.unidade_medida,
               SUM(m.saida) AS saida
        FROM ({SQL_MOVIMENTOS}) m
        JOIN insumos i ON i.id = m.insumo_id
        WHERE m.data >= ? AND m.data <= ? AND m.saida > 0
        GROUP BY i.id, i.nome, i.unidade_medida
        ORDER BY saida DESC
        """,
        (inicio, fim),
    ).fetchall()
    conn.close()

    estoques = {e["insumo"]: e for e in calcular_estoque_todos_insumos()}
    dias = _dias_entre(inicio, fim) + 1

    resultado = []
    for linha in linhas:
        estoque = estoques.get(linha["insumo"], {})
        resultado.append({
            "insumo": linha["insumo"],
            "unidade_medida": linha["unidade_medida"],
            "saida": round(linha["saida"], 3),
            "media_diaria": round(linha["saida"] / dias, 3),
            "estoque_atual": estoque.get("estoque_atual"),
            "estoque_minimo": estoque.get("estoque_minimo"),
            "abaixo_do_minimo": estoque.get("abaixo_do_minimo", False),
        })
    return resultado


def pratos_vendidos_no_periodo(inicio: str, fim: str) -> list[dict]:
    """Quantos de cada prato foram vendidos no período."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT p.nome AS prato, SUM(v.quantidade) AS vendidos
        FROM vendas_diarias v
        JOIN pratos p ON p.id = v.prato_id
        WHERE v.data >= ? AND v.data <= ?
        GROUP BY p.id, p.nome
        ORDER BY vendidos DESC
        """,
        (inicio, fim),
    ).fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


def vendas_por_dia_no_periodo(inicio: str, fim: str) -> list[dict]:
    """Total de pratos vendidos em cada dia do período, só dos dias lançados."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT data, SUM(quantidade) AS pratos_vendidos
        FROM vendas_diarias
        WHERE data >= ? AND data <= ?
        GROUP BY data
        ORDER BY data
        """,
        (inicio, fim),
    ).fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


def dias_sem_lancamento(inicio: str, fim: str) -> list[str]:
    """Dias do período que não têm nenhuma venda lançada.

    Com lançamento manual, dia esquecido é a falha mais provável — e ela
    não dá erro em lugar nenhum: o consumo simplesmente sai menor que o
    real e o estoque teórico fica alto. Por isso os buracos são listados
    junto com o resultado, em vez de ficarem invisíveis.

    Dia marcado como "o restaurante não abriu" não entra: sem essa marca,
    uma folga ficaria acusando falta para sempre, e aviso que nunca some
    é aviso que ninguém mais lê.
    """
    lancados = {linha["data"] for linha in vendas_por_dia_no_periodo(inicio, fim)}
    fechados = dias_sem_movimento(inicio, fim)
    d1 = datetime.date.fromisoformat(inicio)
    d2 = datetime.date.fromisoformat(fim)
    faltando = []
    while d1 <= d2:
        dia = d1.isoformat()
        if dia not in lancados and dia not in fechados:
            faltando.append(dia)
        d1 += datetime.timedelta(days=1)
    return faltando


def dias_sem_movimento(inicio: str, fim: str) -> set[str]:
    """Dias do período marcados como 'o restaurante não abriu'."""
    conn = get_connection()
    linhas = conn.execute(
        "SELECT data FROM dias_sem_movimento WHERE data >= ? AND data <= ?",
        (inicio, fim),
    ).fetchall()
    conn.close()
    return {linha["data"] for linha in linhas}


def marcar_dia_sem_movimento(data: str):
    """Registra que o restaurante não abriu nesse dia. Marcar duas vezes não duplica."""
    conn = get_connection()
    conn.execute("DELETE FROM dias_sem_movimento WHERE data = ?", (data,))
    conn.execute(
        "INSERT INTO dias_sem_movimento (data, marcado_em) VALUES (?, ?)",
        (data, datetime.datetime.now(FUSO).isoformat(timespec="minutes")),
    )
    conn.commit()
    conn.close()


def desmarcar_dia_sem_movimento(data: str):
    conn = get_connection()
    conn.execute("DELETE FROM dias_sem_movimento WHERE data = ?", (data,))
    conn.commit()
    conn.close()


# Até quantos dias para trás o lembrete olha. Mais que duas semanas o
# lembrete deixa de ser lembrete: quem esqueceu um dia há um mês já não
# tem o resumo do PDV à mão, e a lista só cresceria.
JANELA_DO_LEMBRETE = 14


def vendas_pendentes(janela: int = JANELA_DO_LEMBRETE) -> list[str]:
    """Dias recentes que deviam ter venda lançada e não têm.

    É o lembrete do dia a dia. O relatório da semana (`dias_sem_lancamento`
    na tela de Saída) já mostrava os buracos, mas só na segunda-feira —
    quando o resumo do PDV daquela quarta já foi para o lixo. Aqui o dia
    esquecido aparece no dia seguinte.

    Três limites evitam alarme falso:

    - **hoje não entra**: o movimento de hoje ainda está acontecendo, e o
      normal é lançar no fechamento ou na manhã seguinte;
    - **nada antes do início do uso**: o lembrete só começa na primeira
      contagem física ou na primeira venda lançada, o que vier antes. Sem
      isso, um sistema recém-implantado acusaria semanas de "esquecimento";
    - **dia marcado como fechado** não conta.
    """
    conn = get_connection()
    inicio_do_uso = conn.execute(
        """SELECT MIN(data) AS d FROM (
               SELECT MIN(data) AS data FROM vendas_diarias
               UNION ALL
               SELECT MIN(data) AS data FROM contagens_fisicas
           ) AS primeiros"""
    ).fetchone()["d"]
    conn.close()
    if not inicio_do_uso:
        return []

    ontem = hoje() - datetime.timedelta(days=1)
    inicio = max(
        datetime.date.fromisoformat(inicio_do_uso),
        hoje() - datetime.timedelta(days=janela),
    )
    if inicio > ontem:
        return []
    return dias_sem_lancamento(inicio.isoformat(), ontem.isoformat())


def resumo_do_periodo(inicio: str, fim: str) -> dict:
    """Números do topo da tela de saída acumulada."""
    conn = get_connection()
    pratos_vendidos = conn.execute(
        """SELECT COALESCE(SUM(quantidade), 0) AS n FROM vendas_diarias
           WHERE data >= ? AND data <= ?""",
        (inicio, fim),
    ).fetchone()["n"]
    compras_lancadas = conn.execute(
        "SELECT COUNT(*) AS n FROM compras WHERE data >= ? AND data <= ?",
        (inicio, fim),
    ).fetchone()["n"]
    conn.close()

    saidas = saida_por_periodo(inicio, fim)
    buracos = dias_sem_lancamento(inicio, fim)
    total_dias = _dias_entre(inicio, fim) + 1

    return {
        "dias": total_dias,
        "dias_lancados": total_dias - len(buracos),
        "dias_sem_lancamento": buracos,
        "pratos_vendidos": pratos_vendidos,
        "compras_lancadas": compras_lancadas,
        "insumos_movimentados": len(saidas),
        "insumos_abaixo_do_minimo": sum(1 for s in saidas if s["abaixo_do_minimo"]),
    }
