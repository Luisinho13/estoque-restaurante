"""
crud.py
Funções de negócio do sistema: cadastros, lançamentos e cálculo do
estoque teórico (o coração do projeto — é o que elimina a contagem semanal).

Lógica do cálculo de estoque teórico para um insumo:
    1. Pega a última contagem física registrada (se houver) como ponto de partida.
    2. Soma todas as compras feitas depois dessa contagem.
    3. Subtrai o consumo calculado a partir das vendas diárias x ficha técnica,
       também depois dessa contagem.
    4. Resultado = estoque teórico atual, sem precisar contar nada fisicamente.
"""

import datetime

from database import get_connection


# ---------- Cadastros ----------

def cadastrar_insumo(nome: str, unidade_medida: str, estoque_minimo: float = 0):
    conn = get_connection()
    conn.execute(
        "INSERT INTO insumos (nome, unidade_medida, estoque_minimo) VALUES (?, ?, ?)",
        (nome, unidade_medida, estoque_minimo),
    )
    conn.commit()
    conn.close()


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
    Exclui um insumo e todo o histórico ligado a ele (ficha técnica,
    compras e contagens físicas). Use com cuidado: não tem como desfazer.
    """
    conn = get_connection()
    insumo = conn.execute("SELECT id FROM insumos WHERE nome = ?", (nome,)).fetchone()
    if not insumo:
        conn.close()
        raise ValueError(f"Insumo '{nome}' não encontrado.")

    insumo_id = insumo["id"]
    conn.execute("DELETE FROM ficha_tecnica WHERE insumo_id = ?", (insumo_id,))
    conn.execute("DELETE FROM compras WHERE insumo_id = ?", (insumo_id,))
    conn.execute("DELETE FROM contagens_fisicas WHERE insumo_id = ?", (insumo_id,))
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


# ---------- Lançamentos ----------

def registrar_compra(insumo_nome: str, quantidade: float, data: str,
                      fornecedor: str = None, observacao: str = None):
    conn = get_connection()
    insumo = conn.execute("SELECT id FROM insumos WHERE nome = ?", (insumo_nome,)).fetchone()
    if not insumo:
        conn.close()
        raise ValueError(f"Insumo '{insumo_nome}' não encontrado.")

    conn.execute(
        """INSERT INTO compras (insumo_id, quantidade, data, fornecedor, observacao)
           VALUES (?, ?, ?, ?, ?)""",
        (insumo["id"], quantidade, data, fornecedor, observacao),
    )
    conn.commit()
    conn.close()


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


# ---------- O cálculo principal ----------

def calcular_estoque_teorico(insumo_nome: str) -> dict:
    """
    Calcula o estoque teórico atual de um insumo:
    última contagem física + compras - consumo, desde a data dessa contagem.
    """
    conn = get_connection()
    insumo = conn.execute("SELECT * FROM insumos WHERE nome = ?", (insumo_nome,)).fetchone()
    if not insumo:
        conn.close()
        raise ValueError(f"Insumo '{insumo_nome}' não encontrado.")

    insumo_id = insumo["id"]

    # 1. Última contagem física (ponto de partida)
    ultima_contagem = conn.execute(
        """SELECT quantidade_contada, data FROM contagens_fisicas
           WHERE insumo_id = ? ORDER BY data DESC LIMIT 1""",
        (insumo_id,),
    ).fetchone()

    if ultima_contagem:
        baseline = ultima_contagem["quantidade_contada"]
        data_baseline = ultima_contagem["data"]
    else:
        baseline = 0
        data_baseline = "0000-00-00"  # sem contagem ainda: considera tudo desde o início

    # 2. Compras a partir da baseline (inclui o próprio dia da contagem)
    total_compras = conn.execute(
        """SELECT COALESCE(SUM(quantidade), 0) AS total FROM compras
           WHERE insumo_id = ? AND data >= ?""",
        (insumo_id, data_baseline),
    ).fetchone()["total"]

    # 3. Consumo a partir da baseline (vendas x ficha técnica, inclui o mesmo dia)
    total_consumo = conn.execute(
        """
        SELECT COALESCE(SUM(v.quantidade * ft.quantidade_por_prato), 0) AS total
        FROM vendas_diarias v
        JOIN ficha_tecnica ft ON ft.prato_id = v.prato_id
        WHERE ft.insumo_id = ? AND v.data >= ?
        """,
        (insumo_id, data_baseline),
    ).fetchone()["total"]

    conn.close()

    estoque_atual = baseline + total_compras - total_consumo

    return {
        "insumo": insumo_nome,
        "unidade_medida": insumo["unidade_medida"],
        "estoque_minimo": insumo["estoque_minimo"],
        "estoque_atual": round(estoque_atual, 1),
        "abaixo_do_minimo": estoque_atual < insumo["estoque_minimo"],
        "baseline_usada": data_baseline if ultima_contagem else "sem contagem física ainda",
    }


def calcular_estoque_todos_insumos() -> list[dict]:
    conn = get_connection()
    nomes = [row["nome"] for row in conn.execute("SELECT nome FROM insumos").fetchall()]
    conn.close()
    return [calcular_estoque_teorico(nome) for nome in nomes]


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


# ---------- Consultas do dashboard ----------

def _data_inicio(dias: int) -> str:
    return (datetime.date.today() - datetime.timedelta(days=dias - 1)).isoformat()


def consumo_por_insumo(dias: int = 30) -> list[dict]:
    """Quanto de cada insumo foi consumido (vendas × ficha técnica) no período."""
    conn = get_connection()
    linhas = conn.execute(
        """
        SELECT i.nome AS insumo,
               i.unidade_medida,
               SUM(v.quantidade * ft.quantidade_por_prato) AS consumo
        FROM vendas_diarias v
        JOIN ficha_tecnica ft ON ft.prato_id = v.prato_id
        JOIN insumos i ON i.id = ft.insumo_id
        WHERE v.data >= ?
        GROUP BY i.id
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
    return (datetime.date.today() - ultima).days


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
    return {
        "total_insumos": total_insumos,
        "total_pratos": total_pratos,
        "pratos_vendidos": pratos_vendidos,
        "compras_lancadas": compras_lancadas,
        "abaixo_do_minimo": sum(1 for e in estoques if e["abaixo_do_minimo"]),
        "estoque_negativo": sum(1 for e in estoques if e["estoque_atual"] < 0),
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
        SELECT cf.data, 'Contagem', i.nome, cf.quantidade_contada, i.unidade_medida,
               COALESCE(cf.observacao, '')
        FROM contagens_fisicas cf JOIN insumos i ON i.id = cf.insumo_id
        ORDER BY data DESC, tipo
        LIMIT ?
        """,
        (limite,),
    ).fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]
