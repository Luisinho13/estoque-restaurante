"""
sugestao_compra.py
Previsão de demanda da semana e a sugestão de compra que sai dela.

A pergunta da segunda-feira é "o que eu compro para os próximos sete
dias?". A resposta tem dois passos:

1. **Previsão de demanda, prato a prato e dia a dia.** Restaurante vende
   por dia da semana: o sábado não se parece com a terça. Então a
   previsão de cada prato para um sábado é a média dos últimos sábados
   que o PDV registrou, com peso maior para o mais recente (4, 3, 2, 1
   nas últimas quatro semanas; só as semanas que têm dado entram na conta). Com uma semana só de histórico, a
   previsão é exatamente a semana passada.
   Dia sem venda lançada **não conta como zero**: fica fora da média
   (zero seria esquecimento, não demanda). Dia marcado como "o
   restaurante não abriu" conta como zero, porque é.

2. **Da demanda para a compra:**

       necessidade = previsão × ficha do prato, descida até o cru
                     + baixas (quebra, consumo da equipe), na média diária
       comprar     = necessidade dos dias cobertos
                     + estoque mínimo − estoque atual

Duas diferenças em relação ao cálculo do estoque, de propósito:

- **A demanda desce até o cru.** No estoque, a venda da parmegiana tira o
  molho, e o tomate só sai quando a cozinha lança a produção do molho.
  Para prever compra isso não serve: produção esquecida faria o tomate
  sumir da lista. Aqui a previsão atravessa a ficha da produção
  (quantidade por receita ÷ rendimento) até chegar no que se compra.
- **A produção que já está pronta desconta.** Se a câmara tem 30 kg de
  alcatra porcionada, a necessidade de porcionado é abatida antes de
  descer para a peça (a conta de MRP: o que desce para o nível de baixo é
  a necessidade líquida do nível de cima).

Só entra na lista o insumo comprado que a previsão movimenta. Insumo
parado abaixo do mínimo fica de fora da mensagem (só é contado no fim):
com quase todo mínimo em 5, a lista viraria o catálogo inteiro.
"""

import datetime
import math
import time
import urllib.parse
import urllib.request

import crud
from database import get_connection

DIAS_A_COBRIR = 7
SEMANAS_DE_HISTORICO = 4

# Até onde o "quando acaba" olha para a frente. Passou disso, o item só
# está na lista para repor o mínimo.
HORIZONTE_DO_ACABA = 60

# Unidades que se compram em fração. O resto (garrafa, lata, caixa,
# pacote, maço...) arredonda para cima, inteiro: ninguém compra 2,3 latas.
UNIDADES_FRACIONADAS = {"kg", "l"}

DIAS_DA_SEMANA = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")

SEM_FORNECEDOR = "Sem fornecedor ainda"


def _dia(data_iso: str) -> datetime.date:
    return datetime.date.fromisoformat(data_iso)


def _arredondar_para_cima(quantidade: float, unidade: str) -> float:
    # O desconto de 1e-9 evita que 3,0000000001 (erro de ponto flutuante)
    # vire 4 latas.
    if unidade in UNIDADES_FRACIONADAS:
        return math.ceil(quantidade * 10 - 1e-9) / 10
    return float(math.ceil(quantidade - 1e-9))


def _ordem_das_producoes(producoes: set, usa: dict) -> list:
    """Produções de cima para baixo: quem usa vem antes de quem é usado.

    O molho que vai em outro molho só pode ser descido depois que toda a
    necessidade dele (vinda dos pratos e do molho de cima) foi somada. Uma
    produção presa num ciclo (a tela de ficha impede, mas um banco antigo
    pode ter) vai para o fim, em vez de sumir.
    """
    usado_por = {p: 0 for p in producoes}
    for p in producoes:
        for ingrediente in usa.get(p, {}):
            if ingrediente in usado_por:
                usado_por[ingrediente] += 1
    fila = sorted(p for p, n in usado_por.items() if n == 0)
    ordem = []
    while fila:
        p = fila.pop()
        ordem.append(p)
        for ingrediente in usa.get(p, {}):
            if ingrediente in usado_por:
                usado_por[ingrediente] -= 1
                if usado_por[ingrediente] == 0:
                    fila.append(ingrediente)
    return ordem + sorted(p for p in producoes if p not in ordem)


# ---------- Previsão de demanda ----------

def janela_de_historico(semanas: int = SEMANAS_DE_HISTORICO,
                        dia: datetime.date = None) -> tuple[str, str]:
    """As `semanas` semanas fechadas (segunda a domingo) antes da semana de `dia`."""
    segunda = crud.segunda_da_semana(dia)
    inicio = segunda - datetime.timedelta(days=7 * semanas)
    return inicio.isoformat(), (segunda - datetime.timedelta(days=1)).isoformat()


def prever_demanda(vendas: dict, observados: dict, dias: list[datetime.date],
                   segunda: datetime.date, semanas: int = SEMANAS_DE_HISTORICO) -> dict:
    """Quanto de cada prato se espera vender em cada um dos `dias`.

    `vendas` é {(prato, data): quantidade}; `observados` é {data: True}
    para os dias que o histórico conhece (com venda lançada ou fechados).
    Devolve {prato: {data: previsão}}.

    Para cada dia previsto, a média ponderada do mesmo dia da semana no
    histórico, pesando mais a semana mais recente. Se o histórico não tem
    nenhum dia daquele (ex.: o sistema começou numa quarta e o dia previsto
    é segunda), vale a média ponderada de todos os dias conhecidos.
    """
    def peso(data):
        # Com quatro semanas: a passada pesa 4, a retrasada 3, e assim por diante.
        semanas_atras = (segunda - crud.segunda_da_semana(data)).days // 7
        return max(0, semanas + 1 - semanas_atras)

    por_dia_da_semana = {}
    for data in observados:
        por_dia_da_semana.setdefault(data.weekday(), []).append(data)
    todos = list(observados)

    pratos = {prato for prato, _ in vendas}
    previsao = {prato: {} for prato in pratos}
    for dia_previsto in dias:
        base = por_dia_da_semana.get(dia_previsto.weekday()) or todos
        soma_pesos = sum(peso(d) for d in base)
        if not soma_pesos:
            continue
        for prato in pratos:
            valor = sum(peso(d) * vendas.get((prato, d), 0) for d in base) / soma_pesos
            if valor:
                previsao[prato][dia_previsto] = valor
    return {prato: por_dia for prato, por_dia in previsao.items() if por_dia}


# ---------- Da demanda para o cru ----------

def _descer_ate_o_cru(direto: dict, insumos: dict, usa: dict, ordem: list) -> dict:
    """Desce uma necessidade por todas as produções, sem abater estoque."""
    total = dict(direto)
    for producao_id in ordem:
        quantidade = total.get(producao_id)
        rendimento = insumos[producao_id]["rendimento"]
        if not quantidade or not rendimento or rendimento <= 0:
            continue
        for ingrediente, por_receita in usa.get(producao_id, {}).items():
            total[ingrediente] = total.get(ingrediente, 0) + quantidade * por_receita / rendimento
    return total


def calcular(dias_a_cobrir: int = DIAS_A_COBRIR,
             semanas: int = SEMANAS_DE_HISTORICO) -> dict:
    """A previsão de demanda dos próximos `dias_a_cobrir` dias e a compra que ela pede."""
    hoje = crud.hoje()
    segunda = crud.segunda_da_semana(hoje)
    inicio, fim = janela_de_historico(semanas, hoje)
    dias = [hoje + datetime.timedelta(days=n) for n in range(dias_a_cobrir)]

    conn = get_connection()
    insumos = {
        linha["id"]: dict(linha)
        for linha in conn.execute(
            "SELECT id, nome, unidade_medida, estoque_minimo, tipo, rendimento FROM insumos"
        ).fetchall()
    }
    pratos = {}
    vendas = {}
    for linha in conn.execute(
        """SELECT p.id, p.nome, v.data, SUM(v.quantidade) AS vendidos
             FROM vendas_diarias v JOIN pratos p ON p.id = v.prato_id
            WHERE v.data >= ? AND v.data <= ?
            GROUP BY p.id, p.nome, v.data""",
        (inicio, fim),
    ).fetchall():
        pratos[linha["id"]] = linha["nome"]
        vendas[(linha["id"], _dia(linha["data"]))] = linha["vendidos"]
    ficha_prato = {}
    for linha in conn.execute(
        "SELECT prato_id, insumo_id, quantidade_por_prato FROM ficha_tecnica"
    ).fetchall():
        ficha_prato.setdefault(linha["prato_id"], []).append(
            (linha["insumo_id"], linha["quantidade_por_prato"]))
    usa = {}
    for linha in conn.execute(
        "SELECT producao_id, insumo_id, quantidade_por_receita FROM ficha_producao"
    ).fetchall():
        usa.setdefault(linha["producao_id"], {})[linha["insumo_id"]] = linha["quantidade_por_receita"]
    baixas = conn.execute(
        """SELECT insumo_id, SUM(quantidade) AS quantidade FROM baixas
            WHERE data >= ? AND data <= ? GROUP BY insumo_id""",
        (inicio, fim),
    ).fetchall()
    # O fornecedor da compra mais recente de cada insumo: é com quem a
    # equipe vai falar, então a mensagem agrupa por ele.
    fornecedor = {}
    for linha in conn.execute(
        """SELECT insumo_id, fornecedor FROM compras
            WHERE fornecedor IS NOT NULL AND fornecedor <> ''
            ORDER BY data, id"""
    ).fetchall():
        fornecedor[linha["insumo_id"]] = linha["fornecedor"].strip()
    inicio_do_uso = crud._inicio_do_uso(conn)
    conn.close()

    estoques = {e["insumo"]: e for e in crud.calcular_estoque_todos_insumos()}
    fechados = {_dia(d) for d in crud.dias_sem_movimento(inicio, fim)}

    # Os dias que o histórico conhece, e os que ele deveria conhecer mas
    # ficaram sem venda lançada (antes de o sistema entrar em uso não conta).
    com_venda = {data for _, data in vendas}
    observados = {d: True for d in com_venda | fechados}
    sem_venda = []
    d = _dia(inicio)
    while d <= _dia(fim):
        if d not in observados and inicio_do_uso and d >= inicio_do_uso:
            sem_venda.append(d.isoformat())
        d += datetime.timedelta(days=1)

    previsao = prever_demanda(vendas, observados, dias, segunda, semanas)
    semana_passada = segunda - datetime.timedelta(days=7)
    vendido_semana_passada = {}
    for (prato_id, data), quantidade in vendas.items():
        if data >= semana_passada:
            vendido_semana_passada[prato_id] = vendido_semana_passada.get(prato_id, 0) + quantidade

    # Baixa não tem dia da semana que preste (quebra é acaso): entra pela
    # média diária dos dias conhecidos.
    baixa_por_dia = {linha["insumo_id"]: linha["quantidade"] / max(1, len(observados))
                     for linha in baixas}

    # direto[dia]: o que a previsão tira de cada item naquele dia, no
    # primeiro nível (prato → o que está na ficha dele), mais a baixa.
    sem_ficha = {}
    direto_por_dia = {}
    for dia in dias:
        direto = dict(baixa_por_dia)
        for prato_id, por_dia in previsao.items():
            quantidade = por_dia.get(dia, 0)
            itens = ficha_prato.get(prato_id)
            if not itens:
                sem_ficha[prato_id] = sem_ficha.get(prato_id, 0) + quantidade
                continue
            for insumo_id, por_prato in itens:
                direto[insumo_id] = direto.get(insumo_id, 0) + quantidade * por_prato
        direto_por_dia[dia] = direto

    producoes = {i for i, dado in insumos.items() if dado["tipo"] == "producao"}
    ordem = _ordem_das_producoes(producoes, usa)

    # Ritmo de consumo de cada item, por dia da semana, já descido até o
    # cru: é ele que diz em que dia o estoque acaba.
    por_dia_da_semana = {}
    for dia in dias[:7]:
        por_dia_da_semana[dia.weekday()] = _descer_ate_o_cru(
            direto_por_dia[dia], insumos, usa, ordem)

    # A necessidade do período, descida com a conta de MRP: em cada
    # produção, abate o que já está pronto e soma o mínimo dela; só o
    # líquido desce para os ingredientes.
    def saldo(insumo_id):
        # Estoque negativo é conta que não fechou (venda sem produção
        # lançada, compra esquecida). Na prateleira não há menos que zero.
        return max(0.0, estoques[insumos[insumo_id]["nome"]]["estoque_atual"])

    pedido = {}
    for direto in direto_por_dia.values():
        for insumo_id, quantidade in direto.items():
            pedido[insumo_id] = pedido.get(insumo_id, 0) + quantidade
    sem_receita = []
    for producao_id in ordem:
        if not pedido.get(producao_id):
            continue
        dado = insumos[producao_id]
        rendimento = dado["rendimento"]
        if not usa.get(producao_id) or not rendimento or rendimento <= 0:
            sem_receita.append(dado["nome"])
            continue
        liquido = max(0.0, pedido[producao_id] + dado["estoque_minimo"] - saldo(producao_id))
        for ingrediente, por_receita in usa[producao_id].items():
            pedido[ingrediente] = pedido.get(ingrediente, 0) + liquido * por_receita / rendimento

    def quando_acaba(insumo_id, estoque):
        if estoque <= 0:
            return hoje
        if not any(c.get(insumo_id) for c in por_dia_da_semana.values()):
            return None
        for n in range(HORIZONTE_DO_ACABA):
            dia = hoje + datetime.timedelta(days=n)
            estoque -= por_dia_da_semana.get(dia.weekday(), {}).get(insumo_id, 0)
            if estoque < 0:
                return dia
        return None

    itens = []
    for insumo_id, necessidade in pedido.items():
        dado = insumos[insumo_id]
        if dado["tipo"] == "producao" or necessidade <= 0:
            continue
        estoque = estoques[dado["nome"]]
        atual = saldo(insumo_id)
        falta = necessidade + dado["estoque_minimo"] - atual
        if falta <= 1e-9:
            continue
        acaba = quando_acaba(insumo_id, atual)
        itens.append({
            "insumo": dado["nome"],
            "unidade_medida": dado["unidade_medida"],
            "comprar": _arredondar_para_cima(falta, dado["unidade_medida"]),
            "necessidade": round(necessidade, 3),
            "estoque_atual": estoque["estoque_atual"],
            "estoque_minimo": dado["estoque_minimo"],
            "acaba_em": acaba.isoformat() if acaba else None,
            "sem_contagem": estoque["baseline_usada"] == crud.SEM_CONTAGEM,
            "fornecedor": fornecedor.get(insumo_id, SEM_FORNECEDOR),
        })
    itens.sort(key=lambda i: (i["fornecedor"] == SEM_FORNECEDOR, i["fornecedor"],
                              i["acaba_em"] or "9999", i["insumo"]))

    movimentados = {insumos[i]["nome"] for i, q in pedido.items() if q > 0}
    parados = sorted(
        e["insumo"] for e in estoques.values()
        if e["tipo"] != "producao" and e["abaixo_do_minimo"]
        and e["baseline_usada"] != crud.SEM_CONTAGEM and e["insumo"] not in movimentados
    )

    demanda = sorted(
        (
            {
                "prato": pratos[prato_id],
                "previsto": round(sum(por_dia.values()), 1),
                "semana_passada": vendido_semana_passada.get(prato_id, 0),
                "por_dia": {d.isoformat(): round(q, 1) for d, q in sorted(por_dia.items())},
                "sem_ficha": prato_id in sem_ficha,
            }
            for prato_id, por_dia in previsao.items()
        ),
        key=lambda p: (-p["previsto"], p["prato"]),
    )
    semanas_com_dado = len({crud.segunda_da_semana(d) for d in observados})

    return {
        "hoje": hoje.isoformat(),
        "de": dias[0].isoformat(),
        "ate": dias[-1].isoformat(),
        "dias_a_cobrir": dias_a_cobrir,
        "historico": {"inicio": inicio, "fim": fim, "semanas": semanas,
                      "semanas_com_dado": semanas_com_dado},
        "demanda": demanda,
        "previsto_total": round(sum(p["previsto"] for p in demanda)),
        "semana_passada_total": sum(vendido_semana_passada.values()),
        "previsto_por_dia": {
            dia.isoformat(): round(sum(p.get(dia, 0) for p in previsao.values()))
            for dia in dias
        },
        "itens": itens,
        "dias_sem_venda": sem_venda,
        "pratos_sem_ficha": [p for p in demanda if p["sem_ficha"]],
        "producoes_sem_receita": sorted(sem_receita),
        "parados_abaixo_do_minimo": parados,
    }


# ---------- Mensagem ----------

def _dia_curto(data_iso: str) -> str:
    data = _dia(data_iso)
    return f"{DIAS_DA_SEMANA[data.weekday()]} {data.strftime('%d/%m')}"


def _numero(valor: float) -> str:
    return f"{valor:g}".replace(".", ",")


def _quando_acaba(item: dict, hoje: str) -> str:
    if item["estoque_atual"] <= 0:
        return "já acabou"
    if item["acaba_em"] is None:
        return "repor o mínimo"
    if item["acaba_em"] <= hoje:
        return "acaba hoje"
    return f"acaba {_dia_curto(item['acaba_em'])}"


def mensagem(sugestao: dict) -> str:
    """O texto do WhatsApp: a previsão da semana e, por fornecedor, quanto comprar e quando acaba."""
    historico = sugestao["historico"]
    linhas = [
        f"🛒 *Sugestão de compra — {_dia_curto(sugestao['hoje'])}*",
        "",
        f"📈 *Previsão de {_dia_curto(sugestao['de'])} a {_dia_curto(sugestao['ate'])}:* "
        f"~{sugestao['previsto_total']} pratos e drinks"
        f" (semana passada: {sugestao['semana_passada_total']})",
    ]
    if historico["semanas_com_dado"]:
        linhas.append(
            f"Base: {historico['semanas_com_dado']} semana(s) de vendas do PDV, "
            "por dia da semana, peso maior na mais recente"
        )
    if sugestao["demanda"]:
        mais = ", ".join(f"{p['prato']} {_numero(round(p['previsto']))}"
                         for p in sugestao["demanda"][:5])
        linhas.append(f"Mais pedidos: {mais}")
        movimento = max(sugestao["previsto_por_dia"], key=sugestao["previsto_por_dia"].get)
        linhas.append(f"Dia mais cheio: {_dia_curto(movimento)} "
                      f"(~{sugestao['previsto_por_dia'][movimento]})")

    if not sugestao["demanda"]:
        linhas += ["", "Nenhuma venda lançada no histórico: não há base para prever."]
    elif not sugestao["itens"]:
        linhas += ["", "Nada a comprar: o estoque cobre a previsão."]

    atual = None
    for item in sugestao["itens"]:
        if item["fornecedor"] != atual:
            atual = item["fornecedor"]
            linhas += ["", f"*{atual}*"]
        marca = " (sem contagem)" if item["sem_contagem"] else ""
        linhas.append(
            f"• {item['insumo']} — {_numero(item['comprar'])} {item['unidade_medida']}"
            f" ({_quando_acaba(item, sugestao['hoje'])}){marca}"
        )

    avisos = []
    if sugestao["dias_sem_venda"]:
        dias = ", ".join(_dia_curto(d) for d in sugestao["dias_sem_venda"][-7:])
        avisos.append(f"Dias sem venda lançada, fora da previsão: {dias}.")
    if sugestao["pratos_sem_ficha"]:
        nomes = ", ".join(p["prato"] for p in sugestao["pratos_sem_ficha"][:5])
        mais = len(sugestao["pratos_sem_ficha"]) - 5
        avisos.append(
            f"{len(sugestao['pratos_sem_ficha'])} prato(s) previsto(s) sem ficha técnica, "
            f"fora da compra: {nomes}" + (f" e mais {mais}" if mais > 0 else "") + "."
        )
    if sugestao["producoes_sem_receita"]:
        avisos.append("Produção sem receita ou rendimento (o cru dela não entrou): "
                      + ", ".join(sugestao["producoes_sem_receita"]) + ".")
    if sugestao["parados_abaixo_do_minimo"]:
        avisos.append(f"{len(sugestao['parados_abaixo_do_minimo'])} insumo(s) parado(s) "
                      "abaixo do mínimo, fora desta lista (ver no app).")
    if avisos:
        linhas += [""] + [f"⚠️ {aviso}" for aviso in avisos]
    return "\n".join(linhas)


# ---------- Envio pelo CallMeBot ----------

URL_CALLMEBOT = "https://api.callmebot.com/whatsapp.php"

# O texto vai na URL. Acento e emoji triplicam de tamanho quando
# codificados, então a mensagem longa é cortada em partes, sempre entre
# linhas, para nenhum item ficar partido no meio.
TAMANHO_DA_PARTE = 1200
ESPERA_ENTRE_PARTES = 6  # segundos: o bot gratuito recusa rajada


def partes(texto: str, tamanho: int = TAMANHO_DA_PARTE) -> list[str]:
    resultado, atual = [], ""
    for linha in texto.split("\n"):
        if atual and len(atual) + 1 + len(linha) > tamanho:
            resultado.append(atual)
            atual = linha
        else:
            atual = f"{atual}\n{linha}" if atual else linha
    if atual:
        resultado.append(atual)
    if len(resultado) > 1:
        total = len(resultado)
        resultado = [f"{parte}\n\n({n}/{total})" for n, parte in enumerate(resultado, 1)]
    return resultado


def enviar_whatsapp(texto: str, telefone: str, chave: str) -> int:
    """Manda o texto para o WhatsApp de `telefone` pelo CallMeBot. Devolve quantas partes."""
    pedacos = partes(texto)
    for n, pedaco in enumerate(pedacos):
        if n:
            time.sleep(ESPERA_ENTRE_PARTES)
        url = URL_CALLMEBOT + "?" + urllib.parse.urlencode(
            {"phone": telefone, "text": pedaco, "apikey": chave})
        with urllib.request.urlopen(url, timeout=60) as resposta:
            corpo = resposta.read().decode("utf-8", "replace")
        # O CallMeBot responde 200 mesmo quando recusa (chave errada,
        # número não ativado); o motivo vem no corpo da página.
        if "apikey is invalid" in corpo.lower() or "error" in corpo.lower():
            raise RuntimeError(f"O CallMeBot recusou a parte {n + 1}: {corpo[:300]}")
    return len(pedacos)
