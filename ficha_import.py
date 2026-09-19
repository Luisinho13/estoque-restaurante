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
   receita da planilha de Produção, não algo que se compra. Como o banco é
   plano (prato → insumo), a gente *explode* a subreceita: a quantidade usada
   é dividida pelo rendimento do lote e multiplicada pelos ingredientes dele.
   Assim o consumo cai em cima do que realmente entra pela nota fiscal.

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

# Abaixo disso o rendimento declarado é menor que a soma dos ingredientes a
# ponto de não ser redução de cozimento, e sim engano de digitação. "Farofa"
# declara render 0,03 kg a partir de 1,53 kg. Explodir por esse número
# multiplicaria o consumo por 50.
RENDIMENTO_MINIMO_PLAUSIVEL = 0.6


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

def montar_plano(receitas_prato: list[dict], receitas_producao: list[dict],
                 de_para_pratos: dict[str, str] | None = None) -> dict:
    """Transforma as receitas lidas no que precisa ser gravado.

    `de_para_pratos` liga o nome da aba ao nome do prato que já existe no
    sistema (que é o nome da Zig, e é por ele que a venda encontra o prato).
    Aba sem correspondência vira prato novo com o nome da própria ficha.
    """
    de_para_pratos = de_para_pratos or {}
    avisos = []

    # Só receita de produção serve de subreceita. Aba de prato não entra aqui
    # de propósito: várias delas são só o "extra" do cardápio e citam o próprio
    # nome como ingrediente ("Bombom de Alcatra" consome "Bombom de Alcatra"
    # 0,18 kg). Se elas valessem como subreceita, esse 0,18 seria multiplicado
    # por si mesmo e a alcatra do prato cairia para 0,032 kg.
    catalogo = _indexar(receitas_producao)
    for k, v in _indexar([r for r in receitas_prato
                          if (r["tipo"] or "").lower().startswith("produ")]).items():
        catalogo.setdefault(k, v)

    insumos = {}   # nome do insumo -> unidade
    fichas = []    # (prato, insumo, quantidade por porção)
    ja_montados = {}  # chave do prato -> aba que o montou, para pegar aba repetida

    for receita in receitas_prato:
        escolhidos = de_para_pratos.get(receita["aba"])
        if isinstance(escolhidos, str):
            escolhidos = [escolhidos]

        # Uma aba marcada como Produção só vira prato se você disse que ela é
        # um: o "Caldinho de Batata" é vendido, mesmo estando marcado assim.
        if not escolhidos and (receita["tipo"] or "").lower().startswith("produ"):
            avisos.append(
                f"A aba '{receita['aba']}' está marcada como Produção na planilha "
                "de pratos, então virou só ingrediente de outras fichas, não um "
                "prato vendido."
            )
            continue

        porcoes = receita["porcoes"] or 1.0
        consumo = {}
        _explodir(receita, 1.0, catalogo, consumo, [id(receita)], avisos)

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
                insumos[insumo] = unidade_do_insumo(insumo)
                fichas.append({
                    "prato": prato,
                    "insumo": insumo,
                    "quantidade": round(quantidade / porcoes, 6),
                    "aba": receita["aba"],
                })

    # O que já existe no banco não precisa ser criado de novo.
    conn = get_connection()
    unidade_atual = {
        d["nome"]: d["unidade_medida"]
        for d in conn.execute("SELECT nome, unidade_medida FROM insumos").fetchall()
    }
    ja_tem_insumo = set(unidade_atual)
    ja_tem_prato = {d["nome"] for d in conn.execute("SELECT nome FROM pratos").fetchall()}
    conn.close()

    # Insumo que já existe, mas contado numa unidade diferente da que a ficha
    # usa. Fica invisível e estraga a conta: a ficha gasta 0,06 kg de pão e o
    # painel mostra o saldo em unidades.
    divergentes = [
        {"insumo": nome, "atual": unidade_atual[nome], "planilha": unidade}
        for nome, unidade in insumos.items()
        if nome in unidade_atual and unidade_atual[nome] != unidade
    ]

    pratos = sorted({f["prato"] for f in fichas})
    usados = set(insumos)

    return {
        "insumos": dict(sorted(insumos.items())),
        "insumos_novos": sorted(n for n in insumos if n not in ja_tem_insumo),
        "pratos": pratos,
        "pratos_novos": sorted(p for p in pratos if p not in ja_tem_prato),
        "fichas": sorted(fichas, key=lambda f: (f["prato"], f["insumo"])),
        "orfaos": sorted(n for n in ja_tem_insumo if n not in usados),
        "unidades_divergentes": sorted(divergentes, key=lambda d: d["insumo"]),
        # Prato que já recebe venda e que a planilha não cobre: continua sem
        # ficha, então a venda dele não desconta nada do estoque.
        "pratos_sem_ficha": sorted(p for p in ja_tem_prato if p not in set(pratos)),
        "avisos": sorted(set(avisos)),
    }


def _indexar(receitas: list[dict]) -> dict[str, dict]:
    """Índice das receitas por todos os nomes pelos quais elas podem ser citadas."""
    indice = {}
    for receita in receitas:
        for nome in (receita["aba"], receita["nome"], receita["nome_venda"]):
            if nome:
                indice.setdefault(chave(nome), receita)
    return indice


def _rendimento_confiavel(receita: dict, avisos: list) -> float:
    """Rendimento do lote, com defesa contra o campo preenchido errado.

    Quando o rendimento declarado é muito menor que a soma dos ingredientes,
    ele não é redução de cozimento — é erro de digitação. Nesses casos vale
    a soma dos ingredientes, que ao menos mantém a conta na ordem de grandeza
    certa, e o caso é reportado.
    """
    soma = sum(i["quantidade"] for i in receita["ingredientes"])
    rendimento = receita["rendimento"] or 0
    if rendimento >= soma * RENDIMENTO_MINIMO_PLAUSIVEL:
        return rendimento
    avisos.append(
        f"Rendimento de '{receita['aba']}' está em {rendimento or 0:g} kg mas os "
        f"ingredientes somam {soma:g} kg. Usei a soma para não inflar o consumo — "
        "confira o campo na planilha."
    )
    return soma


def _explodir(receita: dict, fator: float, catalogo: dict,
              consumo: dict, pilha: list, avisos: list):
    """Acumula em `consumo` os insumos crus de uma receita, já multiplicados.

    `pilha` guarda as receitas sendo abertas neste caminho. Ela existe porque
    a planilha tem aba que cita a si mesma ("Bombom de Alcatra" consome
    "Bombom de Alcatra"): sem isso a explosão entraria em laço infinito.
    A identidade é o objeto da receita, não o nome — "Brownie" existe nas duas
    planilhas, e o prato Brownie de fato consome a produção Brownie.
    """
    for item in receita["ingredientes"]:
        nome = chave(item["nome"])
        quantidade = item["quantidade"] * fator

        alvo = APELIDOS_DE_RECEITA.get(nome)
        sub = catalogo.get(chave(alvo)) if alvo else catalogo.get(nome)

        if sub is not None and id(sub) not in pilha:
            if nome in APELIDOS_INCERTOS:
                avisos.append(
                    f"'{item['nome']}' não existe como aba; assumi a ficha "
                    f"'{sub['aba']}'. Confirme se é essa mesma."
                )
            rendimento = _rendimento_confiavel(sub, avisos)
            if rendimento > 0:
                _explodir(sub, quantidade / rendimento, catalogo, consumo,
                          pilha + [id(sub)], avisos)
                continue

        if sub is not None:
            avisos.append(
                f"A ficha '{sub['aba']}' cita a si mesma como ingrediente. "
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

        declarada = (item["unidade_declarada"] or "").lower()
        if declarada.startswith("un") and unidade_do_insumo(insumo) != "un":
            avisos.append(
                f"'{item['nome']}' está marcado como unidade na planilha, mas "
                f"'{insumo}' é controlado em {unidade_do_insumo(insumo)}. "
                "Confira a quantidade."
            )

        consumo[insumo] = consumo.get(insumo, 0.0) + quantidade


# ---------- Gravação ----------

def aplicar_plano(plano: dict, substituir_fichas: bool = True,
                  corrigir_unidades: bool = True) -> dict:
    """Grava o plano no banco. Devolve a contagem do que foi feito."""
    for nome in plano["insumos_novos"]:
        crud.cadastrar_insumo(nome, plano["insumos"][nome])

    if corrigir_unidades and plano.get("unidades_divergentes"):
        conn = get_connection()
        for divergencia in plano["unidades_divergentes"]:
            conn.execute(
                "UPDATE insumos SET unidade_medida = ? WHERE nome = ?",
                (divergencia["planilha"], divergencia["insumo"]),
            )
        conn.commit()
        conn.close()

    for nome in plano["pratos_novos"]:
        crud.cadastrar_prato(nome)

    if substituir_fichas:
        _limpar_fichas(sorted({f["prato"] for f in plano["fichas"]}))

    for ficha in plano["fichas"]:
        crud.definir_ficha_tecnica(ficha["prato"], ficha["insumo"], ficha["quantidade"])

    return {
        "insumos": len(plano["insumos_novos"]),
        "pratos": len(plano["pratos_novos"]),
        "fichas": len(plano["fichas"]),
        "unidades": len(plano.get("unidades_divergentes", [])) if corrigir_unidades else 0,
    }


def _limpar_fichas(pratos: list[str]):
    """Apaga a ficha atual dos pratos que a planilha vai redefinir.

    Sem isso um insumo que saiu da receita continuaria sendo descontado para
    sempre, porque `definir_ficha_tecnica` só cria ou atualiza linha.
    """
    conn = get_connection()
    for prato in pratos:
        linha = conn.execute("SELECT id FROM pratos WHERE nome = ?", (prato,)).fetchone()
        if linha:
            conn.execute("DELETE FROM ficha_tecnica WHERE prato_id = ?", (linha["id"],))
    conn.commit()
    conn.close()
