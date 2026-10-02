"""
cozinha_fria.py
A carne que a cozinha fria limpa e porciona vira produção.

Até 30/09/2026 a peça e o porcionado eram o mesmo insumo: o bombom de
alcatra em peça e o bombom porcionado caíam os dois em "Alcatra". A
limpeza — o cordão do mignon, a gordura da alcatra, a pele do salmão —
sumia sem nome, e aparecia como perda na contagem seguinte. Pedido do
usuário em 30/09: "a produção de carnes e cortes feitos na cozinha fria",
montada a partir das linhas da contagem ("monta pela contagem, e eu
confiro depois").

O modelo é o das outras produções (v0.11): o cru é a **peça** comprada; o
porcionado é um item de estoque à parte, do tipo produção; os pratos
descontam o porcionado; e a peça só sai quando um porcionamento é lançado
em Lançar Produção.

- **1 receita = 1 kg de peça.** Quem lança diz quantos kg de peça limpou,
  e em "Quanto rendeu" o peso do que ficou pronto. A diferença é a perda
  da limpeza, agora com nome e data.
- **O rendimento começa em 1** (1 kg de peça, 1 kg porcionado), a
  definir: nenhum peso foi informado, e chutar um rendimento seria pior —
  o erro entraria calado em todo lançamento. A tela sugere o número e a
  cozinha corrige com o peso da balança.
- **A apara não entra.** Ela sai da mesma limpeza, mas uma produção tem uma
  saída só. Fica contada como hoje, no insumo dela.

Ficaram de fora, de propósito: o que chega pronto do fornecedor (truta em
filé, porterhouse, tomahawk, mini hambúrguer), o camarão 11/15 (a linha
"câmara 3/cozinha" não diz se é porcionado) e o frango de uso da equipe.

**Cortes com produção própria** (pedido do usuário em 02/10/2026): o
bombom de alcatra, a carne do fondue, o filé aperitivo e o frango do
fondue saem da mesma peça que o porcionado comum, mas a cozinha porciona
tudo junto e "pode dar confusão". Cada um virou uma produção à parte. O
prato que é desse corte (`CORTES_POR_PRATO`) desconta a produção dele; os
outros continuam no porcionado comum da peça. O rendimento segue 1 kg por
kg de peça: cada pacote feito é 1 kg (confirmado pelo usuário em 02/10).
O corte nasce com a receita do porcionado comum da peça dele, como está no
sistema: em 01/10 o usuário trocou a da alcatra porcionada para Baby Beef,
e o bombom e a carne do fondue saem dele também.

Nada aqui grava sozinho: `montar_plano()` diz o que muda e
`aplicar_plano()` grava, tudo ou nada. Rodar de novo não duplica nada.
"""

from database import get_connection
from ficha_import import chave

# Produção (o porcionado) → insumo cru (a peça) que ela consome.
PORCIONADOS = {
    "Alcatra porcionada": "Alcatra",
    "Bombom de alcatra porcionado": "Alcatra",
    "Carne fondue porcionada": "Alcatra",
    "Mignon porcionado": "Mignon",
    "Filé aperitivo porcionado": "Mignon",
    "Chorizo porcionado": "Chorizo",
    "Costela porcionada": "Costela",
    "Barriga de porco porcionada": "Barriga de porco",
    "Frango porcionado": "Frango",
    "Frango fondue porcionado": "Frango",
    "Camarão sete barbas porcionado": "Camarão sete barbas",
    "Salmão porcionado": "Salmão",
}

# O porcionado comum de cada peça: é ele que o prato desconta quando não
# tem corte próprio.
GERAL = {
    "Alcatra": "Alcatra porcionada",
    "Mignon": "Mignon porcionado",
    "Chorizo": "Chorizo porcionado",
    "Costela": "Costela porcionada",
    "Barriga de porco": "Barriga de porco porcionada",
    "Frango": "Frango porcionado",
    "Camarão sete barbas": "Camarão sete barbas porcionado",
    "Salmão": "Salmão porcionado",
}

# Corte próprio: (começo do nome do prato, por `chave`, e a peça que ele
# cita) → produção. A peça entra na chave porque a sequência de fondue leva
# dois cortes, a carne e o frango.
CORTES_POR_PRATO = {
    ("bombom de alcatra", "Alcatra"): "Bombom de alcatra porcionado",
    ("fondue de carne", "Alcatra"): "Carne fondue porcionada",
    ("sequencia de fondue", "Alcatra"): "Carne fondue porcionada",
    ("sequencia de fondue", "Frango"): "Frango fondue porcionado",
    ("file aperitivo", "Mignon"): "Filé aperitivo porcionado",
}

# Corte que a ficha da planilha da cozinha não cita e que o prato leva:
# (começo do nome do prato, por `chave`) → [(produção, kg por prato)].
# A sequência de fondue leva 180 g de frango (usuário, 02/10/2026); a
# planilha só tinha a carne.
ACRESCIMOS = {
    "sequencia de fondue": [("Frango fondue porcionado", 0.18)],
}


def acrescimos_do_prato(prato: str) -> list[tuple]:
    """Os cortes que `prato` leva além do que a planilha da cozinha diz."""
    nome = chave(prato)
    return [item for comeco, itens in ACRESCIMOS.items()
            if nome.startswith(comeco) for item in itens]


# Linhas da planilha de contagem que são o porcionado. As outras linhas
# desses insumos são a peça e continuam no cru.
LINHAS_PORCIONADAS = {
    "BOMBOM DE ALCATRA (PORCIONADO)": "Bombom de alcatra porcionado",
    "MIOLO/ CORAÇÃO DE ALCATRA PORCIONADO (CAMERA - 3) PORÇÃO 180gr": "Alcatra porcionada",
    "MIOLO/ CORAÇÃO DE ALCATRA PORCIONADO (COZINHA) PARMEGIANA": "Alcatra porcionada",
    "FILET MIGNON PORCIONADO ( GARDE) ESCALOPE / TORNEDOR": "Mignon porcionado",
    "FILET MIGNON PORCIONADO (CAMERA - 3 - FILE APERITIVO) PORÇÃO 280GR": "Filé aperitivo porcionado",
    "FILET MIGNON PORCIONADO BIFE P/ PARMEGIANA 160gr (GARDE)": "Mignon porcionado",
    "FILET MIGNON PORCIONADO STEAK TARTARE": "Mignon porcionado",
    "FILET MIGNON PORCIONADO ISCA DE MIGNON": "Mignon porcionado",
    "CHORIZO PORCIONADO (CAMERA - 3)": "Chorizo porcionado",
    "COSTELA BOVINA PORCIONADO (CAMERA -3)": "Costela porcionada",
    "BARRIGA DE PORCO PORCIONADO": "Barriga de porco porcionada",
    "PEITO DE FRANGO PORCIONADO (GOURMET)": "Frango porcionado",
    "PEITO DE FRANGO PORCIONADO - ISCAS (FRANGO GOURMET) / (CAMARA 3)": "Frango porcionado",
    "PEITO DE FRANGO PORCIONADO - KIDS": "Frango porcionado",
    "PEITO DE FRANGO PORCIONADO FONDUE (CAMERA - 3)": "Frango fondue porcionado",
    "PEITO DE FRANGO PORCIONADO PARMEGIANA(GARDE)": "Frango porcionado",
    "CAMARÃO 7 BARBA PORCIONADO (CÂMARA 3 / COZINHA)": "Camarão sete barbas porcionado",
    "SALMÃO PORCIONADO (CÂMARA 3 / COZINHA)": "Salmão porcionado",
    # A isca sai da mesma limpeza da peça: é porcionado também.
    "SALMÃO APARAS (CAMERA - 3) ISCAS": "Salmão porcionado",
}
_LINHAS = {chave(k): v for k, v in LINHAS_PORCIONADAS.items()}

RENDIMENTO_INICIAL = 1.0   # kg porcionado por kg de peça, a definir (ver o topo)


def porcionado_de(descricao: str) -> str | None:
    """A produção de uma linha da contagem, se ela for de carne porcionada."""
    return _LINHAS.get(chave(descricao))


def porcionado_para(prato: str, insumo: str) -> str | None:
    """O porcionado que `prato` deve descontar no lugar de `insumo`.

    `insumo` pode ser a peça ou um porcionado dela. O prato com corte
    próprio (`CORTES_POR_PRATO`) fica com o corte; os outros, com o
    porcionado comum. None quando o insumo não é carne da cozinha fria.
    """
    peca = insumo if insumo in GERAL else PORCIONADOS.get(insumo)
    if peca is None:
        return None
    nome = chave(prato)
    for (comeco, da_peca), producao in CORTES_POR_PRATO.items():
        if da_peca == peca and nome.startswith(comeco):
            return producao
    return GERAL[peca]


def montar_plano() -> dict:
    """O que muda no banco, sem gravar nada.

    Devolve:
    - 'producoes': [{nome, peca, existe, tipo_atual}] — as produções;
    - 'fichas_de_prato': [(prato, de, para, quantidade)] a trocar;
    - 'fichas_de_producao': [(receita, de, para, quantidade)] a trocar;
    - 'linhas_da_contagem': [(descrição, de, para)] a remapear;
    - 'contagens_a_mover': [(data, descrição, quantidade, de, para)] — o que
      já foi contado nessas linhas, e que muda de insumo junto com elas;
    - 'fichas_acrescentadas': [(prato, produção, quantidade)] que o prato
      passa a levar (`ACRESCIMOS`);
    - 'cortes_sem_prato': corte próprio que nenhum prato cita;
    - 'problemas': o que impede de gravar.
    """
    conn = get_connection()
    insumos = {
        linha["nome"]: dict(linha)
        for linha in conn.execute(
            "SELECT id, nome, unidade_medida, tipo FROM insumos"
        ).fetchall()
    }
    fichas_prato = conn.execute(
        """SELECT p.nome AS dono, i.nome AS insumo, f.quantidade_por_prato AS quantidade
             FROM ficha_tecnica f
             JOIN pratos p ON p.id = f.prato_id
             JOIN insumos i ON i.id = f.insumo_id"""
    ).fetchall()
    fichas_producao = conn.execute(
        """SELECT d.nome AS dono, i.nome AS insumo, f.quantidade_por_receita AS quantidade,
                  d.rendimento
             FROM ficha_producao f
             JOIN insumos d ON d.id = f.producao_id
             JOIN insumos i ON i.id = f.insumo_id"""
    ).fetchall()
    receitas = {}
    for f in fichas_producao:
        receitas.setdefault(f["dono"], []).append((f["insumo"], f["quantidade"]))
    rendimentos = {f["dono"]: f["rendimento"] for f in fichas_producao}
    linhas = conn.execute(
        """SELECT ic.id, ic.descricao, i.nome AS insumo
             FROM itens_contagem ic JOIN insumos i ON i.id = ic.insumo_id"""
    ).fetchall()
    contadas = conn.execute(
        """SELECT ci.data, ic.descricao, ci.quantidade
             FROM contagens_itens ci JOIN itens_contagem ic ON ic.id = ci.item_id
            ORDER BY ci.data, ic.descricao"""
    ).fetchall()
    conn.close()

    problemas = []
    for peca in GERAL:
        if peca not in insumos:
            problemas.append(f"O insumo '{peca}' não existe.")
        elif insumos[peca]["unidade_medida"] != "kg":
            problemas.append(f"'{peca}' não está em kg, e o porcionamento é por kg de peça.")
    producoes = []
    for nome, peca in PORCIONADOS.items():
        if peca not in insumos:
            continue
        atual = insumos.get(nome)
        if atual and atual["unidade_medida"] != "kg":
            problemas.append(f"'{nome}' já existe em '{atual['unidade_medida']}', e não em kg.")
        # Corte sem receita copia a do porcionado comum da peça, se houver.
        modelo = GERAL[peca]
        receita = receitas.get(nome) or receitas.get(modelo) or [(peca, 1.0)]
        producoes.append({
            "nome": nome, "peca": peca,
            "existe": atual is not None,
            "tipo_atual": atual["tipo"] if atual else None,
            "tem_receita": nome in receitas,
            "receita": sorted(receita),
            "rendimento": rendimentos.get(nome) or rendimentos.get(modelo) or RENDIMENTO_INICIAL,
        })

    # Quem já cita o destino não pode citar a origem também: a ficha tem
    # um insumo por linha, e a troca faria duas linhas iguais.
    def trocas(fichas, pular):
        ja_cita = {(f["dono"], f["insumo"]) for f in fichas}
        saida = []
        for f in fichas:
            if f["dono"] in pular:
                continue
            destino = porcionado_para(f["dono"], f["insumo"])
            if destino is None or destino == f["insumo"]:
                continue
            if (f["dono"], destino) in ja_cita:
                problemas.append(
                    f"'{f['dono']}' cita '{f['insumo']}' e '{destino}'. Deixe só um "
                    "na Ficha Técnica antes."
                )
                continue
            saida.append((f["dono"], f["insumo"], destino, f["quantidade"]))
        return saida

    fichas_de_prato = trocas(fichas_prato, set())
    # A receita do próprio porcionado é a que consome a peça: fica. Receita
    # de outra produção não tem corte próprio e cai no porcionado comum.
    fichas_de_producao = trocas(fichas_producao, set(PORCIONADOS))

    linhas_da_contagem = []
    for linha in linhas:
        destino = porcionado_de(linha["descricao"])
        if destino is None or linha["insumo"] == destino:
            continue
        linhas_da_contagem.append((linha["descricao"], linha["insumo"], destino))

    # A linha que muda de insumo leva junto o que já foi contado nela: o
    # total gravado de cada insumo naquele dia é refeito a partir das linhas.
    mudam = {descricao: (de, para) for descricao, de, para in linhas_da_contagem}
    contagens_a_mover = [
        (c["data"], c["descricao"], c["quantidade"], *mudam[c["descricao"]])
        for c in contadas if c["descricao"] in mudam
    ]

    ja_leva = {(f["dono"], f["insumo"]) for f in fichas_prato}
    ja_leva |= {(dono, para) for dono, _, para, _ in fichas_de_prato}
    fichas_acrescentadas = sorted(
        (prato, producao, quantidade)
        for prato in {f["dono"] for f in fichas_prato}
        for producao, quantidade in acrescimos_do_prato(prato)
        if (prato, producao) not in ja_leva
    )

    citados = {f["insumo"] for f in fichas_prato}
    citados |= {para for _, _, para, _ in fichas_de_prato}
    citados |= {producao for _, producao, _ in fichas_acrescentadas}
    cortes_sem_prato = sorted(
        corte for corte in set(CORTES_POR_PRATO.values()) if corte not in citados
    )

    return {
        "producoes": producoes,
        "fichas_de_prato": fichas_de_prato,
        "fichas_de_producao": fichas_de_producao,
        "linhas_da_contagem": linhas_da_contagem,
        "contagens_a_mover": contagens_a_mover,
        "fichas_acrescentadas": fichas_acrescentadas,
        "cortes_sem_prato": cortes_sem_prato,
        "problemas": problemas,
    }


def ha_o_que_fazer(plano: dict) -> bool:
    return bool(
        any(not p["existe"] or p["tipo_atual"] != "producao" for p in plano["producoes"])
        or plano["fichas_de_prato"] or plano["fichas_de_producao"]
        or plano["linhas_da_contagem"] or plano.get("fichas_acrescentadas")
    )


def aplicar_plano(plano: dict) -> dict:
    """Grava o plano, tudo ou nada.

    Produção que já existe (a importação da contagem pode ter criado o
    insumo como cru) vira produção, sem perder o id nem o histórico. A
    receita só é criada se a produção ainda não tiver uma: a cozinha pode
    ter corrigido o rendimento na Ficha Técnica.
    """
    from crud import _atualizar_linhas, _inserir_varias, refazer_totais_contados

    if plano["problemas"]:
        raise ValueError("Há problemas a resolver antes de gravar.")

    conn = get_connection()
    try:
        _inserir_varias(
            conn, "insumos",
            ("nome", "unidade_medida", "estoque_minimo", "tipo", "rendimento", "setor"),
            [(p["nome"], "kg", 0, "producao", p.get("rendimento", RENDIMENTO_INICIAL), "cozinha")
             for p in plano["producoes"] if not p["existe"]],
        )
        ids = {
            linha["nome"]: linha["id"]
            for linha in conn.execute("SELECT id, nome FROM insumos").fetchall()
        }
        viraram = [p["nome"] for p in plano["producoes"]
                   if p["existe"] and p["tipo_atual"] != "producao"]
        for nome in viraram:
            conn.execute(
                """UPDATE insumos SET tipo = 'producao', setor = 'cozinha',
                          rendimento = COALESCE(rendimento, ?)
                    WHERE id = ?""",
                (RENDIMENTO_INICIAL, ids[nome]),
            )

        com_receita = {
            linha["producao_id"]
            for linha in conn.execute("SELECT DISTINCT producao_id FROM ficha_producao").fetchall()
        }
        receitas = [(ids[p["nome"]], ids[insumo], quantidade)
                    for p in plano["producoes"] if ids[p["nome"]] not in com_receita
                    for insumo, quantidade in p.get("receita", [(p["peca"], 1.0)])]
        _inserir_varias(
            conn, "ficha_producao", ("producao_id", "insumo_id", "quantidade_por_receita"),
            receitas,
        )

        pratos = {
            linha["nome"]: linha["id"]
            for linha in conn.execute("SELECT id, nome FROM pratos").fetchall()
        }
        for dono, cru, destino, _ in plano["fichas_de_prato"]:
            conn.execute(
                "UPDATE ficha_tecnica SET insumo_id = ? WHERE prato_id = ? AND insumo_id = ?",
                (ids[destino], pratos[dono], ids[cru]),
            )
        _inserir_varias(
            conn, "ficha_tecnica", ("prato_id", "insumo_id", "quantidade_por_prato"),
            [(pratos[prato], ids[producao], quantidade)
             for prato, producao, quantidade in plano.get("fichas_acrescentadas", [])],
        )
        for dono, cru, destino, _ in plano["fichas_de_producao"]:
            conn.execute(
                "UPDATE ficha_producao SET insumo_id = ? WHERE producao_id = ? AND insumo_id = ?",
                (ids[destino], ids[dono], ids[cru]),
            )

        itens = {
            linha["descricao"]: linha["id"]
            for linha in conn.execute("SELECT id, descricao FROM itens_contagem").fetchall()
        }
        _atualizar_linhas(
            conn, "itens_contagem", {"insumo_id": "INTEGER"},
            {itens[descricao]: (ids[destino],)
             for descricao, _, destino in plano["linhas_da_contagem"]},
        )
        refeitos = refazer_totais_contados(
            conn,
            {ids[nome] for _, de, para in plano["linhas_da_contagem"] for nome in (de, para)},
            sorted({data for data, *_ in plano.get("contagens_a_mover", [])}),
            "total refeito na separação da cozinha fria",
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return {
        "producoes_criadas": sum(1 for p in plano["producoes"] if not p["existe"]),
        "viraram_producao": len(viraram),
        "receitas_criadas": len(receitas),
        "fichas_trocadas": len(plano["fichas_de_prato"]) + len(plano["fichas_de_producao"]),
        "fichas_acrescentadas": len(plano.get("fichas_acrescentadas", [])),
        "linhas_remapeadas": len(plano["linhas_da_contagem"]),
        "totais_refeitos": refeitos,
    }
