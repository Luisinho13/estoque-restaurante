"""
bar_import.py
Lê a planilha de fichas do bar ("Preparos bar villa.xlsx") e transforma cada
aba em drink (prato do setor bar) ou em preparo (produção do bar: caldas,
xarope, espuma), no mesmo formato de plano da ficha da cozinha. A tela de
importação mostra a prévia e `ficha_import.aplicar_plano` grava.

Pedido do usuário em 30/09/2026: a saída do bar passa a seguir a ficha
técnica, como a da cozinha. O que muda em relação à cozinha:

1. **A dose está em litro, e a garrafa é contada em garrafa.** A planilha
   escreve "Kg" mas o número é litro (0,05 de gin = 50 ml). O estoque conta
   destilado em garrafa, tônica em lata. A conversão usa o volume escrito no
   nome do insumo ("Gin Bombay 750 ml" → 0,05 ÷ 0,75 = 0,067 garrafa). Onde
   o nome não diz o volume, a quantidade entra como está e vira aviso.

2. **Os nomes são marcas.** "Gin Bombay", "Jack Daniels N07", "Tônica":
   INGREDIENTES traduz cada grafia para o insumo que a contagem já criou
   (um por produto). Onde a tradução é palpite meu, sai em `avisos`.

3. **A planilha tem sobras de cópia.** A aba "Fresh Ginger" leva 0,2 kg de
   batata noisete, linha herdada de uma ficha da cozinha; o rendimento é
   2,33 em quase todas as abas, que é o valor do modelo. Essas coisas são
   ignoradas e listadas, não lidas como verdade.

Nada aqui grava: `montar_plano()` devolve o que seria feito.
"""

import re

import openpyxl

from database import get_connection
from ficha_import import chave

SETOR = "bar"

# ---------- Onde cada coisa mora na aba ----------
# O formulário é o mesmo da cozinha, mas metade das abas está deslocada uma
# coluna para a esquerda. O deslocamento é achado pela célula "Ingredientes"
# do cabeçalho, e as outras colunas são contadas a partir dela.
LINHA_NOME_TECNICO = 3
LINHA_NOME_VENDA = 4
LINHA_CABECALHO = 6
LINHA_PRIMEIRO_INGREDIENTE = 7
LINHA_ULTIMO_INGREDIENTE = 23
LINHA_RENDIMENTO = 25
LINHA_PORCOES = 29
# Distância de cada campo até a coluna dos ingredientes.
DESLOCA_NOME = 2
DESLOCA_UNIDADE = 2
DESLOCA_QUANTIDADE = 3
DESLOCA_VALOR = 8        # rendimento
DESLOCA_PORCOES = 1

# ---------- Abas que são preparo, não drink ----------
# Chave: aba por `chave()`. Valor: nome da produção no sistema. Tudo em litro.
PREPAROS = {
    "calda de amora": "Calda de amora",
    "calda de framboesa": "Calda de framboesa",
    "xarope simples": "Xarope simples",
    "espuma de gengibre": "Espuma de gengibre",
    # Conde de Campos é receita de lote (3 L de água quente, meio litro de
    # cachaça), não uma dose. Como produção, lançar o lote tira a cachaça e o
    # gin do estoque. Falta saber quanto vai num copo para ligar a venda.
    "conde de campos": "Conde de Campos (lote)",
}

# Nome do drink no sistema, quando o da aba não serve. O resto fica com o
# nome da aba, que é como o bar chama o drink.
NOMES_DE_DRINK = {
    "gin tonica frutas vermelhas": "Gin Tônica Frutas Vermelhas",
    "gt morango": "Gin Tônica Morango",
    "gt laranja": "Gin Tônica Laranja",
    "gin tonica": "Gin Tônica",
    "caipirinha de limao": "Caipirinha de Limão",
    "sex on the beach": "Sex on the Beach",
    "campari tonic": "Campari Tônica",
    "dark n stormy": "Dark N Stormy",
    "j'adore": "J'Adore",
}

# ---------- De grafia da planilha para insumo do sistema ----------
# Valor: o insumo no sistema, com o nome exato que a contagem criou. Os que
# são produção do bar apontam para o nome em PREPAROS.
INGREDIENTES = {
    # destilados, licores e vinhos
    "gin bombay": "Gin Bombay 750 ml",
    "gin beefeater": "Gin Beefeater 750 ml",
    "gin nicks": "Gin Nicks 1000 ml",
    "gin": "Gin Nicks 1000 ml",
    "cachaca": "Cachaça",
    "cachaca velho barreiro": "Cachaça Velho Barreiro 910 ml",
    "campari": "Campari 900 ml",
    "conhaque remi martin": "Conhaque Remi Martin 700 ml",
    "drambuie": "Licor Drambui 750 ml",
    "ramazotti": "Ramazzoti Amaro 700 ml",
    "ramazotti rosato": "Ramazzoti Rosato 700 ml",
    "whisky jack daniels": "Whisky Jack Daniels N07 1000 ml",
    "jack daniels n07": "Whisky Jack Daniels N07 1000 ml",
    "black label": "Whisky Johnnie Walker Black Label 1000 ml",
    "whisky blond": "Whisky Johnnie Walker Blond 1000 ml",
    "buchanans": "Whisky Buchanas 12 Anos",
    "old parr": "Whysky Old Par 1000 ml",
    "vodka grey goose": "Vodka Grey Goose 750 ml",
    "vodka absolut": "Vodka Absolut 1000 ml",
    "vodka smirnoff": "Vodka Smirnoff 1000 ml",
    "lilliet blanc": "Licor Liliet Blanc 750 ml",
    "lillet blanc": "Licor Liliet Blanc 750 ml",
    "lilliet": "Licor Liliet Blanc 750 ml",
    "triple sec": "Licor Cointreau 700 ml",
    "cointreau": "Licor Cointreau 700 ml",
    "rum": "Rum Bacardi Ouro 980 ml",
    "rum bacardi": "Rum Bacardi Carta Blanca Prata 980 ml",
    "rum bacardi prata": "Rum Bacardi Carta Blanca Prata 980 ml",
    "rum carta blanca": "Rum Bacardi Carta Blanca Prata 980 ml",
    "punt e mes": "Put e Mes 750 ml",
    "tequila jose cuervo": "Tequila Prata Jose Cuervo 750 ml",
    "tequila don julio prata": "Tequila Don Julio Prata 750 ml",
    "dry martini": "Martini Dry 750 ml",
    "amarula": "Licor Amarula 750 ml",
    "saque azuma kirin seco": "Saque Azuma Kirin Seco 740 ml",
    "monin gengibre": "Licor Monin Gengibre 700 ml",
    "monin framboesa": "Licor Monin Framboesa 700 ml",
    "monin grapefruit": "Licor Monin Grapefruit 700 ml",
    "monin granadine": "Licor Monin Granadine 700 ml",
    "angostura": "Agostura Tradicional 200 ml",
    "angostura laranja": "Agostura Orange Bitters 100 ml",
    "bitter laranja": "Agostura Orange Bitters 100 ml",
    "cachaca balsamo": "Cachaça Bálsamo",
    "jotape suave box 3lt": "Vinho Jotapê Suave Box 3 L",
    # refrigerantes, águas e sucos
    "tonica": "Tonica Schweppes Original Lata 350 ml",
    "sprite": "Sprite Lata 350 ml",
    "citrus": "Schweppes Citrus Original Lata 350 ml",
    "agua com gas": "Água com Gás Cristal 350 ml VIP",
    "soda": "Água com Gás Cristal 350 ml VIP",
    "ginger": "Ginger ale",
    "suco de laranja": "Suco de laranja",
    "suco de tomate": "Suco de tomate",
    "creme de abacaxi": "Creme de abacaxi",
    "gengibre e mel": "Gengibre e mel",
    "extrato gengibre": "Extrato de gengibre",
    # frutas, ervas e temperos
    "hortela": "Hortelã",
    "manjericao": "Manjericão",
    "alecrim": "Alecrim",
    "morango": "Morango",
    "maracuja": "Polpa de maracujá",
    "maca": "Maçã",
    "laranja": "Laranja",
    "laranja bahia": "Laranja",
    "laranja fatia": "Laranja",
    "fatia laranja": "Laranja",
    "twist de laranja": "Laranja",
    "zest de laranja": "Laranja",
    "limao taiti": "Limão",
    "limao fatia": "Limão",
    "suco de limao": "Limão",
    "suco de limao taiti": "Limão",
    "suco de limao tahiti": "Limão",
    "limao siciliano": "Limão siciliano",
    "suco de limao siciliano": "Limão siciliano",
    "fatia de limao siciliano": "Limão siciliano",
    "amora congelada": "Amora",
    "framboesa congelada": "Framboesa",
    "acucar": "Açúcar",
    "acucar cristal": "Açúcar",
    "canela": "Canela",
    "cravo": "Cravo",
    "gengibre": "Gengibre",
    "zimbro": "Zimbro",
    "sal": "Sal",
    "azeitona": "Azeitona",
    "tabasco": "Molho de pimenta",
    "pimenta tabasco": "Molho de pimenta",
    "molho ingles": "Molho inglês",
    "raspas de chocolate": "Chocolate",
    "cafe": "Café",
    "cafe expresso": "Café",
    "cha frutas vermelhas": "Chá de frutas vermelhas",
    "hibisco": "Hibisco",
    "emulsificante para sorvete": "Emulsificante",
    # preparos do bar
    "xarope acucar": "Xarope simples",
    "xarope de acucar": "Xarope simples",
    "xarope de framboesa": "Calda de framboesa",
    "calda de amora": "Calda de amora",
    "espuma de gengibre": "Espuma de gengibre",
    "espuma moscow mule": "Espuma de gengibre",
}

# Insumo que a planilha do bar cita e o estoque ainda não tem. Entra novo,
# nesta unidade, e aparece na prévia como insumo criado.
NOVOS = {
    "Cachaça Bálsamo": "l",
    "Vinho Jotapê Suave Box 3 L": "caixa",
    "Ginger ale": "l",
    "Creme de abacaxi": "l",
    "Gengibre e mel": "l",
    "Extrato de gengibre": "l",
    "Zimbro": "kg",
    "Chá de frutas vermelhas": "kg",
    "Hibisco": "kg",
    "Emulsificante": "kg",
}

# Volume de 1 garrafa, lata ou caixa, em litro, quando o nome não diz.
VOLUMES = {
    "Vinho Jotapê Suave Box 3 L": 3.0,
}

# Multiplicador para insumo contado por unidade: 1 dose da planilha em litro
# vira quantas unidades. O café expresso vem como 0,03 (30 ml); no estoque,
# café é contado por unidade (uma dose).
FATORES_POR_UNIDADE = {
    "cafe expresso": 1 / 0.03,
}

# Linha que não é da receita: sobra de cópia de outra ficha.
LINHAS_IGNORADAS = {
    ("fresh ginger", "batata noisete"):
        "a linha de 0,2 kg de batata noisete da aba 'Fresh Ginger' é sobra de cópia "
        "da ficha da cozinha e foi ignorada",
}

SEM_ESTOQUE = {"agua quente", "agua filtrada"}
# Mistura de frutas que não é um insumo só: fica de fora da ficha.
SEM_INSUMO_UNICO = {"frutas", "frutas total"}

# Traduções que são interpretação minha, não leitura. Viram aviso.
MAPEAMENTOS_ASSUMIDOS = {
    "gin": "o gin sem marca do Conde de Campos é o Gin Nicks, o da gin tônica da casa",
    "triple sec": "o triple sec é o Cointreau (não há outro na contagem)",
    "rum": "o rum sem marca do Dark N Stormy é o Bacardi Ouro",
    "tequila jose cuervo": "a tequila José Cuervo da margarita é a prata",
    "agua com gas": "a água com gás é a Cristal 350 ml",
    "soda": "a soda é a água com gás Cristal 350 ml",
    "ginger": "'Ginger' é ginger ale, que não está na contagem: entrou como insumo novo",
    "xarope de framboesa": "o xarope de framboesa é a calda de framboesa feita no bar",
    "espuma moscow mule": (
        "a espuma do Moscow Mule é a espuma de gengibre feita no bar. A contagem "
        "tem 'Espuma Moscow Mule' em garrafa: se for a mesma, ligue a linha da "
        "contagem à produção 'Espuma de gengibre' em Itens da Contagem"
    ),
    "cafe expresso": "o café expresso de 30 ml é 1 café (o estoque conta café por unidade)",
    "suco de limao": "o suco de limão foi descontado como limão, na mesma quantidade",
    "suco de limao taiti": "o suco de limão foi descontado como limão, na mesma quantidade",
    "suco de limao tahiti": "o suco de limão foi descontado como limão, na mesma quantidade",
    "suco de limao siciliano": "o suco de limão siciliano foi descontado como limão siciliano",
}

# Um drink que usa bem mais de um insumo que os outros drinks (4× a
# mediana, com ao menos 3 drinks usando) provavelmente tem erro de digitação.
FOLGA_DA_MEDIANA = 4

# Bitter vai em gotas. Acima disto (em litro, por drink) a planilha
# provavelmente escreveu ml onde queria gotas.
BITTER_MAXIMO_POR_DRINK = 0.01

# O que a leitura das abas, uma a uma, encontrou de estranho em 30/09/2026 e
# que a regra geral não pega. É leitura minha da receita, não correção: a
# ficha entra como a planilha diz, e isto aparece para conferência.
AVISOS_DE_ABA = {
    "manhattan": "'Manhattan' não tem whisky na planilha, só Punt e Mes e Angostura: "
                 "falta o destilado base.",
    "dark n stormy": "'Dark N Stormy' leva 0,001 L de ginger ale e 0,1 kg de limão: "
                     "parecem trocados (o drink costuma levar uns 100 ml de ginger ale).",
    "old parr tonic": "'Old Parr Tonic' leva 75 ml de whisky e só 25 ml de tônica: confira "
                      "se não estão invertidos.",
    "espuma de gengibre": "'Espuma de gengibre' leva 1 kg de emulsificante e 1 L de citrus "
                          "por receita: confira se o emulsificante não é em gramas.",
    "clericot": "'Clericot' leva meia garrafa de Lillet (0,375 L): parece jarra, não taça. "
                "Confira como ele é vendido.",
    "caipiroska importada": "A aba 'Caipiroska Importada' tem 'Caipiroska Nacional' como nome "
                            "de venda (cópia da aba anterior); usei o nome da aba.",
}


def _limpa(valor) -> str | None:
    if valor is None:
        return None
    texto = " ".join(str(valor).split()).strip()
    return texto or None


def _numero(valor) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def volume_do_nome(nome: str) -> float | None:
    """Litros de uma garrafa pelo nome: '750 ml' → 0,75; '1 Litro' → 1; '3 L' → 3."""
    if nome in VOLUMES:
        return VOLUMES[nome]
    achado = re.search(r"(\d+(?:[.,]\d+)?)\s*(ml|litros?|l)\b", nome, re.IGNORECASE)
    if not achado:
        return None
    numero = float(achado.group(1).replace(",", "."))
    return numero / 1000 if achado.group(2).lower() == "ml" else numero


# ---------- Leitura das abas ----------

def ler_planilha(arquivo) -> list[dict]:
    """Uma receita por aba preenchida. Aceita caminho ou o upload do Streamlit."""
    wb = openpyxl.load_workbook(arquivo, read_only=True, data_only=True)
    receitas = []
    for ws in wb.worksheets:
        receita = _ler_aba(ws)
        if receita:
            receitas.append(receita)
    wb.close()
    return receitas


def _ler_aba(ws) -> dict | None:
    linhas = list(ws.iter_rows(min_row=1, max_row=LINHA_PORCOES, max_col=14,
                               values_only=True))
    if len(linhas) < LINHA_CABECALHO:
        return None
    cabecalho = [_limpa(c) for c in linhas[LINHA_CABECALHO - 1]]
    if "Ingredientes" not in cabecalho:
        return None
    base = cabecalho.index("Ingredientes")

    def celula(linha, desloca=0):
        if linha - 1 >= len(linhas):
            return None
        conteudo = linhas[linha - 1]
        coluna = base + desloca
        return conteudo[coluna] if coluna < len(conteudo) else None

    ingredientes = []
    for linha in range(LINHA_PRIMEIRO_INGREDIENTE, LINHA_ULTIMO_INGREDIENTE + 1):
        item = _limpa(celula(linha))
        if not item:
            continue
        if item.lower().startswith("unidade:"):
            break
        quantidade = _numero(celula(linha, DESLOCA_QUANTIDADE))
        if quantidade is None or quantidade <= 0:
            continue
        ingredientes.append({
            "nome": item,
            "unidade_declarada": _limpa(celula(linha, DESLOCA_UNIDADE)),
            "quantidade": quantidade,
        })
    if not ingredientes:
        return None

    aba = ws.title.strip()
    return {
        "aba": aba,
        "nome": _limpa(celula(LINHA_NOME_TECNICO, DESLOCA_NOME)) or aba,
        "nome_venda": _limpa(celula(LINHA_NOME_VENDA, DESLOCA_NOME)) or aba,
        "rendimento": _numero(celula(LINHA_RENDIMENTO, DESLOCA_VALOR)),
        "porcoes": _numero(celula(LINHA_PORCOES, DESLOCA_PORCOES)) or 1.0,
        "ingredientes": ingredientes,
    }


# ---------- Montagem do plano ----------

def e_preparo(receita: dict) -> bool:
    return chave(receita["aba"]) in PREPAROS


def nome_do_drink(receita: dict) -> str:
    return NOMES_DE_DRINK.get(chave(receita["aba"]), receita["aba"].strip())


def montar_plano(receitas: list[dict]) -> dict:
    """O plano de gravação, no formato de `ficha_import.montar_plano`.

    Drinks viram pratos do setor bar; preparos viram produções do bar, em
    litro. Toda quantidade sai na unidade do insumo no estoque.
    """
    avisos = []
    # Insumo cuja quantidade não deu para converter: {(insumo, unidade): [(aba, q)]}.
    # Vira um aviso por insumo, não um por drink.
    sem_conversao = {}
    conn = get_connection()
    existentes = {
        d["nome"]: {"unidade": d["unidade_medida"], "tipo": d["tipo"]}
        for d in conn.execute("SELECT nome, unidade_medida, tipo FROM insumos").fetchall()
    }
    ja_tem_prato = {d["nome"] for d in conn.execute("SELECT nome FROM pratos").fetchall()}
    conn.close()

    insumos, tipos = {}, {}
    for receita in receitas:
        if e_preparo(receita):
            nome = PREPAROS[chave(receita["aba"])]
            insumos[nome] = existentes.get(nome, {}).get("unidade", "l")
            tipos[nome] = "producao"

    def resolver(item, receita):
        """(insumo, quantidade na unidade dele), ou None para pular a linha."""
        nome = chave(item["nome"])
        aba = chave(receita["aba"])
        if (aba, nome) in LINHAS_IGNORADAS:
            avisos.append(LINHAS_IGNORADAS[(aba, nome)].capitalize() + ".")
            return None
        if nome in SEM_ESTOQUE:
            return None
        if nome in SEM_INSUMO_UNICO:
            avisos.append(
                f"'{receita['aba']}' leva '{item['nome']}' ({item['quantidade']:g}), que "
                "não é um insumo só: ficou fora da ficha. Se a fruta for sempre a "
                "mesma, acrescente na tela Ficha Técnica."
            )
            return None

        insumo = INGREDIENTES.get(nome)
        if insumo is None:
            insumo = item["nome"].strip().capitalize()
            avisos.append(
                f"'{item['nome']}' ({receita['aba']}) não está na lista de ingredientes "
                f"do bar; entrou como '{insumo}', em litro."
            )
        elif nome in MAPEAMENTOS_ASSUMIDOS:
            # Pelo texto, não pela grafia: "Suco de limão" e "Suco de Limão
            # Taiti" são a mesma suposição e viram um aviso só.
            suposicao = MAPEAMENTOS_ASSUMIDOS[nome]
            avisos.append(f"Suposição: {suposicao}.")

        if tipos.get(insumo) == "producao":
            return insumo, item["quantidade"]

        if insumo in existentes:
            unidade = existentes[insumo]["unidade"]
        else:
            unidade = NOVOS.get(insumo, "l")
            if insumo not in NOVOS and INGREDIENTES.get(nome):
                avisos.append(
                    f"'{insumo}' não existe no estoque (esperava que a contagem o "
                    "tivesse criado); entrou como insumo novo."
                )
        insumos[insumo] = unidade
        tipos[insumo] = existentes.get(insumo, {}).get("tipo", "cru")
        return insumo, _converter(item, insumo, unidade, nome, receita, sem_conversao)

    producoes, fichas = [], []
    for receita in receitas:
        if chave(receita["aba"]) in AVISOS_DE_ABA:
            avisos.append(AVISOS_DE_ABA[chave(receita["aba"])])
        consumo = {}
        for item in receita["ingredientes"]:
            resolvido = resolver(item, receita)
            if resolvido is None:
                continue
            insumo, quantidade = resolvido
            consumo[insumo] = consumo.get(insumo, 0.0) + quantidade

        if e_preparo(receita):
            nome = PREPAROS[chave(receita["aba"])]
            soma = sum(
                i["quantidade"] for i in receita["ingredientes"]
                if chave(i["nome"]) not in SEM_INSUMO_UNICO
            )
            producoes.append({
                "nome": nome,
                "aba": receita["aba"],
                "unidade": insumos[nome],
                # O 2,33 da planilha é o valor do modelo, repetido em quase
                # toda aba. A soma dos ingredientes (água incluída) é um
                # ponto de partida melhor, e quem lança corrige o que rendeu.
                "rendimento": round(soma, 3),
                "itens": [
                    {"insumo": i, "quantidade": round(q, 6)}
                    for i, q in sorted(consumo.items())
                ],
            })
            continue

        prato = nome_do_drink(receita)
        porcoes = receita["porcoes"] or 1.0
        for insumo, quantidade in consumo.items():
            fichas.append({
                "prato": prato,
                "insumo": insumo,
                "quantidade": round(quantidade / porcoes, 6),
                "aba": receita["aba"],
            })

    if any(chave(r["aba"]) == "conde de campos" for r in receitas):
        avisos.append(
            "'Conde de Campos' é receita de lote (3 L de água, meio litro de "
            "cachaça), não uma dose: entrou como produção 'Conde de Campos (lote)'. "
            "Lançar o lote tira a cachaça e o gin do estoque; para a venda do "
            "copo descontar do lote, falta saber quantos ml vão num copo."
        )
    if producoes:
        avisos.append(
            "O rendimento das abas de preparo é 2,33 em todas (valor do modelo). "
            "Usei a soma dos ingredientes como rendimento de 1 receita; corrija "
            "o 'quanto rendeu' ao lançar a produção."
        )
    avisos.extend(_quantidades_fora_da_curva(fichas, insumos))
    avisos.extend(_bitter_demais(fichas))
    for (insumo, unidade), usos in sorted(sem_conversao.items()):
        lista = ", ".join(f"{aba} {q:g}" for aba, q in usos)
        motivo = (f"o nome não diz o volume de 1 {unidade}" if unidade in ("garrafa", "lata", "caixa")
                  else f"a ficha do bar pensa em kg ou litro e não se sabe quanto pesa 1 {unidade}")
        avisos.append(
            f"'{insumo}' é contado em {unidade} e {motivo}. Entrou o número da "
            f"planilha como {unidade}, em {len(usos)} drink(s): {lista}. Acerte na "
            "tela Ficha Técnica."
        )

    pratos = sorted({f["prato"] for f in fichas})
    return {
        "setor": SETOR,
        "insumos": dict(sorted(insumos.items())),
        "tipos": tipos,
        "insumos_novos": sorted(n for n in insumos if n not in existentes),
        "viram_producao": sorted(
            n for n, t in tipos.items()
            if t == "producao" and n in existentes and existentes[n]["tipo"] != "producao"
        ),
        "producoes": sorted(producoes, key=lambda p: p["nome"]),
        "pratos": pratos,
        "pratos_novos": sorted(p for p in pratos if p not in ja_tem_prato),
        "fichas": sorted(fichas, key=lambda f: (f["prato"], f["insumo"])),
        # A planilha do bar não cobre a cozinha: os insumos e pratos que ela
        # não cita não são órfãos, são de outro setor.
        "orfaos": [],
        "unidades_divergentes": [],
        "pratos_sem_ficha": [],
        "avisos": sorted(set(avisos)),
    }


def _converter(item, insumo, unidade, nome, receita, sem_conversao) -> float:
    """A quantidade da planilha (litro ou kg) na unidade do insumo no estoque.

    Sem como converter, devolve o número da planilha e anota em
    `sem_conversao` — não chuta peso de maço nem volume de garrafa.
    """
    quantidade = item["quantidade"]
    if unidade in ("l", "kg"):
        return quantidade
    if unidade in ("garrafa", "lata", "caixa"):
        volume = volume_do_nome(insumo)
        if volume:
            return quantidade / volume
    elif unidade == "un" and nome in FATORES_POR_UNIDADE:
        return quantidade * FATORES_POR_UNIDADE[nome]
    elif unidade == "un":
        return quantidade
    sem_conversao.setdefault((insumo, unidade), []).append((receita["aba"], quantidade))
    return quantidade


def _bitter_demais(fichas: list[dict]) -> list[str]:
    """Aviso para bitter (Angostura) em quantidade de dose, não de gotas."""
    exagerados = []
    for ficha in fichas:
        if not ficha["insumo"].startswith("Agostura"):
            continue
        litros = ficha["quantidade"] * (volume_do_nome(ficha["insumo"]) or 1)
        if litros > BITTER_MAXIMO_POR_DRINK:
            exagerados.append(f"{ficha['prato']} {litros * 1000:g} ml")
    if not exagerados:
        return []
    return [
        f"Angostura em {len(exagerados)} drink(s) vem em ml de dose, não em gotas "
        f"({', '.join(exagerados)}): cada drink tiraria 10% a 20% de uma garrafa. "
        "Confira na planilha e acerte na tela Ficha Técnica."
    ]


def _quantidades_fora_da_curva(fichas: list[dict], insumos: dict) -> list[str]:
    """Aviso para o drink que gasta muito mais de um insumo que os outros."""
    por_insumo = {}
    for ficha in fichas:
        por_insumo.setdefault(ficha["insumo"], []).append(ficha)
    avisos = []
    for insumo, usos in por_insumo.items():
        if len(usos) < 3:
            continue
        quantidades = sorted(u["quantidade"] for u in usos)
        mediana = quantidades[len(quantidades) // 2]
        for uso in usos:
            if uso["quantidade"] >= FOLGA_DA_MEDIANA * mediana:
                avisos.append(
                    f"'{uso['prato']}' gasta {uso['quantidade']:g} {insumos[insumo]} de "
                    f"'{insumo}', e os outros drinks gastam em torno de {mediana:g}. "
                    "Confira na planilha."
                )
    return avisos
