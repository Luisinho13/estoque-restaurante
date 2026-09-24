"""
ficha_import.py
Lê as planilhas de ficha técnica do restaurante (a de Prato Final e a de
Produção) e transforma cada aba em cadastro de insumo, prato e ficha técnica.

Três coisas nessas planilhas exigem cuidado, e é por causa delas que este
módulo existe em vez de um `pandas.read_excel` direto:

1. **A coluna "Unidade" não é confiável.** Aparece "Gr" em linhas cujo valor
   é 0,18 e cujo custo bate com o preço por quilo. A quantidade está sempre
   na unidade base (kg ou litro), qualquer que seja o rótulo escrito. Só
   tratamos como contagem de unidades os insumos marcados como "un" aqui no
   módulo (ovo, café, pão de hambúrguer) — e mesmo assim avisamos quando a
   planilha discorda.

2. **As fichas têm dois níveis.** Um prato consome "Molho queijo", que é uma
   receita da planilha de Produção, não algo que se compra. Cada receita de
   produção vira um item de estoque do tipo produção, com a própria ficha:
   a venda do prato desconta o molho, e o lançamento da produção do molho
   desconta o leite e o parmesão. (Até 23/09/2026 a receita era *explodida*
   no cru e a venda tirava o leite direto; o usuário pediu a separação.)

3. **Os nomes de ingrediente são texto livre.** São mais de 200 grafias, com
   erro de digitação ("katchup", "marshwmelow", "abobobrinha") e com o mesmo
   item escrito de duas formas ("Parmesão" e "Queijo Parmesão"). O dicionário
   NOMES_CANONICOS abaixo é a tradução curada dessas grafias para a lista de
   insumos genéricos que o restaurante controla.

Nada aqui escreve no banco sozinho: `montar_plano()` devolve o que *seria*
feito, a tela mostra, e só então `aplicar_plano()` grava.
"""

import unicodedata

import openpyxl

import crud
from database import get_connection

# ---------- Onde cada coisa mora na aba ----------
# O formulário é o mesmo nas duas planilhas, sempre nas mesmas células.
LINHA_NOME_TECNICO = 3
LINHA_NOME_VENDA = 4
LINHA_TIPO = 5
LINHA_PRIMEIRO_INGREDIENTE = 7
LINHA_ULTIMO_INGREDIENTE = 23
LINHA_RENDIMENTO = 25
LINHA_PORCOES = 29

COL_INGREDIENTE = 2       # B
COL_NOME = 4              # D — vale para nome técnico, nome de venda e tipo
COL_UNIDADE = 4           # D, dentro do bloco de ingredientes
COL_PESO_LIQUIDO = 5      # E
COL_PORCOES = 3           # C, na linha 29
COL_VALOR = 10            # J — rendimento e custo

# Fora desta faixa, o rendimento declarado não é redução de cozimento nem
# água absorvida, e sim engano de digitação. "Farofa" declara render 0,03 kg
# a partir de 1,53 kg; "Molho Mostarda", 26 kg a partir de 0,64 kg.
RENDIMENTO_MINIMO_PLAUSIVEL = 0.6
RENDIMENTO_MAXIMO_PLAUSIVEL = 1.3


def _limpa(valor) -> str | None:
    """Tira espaço sobrando e devolve None para célula vazia."""
    if valor is None:
        return None
    texto = " ".join(str(valor).split()).strip()
    return texto or None


def _numero(valor) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def chave(nome: str | None) -> str:
    """Forma de comparar nomes: sem acento, sem caixa, sem espaço duplicado.

    É só para *achar* o nome na tabela de sinônimos. O nome que vai para o
    banco é sempre o escrito por extenso, com acento.
    """
    texto = unicodedata.normalize("NFKD", (nome or "").lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.replace("-", " ").replace("/", " ").split())


# ---------- De grafia da planilha para insumo do sistema ----------
# Chave: o nome como sai de `chave()`. Valor: o insumo no sistema.
# Grafias diferentes do mesmo item apontam para o mesmo insumo; itens de
# preço bem diferente ficam separados de propósito (mignon x alcatra,
# camarão 11/15 x sete barbas, chocolate x chocolate branco).
NOMES_CANONICOS = {
    # verduras, legumes e frutas
    "abobobrinha": "Abobrinha",
    "abobrinha": "Abobrinha",
    "abobora cabotia": "Abóbora",
    "alface americana": "Alface",
    "alho": "Alho",
    "alho batido": "Alho",
    "alho descascado": "Alho",
    "alho frito": "Alho",
    "alho poro": "Alho-poró",
    "amora": "Amora",
    "banana": "Banana",
    "banana nanica": "Banana",
    "batata": "Batata",
    "batata asterix": "Batata",
    "batata canoa": "Batata",
    "batata noisete": "Batata",
    "fritas": "Batata",
    "fritas canoa": "Batata",
    "pure de batata": "Batata",
    "batata palha": "Batata palha",
    "chips de batata": "Batata palha",
    "beringela": "Berinjela",
    "brocolis": "Brócolis",
    "cebola": "Cebola",
    "cebola perola": "Cebola",
    "cebola roxa": "Cebola",
    "cebolinha": "Cebolinha",
    "cenoura": "Cenoura",
    "cogumelo": "Cogumelo Paris",
    "cogumelo paris": "Cogumelo Paris",
    "cogumelo shimeji": "Cogumelo shimeji",
    "cogumelo shitake": "Cogumelo shitake",
    "framboesa": "Framboesa",
    "limao": "Limão",
    "limao taithi": "Limão",
    "mandioquinha": "Mandioquinha",
    "pure de mandiqouinha": "Mandioquinha",
    "morango": "Morango",
    "palmito": "Palmito",
    "pimenta biquinho": "Pimenta biquinho",
    "pimenta de cheiro": "Pimenta de cheiro",
    "pimentao amarelo": "Pimentão",
    "pimentao verde": "Pimentão",
    "pimentao vermelho": "Pimentão",
    "salsao": "Salsão",
    "tomate": "Tomate",
    "tomate italiano": "Tomate",
    "tomate salada": "Tomate",
    "tomate cereja": "Tomate cereja",
    "tomate cereja assado": "Tomate cereja",
    "uva": "Uva",
    "uva verde": "Uva",
    # carnes e pescados
    "alcaparraz": "Alcaparra",
    "apara de carnes": "Apara de carne",
    "bacon": "Bacon",
    "barriga de porco": "Barriga de porco",
    "bolinho de camarao": "Bolinho de camarão",
    "bombom de alcatra": "Alcatra",
    "croqueta de costela": "Croqueta de costela",
    "file aperitivo": "Mignon",
    "linguica campeira": "Linguiça campeira",
    "linguica provolone": "Linguiça provolone",
    "mini hamburguer": "Hambúrguer",
    "tomahawk": "Tomahawk",
    "miolo alcatra": "Alcatra",
    "miolo de alcatra": "Alcatra",
    "calabresa": "Linguiça calabresa",
    "camarao 11 15": "Camarão",
    "camarao 7 barbas": "Camarão sete barbas",
    "carne moida": "Carne moída",
    "carne seca": "Carne seca",
    "chorizo": "Chorizo",
    "costela": "Costela",
    "file de frango": "Frango",
    "peito de frango": "Frango",
    "file mignon": "Mignon",
    "file mignon 4 5": "Mignon",
    "linguica toscana": "Linguiça toscana",
    "lombo": "Lombo",
    "mocoto": "Mocotó",
    "osso": "Osso",
    # Panceta e barriga de porco são o mesmo corte com dois nomes; as duas
    # abas de "Barriga de porco" da planilha usam um cada.
    "panceta": "Barriga de porco",
    "porterhouse": "Porterhouse",
    "presunto": "Presunto",
    "presunto parma": "Presunto parma",
    "salmao": "Salmão",
    "truta": "Truta",
    # laticínios e ovos
    "brie": "Queijo brie",
    "queijo brie": "Queijo brie",
    "burrata": "Burrata",
    "burrata de bufala": "Burrata",
    "chantily spray": "Chantilly",
    "cheddar": "Queijo cheddar",
    "creme de leite": "Creme de leite",
    "doce de leite": "Doce de leite",
    "leite": "Leite",
    "leite integral": "Leite",
    "leite condensado": "Leite condensado",
    "leite de coco": "Leite de coco",
    "leite em po": "Leite em pó",
    "manteiga": "Manteiga",
    "manteiga de limao": "Manteiga",
    "mussarela": "Queijo mussarela",
    "queijo mussarela": "Queijo mussarela",
    "mussarela de bufala": "Mussarela de búfala",
    "ovo": "Ovo",
    "ovos": "Ovo",
    "parmesao": "Queijo parmesão",
    "queijo parmesao": "Queijo parmesão",
    "queijo camembert": "Queijo camembert",
    "queijo minas padrao": "Queijo minas",
    "queijo tipo reino": "Queijo do reino",
    "requeijao": "Requeijão",
    # secos, massas e panificação
    "acucar": "Açúcar",
    "arroz": "Arroz",
    "arroz branco": "Arroz",
    "arroz arborio": "Arroz arbóreo",
    "arroz basmati": "Arroz basmati",
    "biscoito champnhe": "Bolacha champanhe",
    "bolacha champanhe": "Bolacha champanhe",
    "biscoito maisena": "Bolacha maisena",
    "bolacha maisena": "Bolacha maisena",
    "castanha de caju": "Castanha de caju",
    "coco ralado": "Coco ralado",
    "crispi de arroz": "Crispy de arroz",
    "espaguete": "Massa",
    "macarrao chiferri": "Massa",
    "pappardelle": "Massa",
    "rigatoni": "Massa",
    "massa de lasanha": "Massa de lasanha",
    "massa folhada": "Massa folhada",
    "farinha de trigo": "Farinha de trigo",
    "farinha panco": "Farinha panko",
    "farinha panko": "Farinha panko",
    "feijao carioca": "Feijão",
    "maisena": "Amido de milho",
    "mini baguete": "Mini baguete",
    "pao": "Pão",
    "pao filao": "Pão",
    "torrada de pao filao": "Pão",
    "pao bola": "Pão de hambúrguer",
    "mini pao brioche": "Pão de hambúrguer",
    "tapioca granulada": "Tapioca granulada",
    # temperos e condimentos
    "agua": "Água",
    "alecrim": "Alecrim",
    "azeite": "Azeite",
    "azeite trufado": "Azeite trufado",
    "azeitonas": "Azeitona",
    "canela em pau": "Canela",
    "canela em po": "Canela",
    "cardamomo": "Cardamomo",
    "cravo da india": "Cravo",
    "geleia de damasco": "Geleia de damasco",
    "geleia de pimenta": "Geleia de pimenta",
    "katchup": "Ketchup",
    "ketchup": "Ketchup",
    "louro": "Louro",
    "manjericao": "Manjericão",
    "mostarda": "Mostarda",
    "mostarda amarela": "Mostarda",
    "mostarda djon": "Mostarda",
    "nos moscada": "Noz-moscada",
    "oleo": "Óleo",
    "oleo soja": "Óleo",
    "pimenta do reino": "Pimenta-do-reino",
    "pimenta em grao": "Pimenta-do-reino",
    "sal": "Sal",
    "sal refinado": "Sal",
    "salsinha": "Salsinha",
    "semente de coentro": "Coentro em semente",
    "semente de cumaru": "Cumaru",
    "tabasco": "Molho de pimenta",
    "tomilho": "Tomilho",
    "vinagre": "Vinagre",
    # doces e sobremesas
    "cacau": "Cacau em pó",
    "chocolate 30%": "Chocolate",
    "chocolate 70%": "Chocolate",
    "chocolate de fondue": "Chocolate",
    "chocolate meio amargo": "Chocolate",
    "chocolate para decorar": "Chocolate",
    "chocolate branco": "Chocolate branco",
    "fudge": "Fudge",
    "marshmallow": "Marshmallow",
    "marshwmelow": "Marshmallow",
    "pacoca": "Paçoca",
    "bola de sorvete": "Sorvete",
    "sorvete": "Sorvete",
    "sorvete de pistache": "Sorvete",
    # bebidas usadas na cozinha
    "cachaca": "Cachaça",
    "cachaca 51": "Cachaça",
    "cafe": "Café",
    "domeq": "Conhaque",
    "polpa de maracuja": "Polpa de maracujá",
    "suco de laranja": "Suco de laranja",
    "vinho branco chalise": "Vinho branco",
    "vinho tinto": "Vinho tinto",
    # preparações que a planilha cita mas não tem ficha própria: entram como
    # insumo para não sumir do cálculo, e saem listadas em `avisos`.
    "base fondue": "Preparo de fondue",
    "preparo de fondue": "Preparo de fondue",
    "conchiglione recheado": "Conchiglione recheado",
    "molho roti": "Molho roti",
}

# Quantidade da planilha que está errada e que a cozinha confirmou qual é
# a certa. Chave: (prato, insumo), comparados por `chave()`. Valor: quanto
# 1 porção consome, na unidade do insumo. A planilha continua sendo a fonte
# da verdade para todo o resto; isto só impede que reimportar desfaça uma
# correção já confirmada.
QUANTIDADES_CORRIGIDAS = {
    # A planilha diz 1 (uma unidade, ao que parece), lido como 1 kg. O
    # usuário confirmou em 23/09/2026: a porção leva 300 g de croqueta.
    ("croqueta de costela", "croqueta de costela"): 0.3,
}

# Insumo que se conta por unidade, não por peso. Todo o resto é kg, menos
# o que estiver em EM_LITRO.
EM_UNIDADE = {"Ovo", "Café", "Pão de hambúrguer", "Linguiça provolone"}
EM_LITRO = {
    "Água", "Azeite", "Azeite trufado", "Óleo", "Leite", "Leite de coco",
    "Vinho branco", "Vinho tinto", "Cachaça", "Conhaque", "Vinagre",
    "Molho de pimenta", "Suco de laranja",
}

# Ingredientes que são, na verdade, uma receita da planilha de Produção
# escrita com outro nome. Sem isso o "Molho queijo" do prato não acha a aba
# "Molho de Queijo" e viraria um insumo que ninguém compra.
APELIDOS_DE_RECEITA = {
    "molho ao sugo": "Molho sugo",
    # "Molho de tomate" é o nome técnico escrito dentro da aba "Molho sugo"
    # (e, por erro de cópia, também dentro de "Molho Mostarda").
    "molho de tomate": "Molho sugo",
    "molho de mostarda": "Molho Mostarda",
    "molho queijo": "Molho de Queijo",
    "molho pesto": "Pesto",
    "molho bechamel": "Bechamel",
    "fondue de queijo": "Queijo Fonfue",
    "dadinho tapioca": "Dadinho de tapioca",
    "risoto": "Base de risoto",
    "cocada": "Cocada Cremosa",
    # As duas fichas de parmegiana da planilha de Produção têm o mesmo nome
    # interno ("Parmeggiana de Carne"), erro de cópia. Aqui elas são achadas
    # pelo nome da aba, que é o único campo que as distingue.
    "parmeggiana carne": "P Parmeggiana Carne",
    "parmeggiana frango": "P Parmeggiana Frango",
    "parmegiana": "P Parmeggiana Carne",
    # Os quatro abaixo são palpite meu: o nome citado não existe como aba,
    # mas só há um candidato razoável. Saem em `avisos` para conferência.
    "aioli": "Aioli de Alho",
    "aioli de pimenta de limao": "Aioli de Limao",
    "aioli de pimenta do reino": "Aioli de Pimenta de cheiro",
    "molho de alho": "Aioli de Alho",
    "molho de frutas vermelhas": "Geleia Frutas Vermelha",
}

# Ingrediente que a receita cita mas que não é estoque: água da torneira
# entraria no painel com saldo negativo para sempre.
SEM_ESTOQUE = {"agua"}

# Nome de cada produção no sistema, pela aba da planilha de Produção
# (comparada por `chave()`). O campo "nome técnico" das abas não serve: foi
# copiado de uma aba para a outra, e "Molho Mostarda" se chama "Molho de
# tomate" por dentro. Onde a contagem de 23/09 já criou o item, o nome é o
# mesmo dela, para a contagem cair direto na produção.
NOMES_DE_PRODUCAO = {
    "molho mostarda": "Molho de mostarda",
    "molho sugo": "Molho ao sugo",                  # já existe pela contagem
    "molho madeira": "Molho madeira",
    "molho de strogonoff": "Molho de strogonoff",
    "bechamel": "Molho bechamel",
    "pesto": "Pesto",                               # já existe pela contagem
    "molho maracuja": "Molho de maracujá",          # já existe pela contagem
    "molho de queijo": "Molho de queijo",
    "base de risoto": "Base de risoto",
    "p parmeggiana carne": "Parmegiana de carne empanada",
    "p parmeggiana frango": "Parmegiana de frango empanada",
    "geleia frutas vermelha": "Geleia de frutas vermelhas",
    "molho cheddar": "Molho cheddar",
    "petit four": "Petit four",
    "molho ceaser": "Molho caesar",
    "molho steak tartare": "Molho steak tartare",
    "mix de cogumelos": "Mix de cogumelos",
    "caldo de legumes": "Caldo de legumes",
    "vinagrete": "Vinagrete",
    "brownie": "Brownie",
    "cocada cremosa": "Cocada cremosa",
    "aioli de limao": "Aioli de limão",
    "aioli de pimenta de cheiro": "Aioli de pimenta de cheiro",
    "aioli de alho": "Aioli de alho",
    "queijo fonfue": "Fondue de queijo",
    "fondue de chocolate": "Fondue de chocolate",
    "fondue doce de leite": "Fondue de doce de leite",
    "brigadeiro com pacoquinha": "Brigadeiro com paçoquinha",
    "mousse de limao crocante": "Mousse de limão crocante",
    "frango gourmet": "Frango gourmet",
    # A ficha leva carne seca: é o "com carne seca" da contagem.
    "bolinho de abobora": "Bolinho de abóbora com carne seca",
    "dadinho de tapioca": "Dadinho de tapioca",     # já existe pela contagem
    "farofa": "Farofa",
}

# Produções que o prato cita por peça, não por peso ("1 und" de
# parmegiana, "1 unidade" de dadinho). Nelas o rendimento de 1 receita é o
# número de porções da aba, e não o peso.
PRODUCOES_EM_PORCAO = {
    "p parmeggiana carne", "p parmeggiana frango",
    "dadinho de tapioca", "bolinho de abobora",
}

APELIDOS_INCERTOS = {
    "aioli", "aioli de pimenta de limao", "aioli de pimenta do reino",
    "molho de alho", "molho de frutas vermelhas", "risoto", "parmegiana",
}

# Traduções em que eu troquei o nome da preparação pelo insumo cru que ela é
# na prática, porque é esse que entra pela nota fiscal. Não é leitura do que
# está escrito, é interpretação — então cada uma vira aviso na tela.
MAPEAMENTOS_ASSUMIDOS = {
    "bombom de alcatra": "o bombom é alcatra porcionada",
    "file aperitivo": "o filé aperitivo é mignon em cubos",
    "pure de batata": "o purê é batata",
    "pure de mandiqouinha": "o purê é mandioquinha",
    "fritas": "fritas são batata",
    "fritas canoa": "fritas canoa são batata",
    "batata canoa": "batata canoa é batata",
    "batata noisete": "batata noisete é batata",
}


# ---------- De aba da planilha para prato do sistema ----------
# Os pratos do sistema têm o nome exato da Zig, porque é por ele que a
# importação de vendas acha o prato. Na planilha eles têm nome de cozinha.
# Sem esta tabela, "MIX de churrasco" viraria um prato novo e o "Mix Churrasco P"
# que recebe as vendas continuaria sem ficha técnica.
# Uma aba pode alimentar mais de um prato: as porções P e normal do bombom
# são a mesma receita no cardápio.
DE_PARA_PADRAO = {
    "banofee": "Banoffe",
    "Batata Canoa c creme de cheddar": "Batata Canoa",
    "Bombom de alcatra e batata": [
        "Bombom de Alcatra Arroz e Batata",
        "Bombom de Alcatra Arroz e Batata P*",
    ],
    "bombom de alcatra trufado": "Bombom de Alcatra com Trufas",
    "Brusqueta de queijo brie": "Brusqueta",
    "Caldinho de Batata": "Caldinho de Batata",
    "Chorizo com Pappardelle": "Chorizo Grelhado c/ Parpadelle ao Pesto P",
    "Conchiglione 4 queijos": "Conchiglione Recheado",
    "Filé aperitivo": "Filé Aperitivo",
    "Fondue Chocolate": "Fondue Chocolate (Sequência / Abstrato)",
    "Fondue Master": "SEQUENCIA DE FONDUE 169,90",
    "mini hamburguer": "Mini Burguer",
    "MIX de churrasco": "Mix Churrasco P",
    "Tabua de Frios": "Tábua de Frios",
    "Truta com Risoto de Limao": "Truta com Risoto 3 Limões",
}


def unidade_do_insumo(nome: str) -> str:
    if nome in EM_UNIDADE:
        return "un"
    if nome in EM_LITRO:
        return "l"
    return "kg"


# ---------- Leitura das abas ----------

def ler_planilha(arquivo) -> list[dict]:
    """Devolve uma receita por aba preenchida da planilha.

    `arquivo` pode ser um caminho ou o buffer que o Streamlit entrega no
    upload — openpyxl aceita os dois.
    """
    wb = openpyxl.load_workbook(arquivo, read_only=True, data_only=True)
    receitas = []
    for ws in wb.worksheets:
        receita = _ler_aba(ws)
        if receita:
            receitas.append(receita)
    wb.close()
    return receitas


def _ler_aba(ws) -> dict | None:
    linhas = list(ws.iter_rows(min_row=1, max_row=LINHA_PORCOES,
                               max_col=COL_VALOR, values_only=True))

    def celula(linha, coluna):
        if linha - 1 >= len(linhas):
            return None
        conteudo = linhas[linha - 1]
        return conteudo[coluna - 1] if coluna - 1 < len(conteudo) else None

    nome = _limpa(celula(LINHA_NOME_TECNICO, COL_NOME))
    nome_venda = _limpa(celula(LINHA_NOME_VENDA, COL_NOME))

    ingredientes = []
    for linha in range(LINHA_PRIMEIRO_INGREDIENTE, LINHA_ULTIMO_INGREDIENTE + 1):
        item = _limpa(celula(linha, COL_INGREDIENTE))
        if not item:
            continue
        # A legenda "Unidade: Kg=quilo / Lt=litro..." fecha o bloco.
        if item.lower().startswith("unidade:"):
            break
        quantidade = _numero(celula(linha, COL_PESO_LIQUIDO))
        if quantidade is None or quantidade <= 0:
            continue
        ingredientes.append({
            "nome": item,
            "unidade_declarada": _limpa(celula(linha, COL_UNIDADE)),
            "quantidade": quantidade,
        })

    if not ingredientes:
        return None

    return {
        "aba": ws.title.strip(),
        "nome": nome or nome_venda or ws.title.strip(),
        "nome_venda": nome_venda or nome or ws.title.strip(),
        "tipo": _limpa(celula(LINHA_TIPO, COL_NOME)),
        "rendimento": _numero(celula(LINHA_RENDIMENTO, COL_VALOR)),
        "porcoes": _numero(celula(LINHA_PORCOES, COL_PORCOES)) or 1.0,
        "ingredientes": ingredientes,
    }


# ---------- Montagem do plano ----------

def _e_producao(receita: dict) -> bool:
    return (receita["tipo"] or "").lower().startswith("produ")


def nome_da_producao(receita: dict) -> str:
    """Nome do item produzido no sistema, a partir da aba da planilha."""
    nome = NOMES_DE_PRODUCAO.get(chave(receita["aba"]))
    if nome:
        return nome
    aba = receita["aba"].strip()
    return aba[:1].upper() + aba[1:]


def montar_plano(receitas_prato: list[dict], receitas_producao: list[dict],
                 de_para_pratos: dict[str, str] | None = None) -> dict:
    """Transforma as receitas lidas no que precisa ser gravado.

    Cada aba de produção vira um item de estoque do tipo produção, com a
    própria ficha (o que 1 receita gasta) e o rendimento. Cada aba de prato
    vira a ficha do prato, citando a produção pelo nome quando a receita
    leva um molho ou uma base — sem abrir nos ingredientes.

    `de_para_pratos` liga o nome da aba ao nome do prato que já existe no
    sistema (que é o nome da Zig, e é por ele que a venda encontra o prato).
    Aba sem correspondência vira prato novo com o nome da própria ficha.
    """
    de_para_pratos = de_para_pratos or {}
    avisos = []

    conn = get_connection()
    unidade_atual = {
        d["nome"]: d["unidade_medida"]
        for d in conn.execute("SELECT nome, unidade_medida FROM insumos").fetchall()
    }
    tipo_atual = {
        d["nome"]: d["tipo"]
        for d in conn.execute("SELECT nome, tipo FROM insumos").fetchall()
    }
    ja_tem_prato = {d["nome"] for d in conn.execute("SELECT nome FROM pratos").fetchall()}
    # Insumo que a contagem conta tem a unidade que o fator da linha da
    # contagem pressupõe. Trocar a unidade dele aqui estragaria a contagem.
    contados = {
        d["nome"] for d in conn.execute(
            """SELECT DISTINCT i.nome FROM itens_contagem ic
               JOIN insumos i ON i.id = ic.insumo_id"""
        ).fetchall()
    }
    conn.close()

    # O que é produção: toda aba da planilha de Produção e as abas da de
    # pratos marcadas como Produção que você não ligou a um prato vendido.
    # Aba de prato comum não entra de propósito: várias delas são só o
    # "extra" do cardápio e citam o próprio nome como ingrediente ("Bombom
    # de Alcatra" consome "Bombom de Alcatra" 0,18 kg).
    receitas_de_producao = list(receitas_producao)
    for receita in receitas_prato:
        if _e_producao(receita) and not de_para_pratos.get(receita["aba"]):
            receitas_de_producao.append(receita)
            avisos.append(
                f"A aba '{receita['aba']}' está marcada como Produção na planilha "
                "de pratos, então virou item de produção, não um prato vendido."
            )
    catalogo = _indexar(receitas_de_producao)

    # Nome de cada produção no sistema. Duas abas com o mesmo nome final
    # gravariam uma por cima da outra; vale a primeira.
    nomes_producao, usados = {}, {}
    for receita in receitas_de_producao:
        nome = nome_da_producao(receita)
        if nome in usados:
            avisos.append(
                f"As abas de produção '{usados[nome]}' e '{receita['aba']}' viram o "
                f"mesmo item ('{nome}'). Usei a primeira."
            )
            continue
        usados[nome] = receita["aba"]
        nomes_producao[id(receita)] = nome

    insumos = {}    # nome do insumo -> unidade
    tipos = {}      # nome do insumo -> 'cru' ou 'producao'
    producoes = []

    # Primeiro as produções: a unidade delas precisa estar decidida antes
    # de conferir como os pratos as citam.
    for receita in receitas_de_producao:
        nome = nomes_producao.get(id(receita))
        if nome is None:
            continue
        em_porcao = chave(receita["aba"]) in PRODUCOES_EM_PORCAO
        unidade_planilha = "un" if em_porcao else "kg"
        # Item que já existe (a contagem de 23/09 criou vários molhos) fica
        # na unidade em que é contado. Trocar aqui estragaria o fator da
        # linha da contagem, que foi pensado nessa unidade.
        unidade = unidade_atual.get(nome, unidade_planilha)
        if unidade != unidade_planilha:
            avisos.append(
                f"'{nome}' já existe no sistema em '{unidade}' (é assim que a "
                f"contagem conta), e a planilha pensa em '{unidade_planilha}'. "
                f"Mantive '{unidade}': confira se 1 {unidade} equivale a 1 porção "
                "da ficha."
            )
        insumos[nome] = unidade
        tipos[nome] = "producao"
        producoes.append({
            "nome": nome,
            "aba": receita["aba"],
            "unidade": unidade,
            "rendimento": (receita["porcoes"] or 1.0) if em_porcao
            else _rendimento_confiavel(receita, avisos),
            "receita": receita,
        })

    def resolver(item, receita):
        """Insumo do sistema que a linha da ficha cita, ou None para pular."""
        nome = chave(item["nome"])
        if nome in SEM_ESTOQUE:
            avisos.append(
                f"'{item['nome']}' ficou fora das fichas: não é item de estoque."
            )
            return None
        alvo = APELIDOS_DE_RECEITA.get(nome)
        sub = catalogo.get(chave(alvo)) if alvo else catalogo.get(nome)

        if sub is not None and sub is not receita and id(sub) in nomes_producao:
            if nome in APELIDOS_INCERTOS:
                avisos.append(
                    f"'{item['nome']}' não existe como aba; assumi a ficha "
                    f"'{sub['aba']}'. Confirme se é essa mesma."
                )
            producao = nomes_producao[id(sub)]
            _conferir_unidade(item, producao, insumos[producao], receita, avisos)
            return producao

        if sub is receita:
            avisos.append(
                f"A ficha '{receita['aba']}' cita a si mesma como ingrediente. "
                "Tratei essa linha como insumo comprado."
            )

        insumo = NOMES_CANONICOS.get(nome)
        if insumo is None:
            insumo = item["nome"].strip().capitalize()
            avisos.append(
                f"'{item['nome']}' não está na lista de insumos conhecidos; "
                f"entrou como '{insumo}'."
            )
        elif nome in MAPEAMENTOS_ASSUMIDOS:
            avisos.append(
                f"'{item['nome']}' foi lançado como '{insumo}' — "
                f"{MAPEAMENTOS_ASSUMIDOS[nome]}."
            )
        if tipos.get(insumo) == "producao":
            return insumo

        declarada = (item["unidade_declarada"] or "").lower()
        if declarada.startswith("un") and unidade_do_insumo(insumo) != "un":
            avisos.append(
                f"'{item['nome']}' está marcado como unidade na planilha, mas "
                f"'{insumo}' é controlado em {unidade_do_insumo(insumo)}. "
                "Confira a quantidade."
            )
        insumos[insumo] = unidade_do_insumo(insumo)
        tipos[insumo] = "cru"
        return insumo

    for producao in producoes:
        itens = {}
        for item in producao["receita"]["ingredientes"]:
            insumo = resolver(item, producao["receita"])
            if insumo is None:
                continue
            itens[insumo] = itens.get(insumo, 0.0) + item["quantidade"]
        producao["itens"] = [
            {"insumo": insumo, "quantidade": round(quantidade, 6)}
            for insumo, quantidade in sorted(itens.items())
        ]
        del producao["receita"]

    fichas = []       # (prato, insumo, quantidade por porção)
    ja_montados = {}  # chave do prato -> aba que o montou, para pegar aba repetida

    for receita in receitas_prato:
        escolhidos = de_para_pratos.get(receita["aba"])
        if isinstance(escolhidos, str):
            escolhidos = [escolhidos]
        if not escolhidos and _e_producao(receita):
            continue   # já virou produção lá em cima

        porcoes = receita["porcoes"] or 1.0
        consumo = {}
        for item in receita["ingredientes"]:
            insumo = resolver(item, receita)
            if insumo is None:
                continue
            consumo[insumo] = consumo.get(insumo, 0.0) + item["quantidade"]

        for prato in escolhidos or [receita["nome_venda"]]:
            # Duas abas descrevem "Barriga de porco" de jeitos diferentes. Vale
            # a primeira: sem isso as duas gravariam no mesmo prato e a segunda
            # apagaria a ficha da primeira sem ninguém ver.
            if chave(prato) in ja_montados:
                avisos.append(
                    f"As abas '{ja_montados[chave(prato)]}' e '{receita['aba']}' viram "
                    f"o mesmo prato ('{prato}'). Usei a primeira e ignorei a segunda."
                )
                continue
            ja_montados[chave(prato)] = receita["aba"]

            for insumo, quantidade in consumo.items():
                por_porcao = round(quantidade / porcoes, 6)
                corrigida = QUANTIDADES_CORRIGIDAS.get((chave(prato), chave(insumo)))
                if corrigida is not None and corrigida != por_porcao:
                    avisos.append(
                        f"'{prato}' consome {por_porcao:g} de '{insumo}' na planilha; "
                        f"usei {corrigida:g}, a quantidade confirmada pela cozinha."
                    )
                    por_porcao = corrigida
                fichas.append({
                    "prato": prato,
                    "insumo": insumo,
                    "quantidade": por_porcao,
                    "aba": receita["aba"],
                })

    # Insumo cru que já existe, mas contado numa unidade diferente da que a
    # ficha usa. Fica invisível e estraga a conta: a ficha gasta 0,06 kg de
    # pão e o painel mostra o saldo em unidades. Produção não entra aqui:
    # ela ficou na unidade que já tinha, com aviso.
    divergentes = []
    for nome, unidade in insumos.items():
        if tipos[nome] != "cru" or nome not in unidade_atual or unidade_atual[nome] == unidade:
            continue
        if nome in contados:
            avisos.append(
                f"'{nome}' é contado em {unidade_atual[nome]} na contagem, e a ficha "
                f"usa {unidade}. Ficou em {unidade_atual[nome]}: acerte a quantidade "
                "na tela Ficha Técnica para ela ficar nessa unidade."
            )
            continue
        divergentes.append({"insumo": nome, "atual": unidade_atual[nome], "planilha": unidade})

    pratos = sorted({f["prato"] for f in fichas})
    usados_no_plano = set(insumos)

    return {
        "insumos": dict(sorted(insumos.items())),
        "tipos": tipos,
        "insumos_novos": sorted(n for n in insumos if n not in unidade_atual),
        # Já existiam como cru (a contagem criou vários molhos) e passam a
        # ser produção, com ficha.
        "viram_producao": sorted(
            n for n, t in tipos.items()
            if t == "producao" and n in tipo_atual and tipo_atual[n] != "producao"
        ),
        "producoes": sorted(producoes, key=lambda p: p["nome"]),
        "pratos": pratos,
        "pratos_novos": sorted(p for p in pratos if p not in ja_tem_prato),
        "fichas": sorted(fichas, key=lambda f: (f["prato"], f["insumo"])),
        "orfaos": sorted(n for n in unidade_atual if n not in usados_no_plano),
        "unidades_divergentes": sorted(divergentes, key=lambda d: d["insumo"]),
        # Prato que já recebe venda e que a planilha não cobre: continua sem
        # ficha, então a venda dele não desconta nada do estoque.
        "pratos_sem_ficha": sorted(p for p in ja_tem_prato if p not in set(pratos)),
        "avisos": sorted(set(avisos)),
    }


def _conferir_unidade(item: dict, producao: str, unidade: str,
                      receita: dict, avisos: list):
    """Avisa quando a ficha cita a produção numa unidade que não é a dela.

    A planilha escreve "1 und" de dadinho e "0,08 Gr" de dadinho em fichas
    diferentes. Uma das duas está errada, e a conta não tem como saber qual.
    """
    declarada = (item["unidade_declarada"] or "").lower()
    por_porcao = unidade in ("un", "pacote")
    citada_por_porcao = declarada.startswith("un")
    if por_porcao != citada_por_porcao:
        avisos.append(
            f"'{receita['aba']}' usa {item['quantidade']:g} {item['unidade_declarada'] or ''} "
            f"de '{producao}', que é controlado em {unidade}. Confira a quantidade."
        )


def _indexar(receitas: list[dict]) -> dict[str, dict]:
    """Índice das receitas por todos os nomes pelos quais elas podem ser citadas."""
    indice = {}
    for receita in receitas:
        for nome in (receita["aba"], receita["nome"], receita["nome_venda"]):
            if nome:
                indice.setdefault(chave(nome), receita)
    return indice


def _rendimento_confiavel(receita: dict, avisos: list) -> float:
    """Rendimento de 1 receita, com defesa contra o campo preenchido errado.

    O rendimento não mexe no que a produção desconta (isso é a ficha ×
    receitas); ele só preenche o "quanto rendeu" na tela de produção. Mesmo
    assim, um número absurdo ali seria digitado adiante sem ninguém ver.
    Quando o declarado foge muito da soma dos ingredientes — "Farofa"
    rende 0,03 kg de 1,53 kg, "Molho Mostarda" rende 26 kg de 0,64 kg —
    vale a soma, e o caso é reportado.
    """
    soma = sum(i["quantidade"] for i in receita["ingredientes"])
    rendimento = receita["rendimento"] or 0
    if soma * RENDIMENTO_MINIMO_PLAUSIVEL <= rendimento <= soma * RENDIMENTO_MAXIMO_PLAUSIVEL:
        return rendimento
    avisos.append(
        f"Rendimento de '{receita['aba']}' está em {rendimento or 0:g} kg mas os "
        f"ingredientes somam {soma:g} kg. Usei a soma como rendimento de 1 receita — "
        "confira o campo na planilha ou corrija na tela Ficha Técnica."
    )
    return round(soma, 3)


# ---------- Gravação ----------

def aplicar_plano(plano: dict, substituir_fichas: bool = True,
                  corrigir_unidades: bool = True) -> dict:
    """Grava o plano no banco, tudo ou nada. Devolve a contagem do que foi feito.

    Com `substituir_fichas`, a ficha de cada prato e de cada produção da
    planilha é trocada inteira — inclusive o que tiver sido editado na tela
    Ficha Técnica. Sem isso, um insumo que saiu da receita continuaria
    sendo descontado para sempre.
    """
    conn = get_connection()
    try:
        rendimento = {p["nome"]: p["rendimento"] for p in plano["producoes"]}
        for nome in plano["insumos_novos"]:
            tipo = plano["tipos"].get(nome, "cru")
            conn.execute(
                """INSERT INTO insumos (nome, unidade_medida, estoque_minimo, tipo, rendimento)
                   VALUES (?, ?, 0, ?, ?)""",
                (nome, plano["insumos"][nome], tipo, rendimento.get(nome)),
            )

        if corrigir_unidades:
            for divergencia in plano.get("unidades_divergentes", []):
                conn.execute(
                    "UPDATE insumos SET unidade_medida = ? WHERE nome = ?",
                    (divergencia["planilha"], divergencia["insumo"]),
                )

        for producao in plano["producoes"]:
            conn.execute(
                "UPDATE insumos SET tipo = 'producao', rendimento = ? WHERE nome = ?",
                (producao["rendimento"], producao["nome"]),
            )

        for nome in plano["pratos_novos"]:
            conn.execute("INSERT INTO pratos (nome) VALUES (?)", (nome,))

        ids_insumo = {
            d["nome"]: d["id"] for d in conn.execute("SELECT id, nome FROM insumos").fetchall()
        }
        ids_prato = {
            d["nome"]: d["id"] for d in conn.execute("SELECT id, nome FROM pratos").fetchall()
        }

        if substituir_fichas:
            for prato in sorted({f["prato"] for f in plano["fichas"]}):
                conn.execute("DELETE FROM ficha_tecnica WHERE prato_id = ?", (ids_prato[prato],))
            for producao in plano["producoes"]:
                conn.execute("DELETE FROM ficha_producao WHERE producao_id = ?",
                             (ids_insumo[producao["nome"]],))

        for ficha in plano["fichas"]:
            conn.execute(
                """INSERT INTO ficha_tecnica (prato_id, insumo_id, quantidade_por_prato)
                   VALUES (?, ?, ?)
                   ON CONFLICT(prato_id, insumo_id)
                   DO UPDATE SET quantidade_por_prato = excluded.quantidade_por_prato""",
                (ids_prato[ficha["prato"]], ids_insumo[ficha["insumo"]], ficha["quantidade"]),
            )
        linhas_producao = 0
        for producao in plano["producoes"]:
            for item in producao["itens"]:
                conn.execute(
                    """INSERT INTO ficha_producao (producao_id, insumo_id, quantidade_por_receita)
                       VALUES (?, ?, ?)
                       ON CONFLICT(producao_id, insumo_id)
                       DO UPDATE SET quantidade_por_receita = excluded.quantidade_por_receita""",
                    (ids_insumo[producao["nome"]], ids_insumo[item["insumo"]],
                     item["quantidade"]),
                )
                linhas_producao += 1
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()

    return {
        "insumos": len(plano["insumos_novos"]),
        "pratos": len(plano["pratos_novos"]),
        "fichas": len(plano["fichas"]),
        "producoes": len(plano["producoes"]),
        "linhas_producao": linhas_producao,
        "unidades": len(plano.get("unidades_divergentes", [])) if corrigir_unidades else 0,
    }
