"""
contagem_import.py
Lê a planilha de contagem semanal do restaurante (aba COMPRAS) e
transforma cada linha dela num item da contagem do sistema, ligado a um
insumo.

A planilha é como o estoque é contado de verdade, prateleira por
prateleira, e por isso a tela de contagem segue ela: mesma ordem, mesmas
seções, mesma unidade. O problema é que essa unidade raramente é a do
insumo. A cozinha conta o parmesão em peça, e a ficha técnica desconta
em kg. Cada linha guarda então um **fator de conversão**: 1 peça do
"QUEIJO PARMESÃO PEÇA (PEÇA 7,5KG)" vale 7,5 kg de "Queijo parmesão".
Várias linhas podem cair no mesmo insumo (alcatra em peça, porcionada na
câmara 3 e porcionada na cozinha são todas "Alcatra"), e a contagem do
insumo é a soma delas.

Três regras, decididas com o usuário:

1. **Só alimentos e bebidas.** A planilha também tem limpeza,
   descartáveis, material de escritório e utensílios; esses ficam fora.
2. **Os alimentos caem nos insumos genéricos** que a ficha técnica já
   usa, com os mesmos nomes do `ficha_import.NOMES_CANONICOS`. Senão o
   que é contado e o que é consumido seriam insumos diferentes, e o
   estoque teórico nunca fecharia.
3. **As bebidas viram um insumo por produto**, com o nome limpo a partir
   da descrição: Heineken e Amstel são produtos diferentes na prateleira
   e no preço. A exceção são as duas que a cozinha usa como ingrediente
   (cachaça 51 e conhaque Domec), que caem nos insumos da ficha.

Quando a descrição não diz o peso (uma "UND" de alface, um "MÇ" de
alecrim) e o insumo já existe em kg, o fator fica **em branco, a definir**:
chutar um peso médio seria pior, porque o erro entraria calado em toda
contagem. A tela de itens da contagem mostra esses casos para o usuário
preencher.

Nada aqui grava sozinho: `montar_plano()` devolve o que seria feito e
`aplicar_plano()` grava, tudo ou nada.
"""

import re

import openpyxl

from database import get_connection
from ficha_import import chave

ABA = "COMPRAS"

# Seções da planilha que não entram. A planilha segue a ordem bebidas →
# alimentos → limpeza → descartáveis → escritório → utensílios; a leitura
# para na primeira destas, mas cada uma também é recusada pelo nome, caso
# alguém reordene a planilha.
SECOES_FORA = ("HIGIENE", "DESCARTAVEIS", "MATERIAL DE ESCRITORIO", "UTENSILIOS")

# A primeira seção de comida. Tudo o que vem antes dela é bebida.
PRIMEIRA_SECAO_DE_ALIMENTOS = "ALIMENTOS"

# A "Medida" da planilha, por extenso. É o que aparece na tela de
# contagem, ao lado do campo, para quem conta saber em que unidade digitar.
# O chopp ("BR", barril na planilha) é contado em litro: o barril aberto
# está pela metade, e barril inteiro não diz quanto sobrou. Pedido do
# usuário em 24/09/2026.
MEDIDAS = {
    "BR": "l", "GF": "garrafa", "GRF": "garrafa", "GR": "garrafa",
    "GF / DS": "garrafa", "GF/DS": "garrafa", "GF/DF": "garrafa",
    "LT": "lata", "BX": "caixa", "CX": "caixa", "SC": "saco", "VD": "vidro",
    "PCT": "pacote", "PT": "pacote", "BLD": "balde", "GL": "galão",
    "UND": "un", "UNID": "un", "UN": "un", "UM": "un", "KG": "kg",
    "PÇ": "peça", "MÇ": "maço", "MC": "maço", "BDJ": "bandeja", "POTE": "pote",
}


def _i(insumo, fator, unidade, conta_em=None):
    """Uma linha de alimento: vai para `insumo` (em `unidade`), 1 contada = `fator`.

    `conta_em` troca a unidade de contagem quando a "Medida" da planilha
    não é como a equipe conta de verdade (ex.: morango em bandeja, não em
    caixa). Informado pelo usuário em 23/09/2026.
    """
    return (insumo, fator, unidade, conta_em)


A_DEFINIR = None   # fator que depende de um peso que a planilha não diz
IGNORAR = "ignorar"

# ---------- Alimentos: linha da planilha → insumo ----------
# Chave: a descrição como está na planilha (comparada por `chave()`, sem
# acento nem caixa). Os nomes de insumo seguem NOMES_CANONICOS do
# importador de ficha técnica.
ALIMENTOS = {
    # ALIMENTOS
    "ACETO BALSAMICO IGP FASANO 250ML": _i("Vinagre balsâmico", 0.25, "l"),
    "AÇUCAR REFINADO 1KG": _i("Açúcar", 1, "kg"),
    "AÇUCAR SACHET CX - (UNIÃO)": _i("Açúcar em sachê", 1, "caixa"),
    "ADOÇANTE SACHET CX 400 GR - SUCRALOSE (UNIAO)": _i("Adoçante em sachê", 0.4, "kg"),
    "ADOÇANTE SACHET CX 600 GR - SUCRALOSE (LINEA)": _i("Adoçante em sachê", 0.6, "kg"),
    "ALCAPARRAS BLD 2 KG": _i("Alcaparra", 2, "kg"),
    "ALGA NORI": _i("Alga nori", 1, "pacote"),
    "AMIDO DE MILHO 1,8KG MAISENA": _i("Amido de milho", 1.8, "kg"),
    "ARROZ ARBORIO CX 1 KG (LA PASTINA)": _i("Arroz arbóreo", 1, "kg"),
    "ARROZ ARBORIO CX 2KG (CAMIL/FANTÁSTICO)": _i("Arroz arbóreo", 2, "kg"),
    "ARROZ BASMATI PCT 500G": _i("Arroz basmati", 0.5, "kg"),
    "ARROZ PCT 5 KG (PRATO FINO OU CAMIL)": _i("Arroz", 5, "kg"),
    "AZEITE DE DENDE VD 900 ML": _i("Azeite de dendê", 0.9, "l"),
    "AZEITE GALLO GL 2LT": _i("Azeite", 2, "l"),
    "AZEITE GALLO VD 500ML": _i("Azeite", 0.5, "l"),
    "AZEITE GL 5LT": _i("Azeite", 5, "l"),
    "AZEITE TRUFADO ( SAVITAR/ COLLITALI)": _i("Azeite trufado", 0.25, "l", "un"),
    "AZEITONAS PRETAS AZAPA 110/130 BLD 3,2KG DRENADO": _i("Azeitona", 3.2, "kg"),
    "AZEITONAS VERDE AZAPA 110/130 BLD 3,2KG DRENADO": _i("Azeitona", 3.2, "kg"),
    "BATATA PALHA Extra ALMAVITA PCT 1KG": _i("Batata palha", 1, "kg"),
    "BISCOITO CHAMPAGNE BAUDUCCO CX 150G": _i("Bolacha champanhe", 0.15, "kg"),
    "BOLACHA MAISENA PCT 200GR": _i("Bolacha maisena", 0.2, "kg"),
    # "Café" em unidade é a dose da ficha técnica; o pó é outro insumo.
    "CAFÉ 3 CORAÇÕES PCTE 500GR": _i("Café em pó", 0.5, "kg"),
    "CAFÉ EXPRESSO TRES CORAÇAOES AMENO C/10 UND": _i("Cápsula de café ameno", 1, "caixa"),
    "CAFÉ EXPRESSO TRES CORAÇAOES CAFÉ COM LEITE C/10 UND": _i("Cápsula de café com leite", 1, "caixa"),
    "CAFÉ EXPRESSO TRES CORAÇAOES CAPUCCINO C/10 UND": _i("Cápsula de cappuccino", 1, "caixa"),
    "CAFÉ EXPRESSO TRES CORAÇAOES expresso C/10 UND": _i("Cápsula de café expresso", 1, "caixa"),
    "CAFÉ EXPRESSO TRES CORAÇAOES SUPREMO C/10 UND": _i("Cápsula de café supremo", 1, "caixa"),
    "CHA CX C/ 10 SACHES SABORES VARIADOS TWINGS": _i("Chá em sachê", 1, "caixa"),
    "CHOC. AO LEITE CALEBAUTT CX 10 KG": _i("Chocolate", 10, "kg"),
    "CHOC. CACAU EM PÓ 70% BARRY CALLEBAUT EXTRA BRUTE": _i("Cacau em pó", 0.5, "kg", "un"),
    "CHOC. COBERTURA FACIL SICAO BLEND BARRA 2,1KG meio amargo": _i("Chocolate", 2.1, "kg"),
    "CHOC. MEIO AMARGO CALEBAUTT CX 10 KG SICAO": _i("Chocolate", 10, "kg"),
    "CHOC. SICAO BRANCO 2,1KG (BARRA)": _i("Chocolate branco", 2.1, "kg"),
    "COCO RALADO FRESCO / FLOCOS MEDIO PCT 5KG": _i("Coco ralado", 5, "kg"),
    'CONE DE MILHO "12CM ALTURA/ 5CM ABERTURA"': _i("Cone de milho", 1, "un"),
    "CREME DE CEBOLA": _i("Creme de cebola", 1, "pacote"),
    "CREME DE LEITE 17% DE GORDURA 1KG": _i("Creme de leite", 1, "kg"),
    "DOCE DE LEITE JERSEY VALLEY BLD 5KG": _i("Doce de leite", 5, "kg"),
    "EXTRATO DE TOMATE POCHE 2KG (ELEFANTE)": _i("Extrato de tomate", 2, "kg"),
    "FARINHA DE MANDIOCA": _i("Farinha de mandioca", 1, "pacote"),
    "FARINHA DE ROSCA FINA 500gr": _i("Farinha de rosca", 0.5, "kg"),
    "FARINHA DE TRIGO PCT 5 KG ANACONDA": _i("Farinha de trigo", 5, "kg"),
    "FARINHA PANKO PCT 1 KG (FOOD SERVIÇE)": _i("Farinha panko", 1, "kg"),
    "FEIJÃO CARIOCA 2KG (FANTASTICO/CAMIL/KICALDO)": _i("Feijão", 2, "kg"),
    "FEIJÃO PRETO 1 KG": _i("Feijão preto", 1, "kg"),
    "FERMENTO BIOLOGICO SECO 500GR FLESHMAN": _i("Fermento biológico", 0.5, "kg"),
    "FERMENTO PÓ PT 500 GR (ROYAL)": _i("Fermento químico", 0.5, "kg"),
    "GELEIA DE DAMASCO BLD 1,2 KG HOMEMADE": _i("Geleia de damasco", 1.2, "kg"),
    "GELEIA DE DAMASCO BLD 2 KG HOMEMADE": _i("Geleia de damasco", 2, "kg"),
    "GELEIA DE PIMENTA BLD 2 KG HOMEMADE": _i("Geleia de pimenta", 2, "kg"),
    "GRÃO DE BICO": _i("Grão-de-bico", 1, "un"),
    "HONDASHI": _i("Hondashi", 1, "pacote"),
    "KETCHUP 3,5 KG GL (CEPERA)": _i("Ketchup", 3.5, "kg"),
    "KETCHUP SACHET CX 1,1 KG HEINZ": _i("Ketchup em sachê", 1, "caixa"),
    "LEITE CONDENSADO TP 395GR": _i("Leite condensado", 0.395, "kg"),
    "LEITE DE COCO SOCOCO 1L": _i("Leite de coco", 1, "l"),
    "LEITE EM PO PCT (PIRACANJUBA) PCT 1KG": _i("Leite em pó", 1, "kg"),
    "LEITE INTEGRAL 1 LT TP": _i("Leite", 1, "l"),
    "MACARRAO CHIFERRI - ELBOWS 500G (BARILA)": _i("Massa", 0.5, "kg"),
    "MACARRAO CONCHIGLIONE GRANDE 500G (PAGANINI)": _i("Massa", 0.5, "kg"),
    "MACARRAO ESPAGUETE BARILLA 500G": _i("Massa", 0.5, "kg"),
    "MACARRAO ESPAGUETTI 8 PCT 500 GR (ADRIA OU RENATA)": _i("Massa", 0.5, "kg"),
    "MACARRAO PAPARDELLE 201 (PAGANINI / DICECCO / COLAVITA)": _i("Massa", 1, "kg", "un"),
    "MACARRAO PENNE 500 GR ( RENATA)": _i("Massa", 0.5, "kg"),
    "MACARRAO PENNE BARILLA PCT 500G": _i("Massa", 0.5, "kg"),
    "MACARRAO RIGATONI BARILLA PCT 500G": _i("Massa", 0.5, "kg"),
    "MAIONESE SACHET - CAIXA 1,1 KG (HEINZ)": _i("Maionese em sachê", 1, "caixa"),
    "MAIONESE HELMANS 2,8KG": _i("Maionese", 2.8, "kg"),
    "MARSHMELOW BRANCO PACOTE 250 GR": _i("Marshmallow", 0.25, "kg"),
    "MASSA DE LAZANHA ADRIA 500 GR": _i("Massa de lasanha", 0.5, "kg"),
    "MOLHO DE OSTRA": _i("Molho de ostra", 1, "un"),
    "MOLHO DE PIMENTA VIDRO 60 ML TABASCO": _i("Molho de pimenta", 0.06, "l"),
    "MOLHO INGLÊS 1 LITRO HEMMER": _i("Molho inglês", 1, "l"),
    "MOLHO SHOYO SAKURA ORIENTAL LIGTH GL 5L": _i("Shoyu", 5, "l"),
    "MOSTARDA GALAO 3,3 (CEPERA)": _i("Mostarda", 3.3, "kg"),
    "MOSTARDA DIJON 1,01 kg (BEAUFOR)": _i("Mostarda", 1.01, "kg"),
    "MOSTARDA ESCURA HEMER 200G": _i("Mostarda", 0.2, "kg"),
    "MOSTARDA L ' ANCIENE": _i("Mostarda", 0.5, "kg"),
    "MOSTARDA SACHET CAIXA (HEINZ)": _i("Mostarda em sachê", 1, "caixa"),
    "NACHOS - CANAPES(EMBALAGEM 250GR)": _i("Nachos", 0.25, "kg"),
    "OLEO ALGODAO BLD 15 LTS/ 15,8 KG": _i("Óleo", 15, "l"),
    "OLEO DE GERGILIM TORRADO 1 L": _i("Óleo de gergelim", 1, "l"),
    "OLEO SOJA 900 ML": _i("Óleo", 0.9, "l"),
    "PAÇOCA SANTA HELENA CX C/100UN": _i("Paçoca", 100, "un"),
    "PALITO DE DENTE SACHE": IGNORAR,   # está em ALIMENTOS, mas não é comida
    "PALMITO 1,8 KG PUPUNHA TOLETE VIDRO": _i("Palmito", 1.8, "kg"),
    "PESSEGO EM CALDA": _i("Pêssego em calda", 1, "lata"),
    "PIKLES DE PEPINO VD 280G DRENADO": _i("Picles de pepino", 0.28, "kg"),
    "PIMENTA BIQUINHO BALDE 1,8 KG": _i("Pimenta biquinho", 1.8, "kg"),
    "PREPARO CHOCOLATE PÓ SUISSE 200GR": _i("Chocolate em pó", 0.2, "kg"),
    "SAL GROSSO PCT 1 KG": _i("Sal grosso", 1, "kg"),
    "SAL REFINADO PCT 1KG": _i("Sal", 1, "kg"),
    "SAL SACHE CX 1 KG - (CISNE)": _i("Sal em sachê", 1, "caixa"),
    "SUCO DE TOMATE GF 1000 ML RAIOLA": _i("Suco de tomate", 1, "l"),
    "SUCO SABORES VARIADOS PCT 1 KG (MENOS CAJU)": _i("Polpa de fruta", 1, "kg"),
    "TAPIOCA GRANULADA PACOTE 500 GR YOKI": _i("Tapioca granulada", 0.5, "kg"),
    "TOMATE PELATI LT2,5KG": _i("Tomate pelado", 2.5, "kg"),
    "TRIGO P/ KIBE - pct 1KG": _i("Trigo para quibe", 1, "kg"),
    "VINAGRE BALSAMICO LA PASTINA 250ML": _i("Vinagre balsâmico", 0.25, "l"),
    "VINAGRE DE ALCOOL COLORIDO CASTELO - 5L": _i("Vinagre", 5, "l"),
    "VINAGRE DE VINHO BRANCO CASTELO 750 ML": _i("Vinagre", 0.75, "l"),
    "VINHO BRANCO SECO COZINHA 750 ML (CHALISE)": _i("Vinho branco", 0.75, "l"),
    "VINHO TINTO SECO COZINHA 750 ML (CHALISE)": _i("Vinho tinto", 0.75, "l"),
    "XAROPE GLICOSE DE MILHO 350 GR (YOKI)": _i("Glucose de milho", 0.35, "kg"),
    # TEMPEROS/GRAOS/FARINHAS
    "AÇAFRÃO PÓ PCT 500G": _i("Açafrão", 0.5, "kg"),
    "AMENDOA LAMINADA - 1 KG (NÃO COMPRAR DA CASA DO CONFEITEIRO) - QUEBRADIÇA":
        _i("Amêndoa laminada", 1, "kg"),
    "AMENDOAS INTEIRA": _i("Amêndoa inteira", 1, "pacote"),
    "ANIS ESTRELADO 250G": _i("Anis-estrelado", 0.25, "kg"),
    "BICARBONATO DE SÓDIO PCT 1 KG": _i("Bicarbonato de sódio", 1, "kg"),
    "CANELA EM PAU PCT 500GR": _i("Canela", 0.5, "kg"),
    "CANELA EM PÓ MOÍDA PACOTE 500 GR": _i("Canela", 0.5, "kg"),
    "CARDAMOMO EM PO (BOMBAY)": _i("Cardamomo", 1, "pacote"),
    "CASTANHA CAJU CRUA - 1 KG": _i("Castanha de caju", 1, "kg"),
    "CASTANHA PARÁ PCT 1 KG": _i("Castanha-do-pará", 1, "kg"),
    "COENTRO EM GRAOS - 500 GR": _i("Coentro em semente", 0.5, "kg"),
    "COLORIFICIO PCT 1 KG": _i("Colorau", 1, "kg"),
    "CURCUMA": _i("Cúrcuma", 1, "kg"),
    "CURRY EM PÓ PCT 500 GR": _i("Curry", 0.5, "kg"),
    "DAMASCO - 1 KG": _i("Damasco", 1, "kg"),
    "LEMON PEPPER PCT 500 GR(BOMBAY)": _i("Lemon pepper", 0.5, "kg"),
    "MOSTARDA EM GRÃO": _i("Mostarda em grão", 1, "pacote"),
    "NOS MOSCADA EM BOLINHA PCT": _i("Noz-moscada", 0.5, "kg", "un"),
    "NOZES MARIPOSA EXTRA LITGH PCT 1 KG": _i("Nozes", 1, "kg"),
    "NUTS CARAMELIZADAS KG": _i("Nuts caramelizadas", 1, "kg"),
    "OREGANO PCT 1KG": _i("Orégano", 1, "kg"),
    "PAPRICA DEFUMADA PCT 500G": _i("Páprica defumada", 0.5, "kg"),
    "PIMENTA CALABRESA FLOCOS 500 GR": _i("Pimenta calabresa", 0.5, "kg"),
    "PIMENTA PRETA EM GRAO": _i("Pimenta-do-reino", 0.5, "kg", "un"),
    "QUINOA BRANCA": _i("Quinoa", 1, "pacote"),
    "QUINOA PRETA": _i("Quinoa", 1, "pacote"),
    "QUINOA VERMELHA": _i("Quinoa", 1, "pacote"),
    "SEMENTE DE CUMARU": _i("Cumaru", 1, "kg"),
    # LATICINIOS (e frios)
    "BACON": _i("Bacon", 1, "kg"),
    "Borbinha (peças de 300g aprox.)": _i("Borbinha", 0.3, "kg"),
    "CALABRESA APIMENTADA CURADA NO AZEITE CANCIAN": _i("Calabresa curada", 1, "pacote"),
    "CHANTILY SPRAY POLENGHI 250GR": _i("Chantilly", 0.25, "kg"),
    "COPA LOMBO CURADA": _i("Copa lombo", 1, "pacote"),
    "COPA LOMBO CURADA CANCIAN": _i("Copa lombo", 1, "pacote"),
    "IOGURTE NATURAL VIVE": _i("Iogurte natural", 1, "un"),
    "LINGUIÇA CALABRESA PERDIGÃO/SADIA DEFUMADA RETA PCT 2,5 KG": _i("Linguiça calabresa", 1, "kg"),
    "LINGUIÇA CALABRESA PORCIONADA FONDUE - (CÂMARA 3)": _i("Linguiça calabresa", 1, "kg"),
    "LOMBO CANADENSE": _i("Lombo", 0.5, "kg"),
    "MANTEIGA SAL PEÇA (PEÇA 5 KG) 3 MARIAS": _i("Manteiga", 5, "kg"),
    "nta Queijo Brisa (peças com 450g aprox.)": _i("Queijo brisa", 0.45, "kg"),
    "PEITO PERU (PEÇA 2,5 KG)": _i("Peito de peru", 2.5, "kg"),
    "PREPARO PARA FONDUE QUEIJO 400G SUPREMO": _i("Preparo de fondue", 0.4, "kg"),
    "PRESUNTO (PEÇA 3,5 KG) - FUNCIONÁRIOS": _i("Presunto", 3.5, "kg"),
    "PRESUNTO PARMA FATIADO BANDEJA 100GR CERATTI": _i("Presunto parma", 0.1, "kg"),
    "QUEIJO BRIE PEÇA 1 KG SÃO VICENTE /VIGOR": _i("Queijo brie", 1, "kg"),
    "QUEIJO BURRATA POTE 200GR (BUFALAT / RENATO)": _i("Burrata", 0.2, "kg"),
    "QUEIJO CAMEMBERE FRACIONADO": _i("Queijo camembert", 1, "kg"),
    "QUEIJO CHEDDAR FATIADO KG (VIGOR)": _i("Queijo cheddar", 2, "kg"),
    "QUEIJO CREAM CHEESE POLENGHI BISNAGA": _i("Cream cheese", 1, "un"),
    "QUEIJO GORGONZOLA 3KG SÃO VICENTE/VIGOR": _i("Queijo gorgonzola", 3, "kg"),
    "QUEIJO GRUYERE pç 3KG": _i("Queijo gruyère", 3, "kg"),
    'QUEIJO MUSS. DE BUFALLA CEREJA 250G" BUFALAT/ RENATO"': _i("Mussarela de búfala", 0.25, "kg"),
    "QUEIJO MUSSARELA PEÇA (PEÇA 4KG) CATUPIRY/PRESIDENTE/SCALA": _i("Queijo mussarela", 4, "kg"),
    "QUEIJO PARMESÃO 5 ESTRELAS/PINHALZINHO PÇ 6KG (DADINHO TAPIOCA)": _i("Queijo parmesão", 6, "kg"),
    "QUEIJO PARMESÃO PEÇA (PEÇA 7,5KG) MARCA CAPA PRETA": _i("Queijo parmesão", 7.5, "kg"),
    "QUEIJO PROVOLONE (PROVOLETE)": _i("Queijo provolone", 1, "peça"),
    "QUEIJO TIPO GOLDA (PEÇA 2KG)": _i("Queijo gouda", 2, "kg"),
    "QUEIJO TIPO REINO (PEÇA 2KG)": _i("Queijo do reino", 2, "kg"),
    "QUEJO MINAS PADRAO": _i("Queijo minas", 1, "kg"),
    "REQUEIJÃO TIROLEZ/SCALA BISNAGA 1,5 KG": _i("Requeijão", 1.5, "kg"),
    "SALAME SADIA/PERDIGÃO PÇ 0,900G A 1KG": _i("Salame", 1, "un"),
    # CARNES/AVES
    "APARAS DE CARNE KG (CAMERA - 3)": _i("Apara de carne", 1, "kg"),
    "BARRIGA DE PORCO": _i("Barriga de porco", 1, "kg"),
    "BARRIGA DE PORCO PORCIONADO": _i("Barriga de porco", 1, "kg"),
    "BOMBOM DE ALCATRA (BABY BEEF PEÇA)": _i("Alcatra", 1, "kg"),
    "BOMBOM DE ALCATRA (PORCIONADO)": _i("Alcatra", 1, "kg"),
    "CARNE PARA HAMBURGUER": _i("Hambúrguer", 1, "kg"),
    "CARNE SECA": _i("Carne seca", 1, "kg"),
    "CHORIZO CONTRAFILE BASSI ANGUS": _i("Chorizo", 1, "kg"),
    "CHORIZO PORCIONADO (CAMERA - 3)": _i("Chorizo", 1, "kg"),
    "COSTELA BOVINA PORCIONADO (CAMERA -3)": _i("Costela", 1, "kg"),
    "COSTELA BOVINA MINGA INTEIRA (MAGRA)": _i("Costela", 1, "kg"),
    # Cozida e desfiada: o peso já não é o da costela crua.
    "COSTELA DESFIADA": _i("Costela desfiada", 1, "kg"),
    "FILET MIGNON 4/5 (PLENNA - FRIGOL - IGUATEMI)": _i("Mignon", 1, "kg"),
    "FILET MIGNON PORCIONADO ( GARDE) ESCALOPE / TORNEDOR": _i("Mignon", 1, "kg"),
    "FILET MIGNON PORCIONADO (CAMERA - 3 - FILE APERITIVO) PORÇÃO 280GR": _i("Mignon", 1, "kg"),
    "FILET MIGNON PORCIONADO BIFE P/ PARMEGIANA 160gr (GARDE)": _i("Mignon", 0.16, "kg"),
    "FILET MIGNON PORCIONADO STEAK TARTARE": _i("Mignon", 1, "kg"),
    "FILET MIGNON PORCIONADO ISCA DE MIGNON": _i("Mignon", 1, "kg"),
    "LINGUICA TOSCANA PORCIONADA (MINI HAMBURGUER) (SADIA / PERDIGÃO)": _i("Linguiça toscana", 1, "kg"),
    "MINI HAMBURGUE": _i("Hambúrguer", 0.1, "kg", "pacote"),
    "MIOLO DE ALCATRA KG": _i("Alcatra", 1, "kg"),
    "MIOLO/ CORAÇÃO DE ALCATRA PORCIONADO (CAMERA - 3) PORÇÃO 180gr": _i("Alcatra", 1, "kg"),
    "MIOLO/ CORAÇÃO DE ALCATRA PORCIONADO (COZINHA) PARMEGIANA": _i("Alcatra", 1, "kg"),
    "MOCOTÓ SERRADO": _i("Mocotó", 1, "kg"),
    "OSSO PARA CALDO": _i("Osso", 1, "kg"),
    "OSSOBUCO (CORTES SELECIONADOS)": _i("Ossobuco", 1, "kg"),
    "PEITO DE FRANGO PORCIONADO (GOURMET)": _i("Frango", 1, "kg"),
    "PEITO DE FRANGO PORCIONADO - ISCAS (FRANGO GOURMET) / (CAMARA 3)": _i("Frango", 0.3, "kg", "pacote"),
    "PEITO DE FRANGO PORCIONADO - KIDS": _i("Frango", 1, "kg"),
    "PEITO DE FRANGO PORCIONADO FONDUE (CAMERA - 3)": _i("Frango", 1, "kg"),
    "PEITO DE FRANGO PORCIONADO PARMEGIANA(GARDE)": _i("Frango", 0.15, "kg"),
    "PEITO DE FRANGO SEM OSSO": _i("Frango", 1, "kg"),
    "PORTERHOUSE FRIBOI 1953 PÇ 1KG ( 900G A 1KG)": _i("Porterhouse", 1, "kg"),
    "TOMAHAWK": _i("Tomahawk", 1, "kg"),
    # PROTEINAS FUNCIONARIOS — comida da equipe. Quando o mesmo produto
    # também existe na seção da cozinha, fica num insumo à parte: são
    # estoques separados na prática, e a refeição da equipe não tem ficha
    # técnica, então apareceria como perda no insumo da cozinha.
    "ACEM KG": _i("Acém", 1, "kg"),
    "APARAS DE FRANGO": _i("Apara de frango", 1, "kg"),
    "BISTECA SUINA KG": _i("Bisteca suína", 1, "kg"),
    "CARNE MOÍDA": _i("Carne moída", 1, "kg"),
    "COSTELA BOVINA EM CUBOS": _i("Costela em cubos (funcionários)", 1, "kg"),
    "COSTELA SUINA (INTEIRA)": _i("Costela suína", 1, "kg"),
    "COXA E SOBRECOXA": _i("Coxa e sobrecoxa", 1, "kg"),
    "COXÃO DURO": _i("Coxão duro", 1, "kg"),
    "COXÃO MOLE PEÇA (FUNCIONÁRIOS)": _i("Coxão mole", 1, "kg"),
    "COXINHA DA ASA": _i("Coxinha da asa", 1, "kg"),
    "CUPIM TIPO B": _i("Cupim", 1, "kg"),
    "FILÉ DE PEITO DE FRANGO SEM OSSO": _i("Frango (funcionários)", 1, "kg"),
    "FILE DE TILAPIA": _i("Tilápia", 1, "kg"),
    "LINGUICA TOSCANA PCT C/5KG (SADIA / PERDIGÃO)": _i("Linguiça toscana (funcionários)", 1, "kg"),
    "LOMBO SUÍNO PALMITO": _i("Lombo suíno", 1, "kg"),
    "PANGASSIUS": _i("Pangasius", 1, "kg"),
    "PATINHO KG": _i("Patinho", 1, "kg"),
    "PEITO BOVINO": _i("Peito bovino", 1, "kg"),
    "SALSICHA": _i("Salsicha", 1, "kg"),
    "SASSAMIZINHO DE FRANGO": _i("Sassami", 1, "kg"),
    # PEIXES
    "BACALHAU DESFIADO DESSALGADO": _i("Bacalhau", 1, "kg"),
    "CAMARÃO 11/15 (CÂMARA 3 /COZINHA)": _i("Camarão", 1, "kg"),
    "CAMARÃO 7 BARBA KG C/15KG": _i("Camarão sete barbas", 1, "kg"),
    "CAMARÃO 7 BARBA PORCIONADO (CÂMARA 3 / COZINHA)": _i("Camarão sete barbas", 1, "kg"),
    "Camarão pequeno porcionado": _i("Camarão pequeno", 1, "kg"),
    "CAMARÃO 11/15": _i("Camarão", 1, "kg"),
    "DOURADO PORCIONADO (Camarão 20/30)": _i("Dourado", 1, "kg"),
    "SALMÃO APARAS (CAMERA - 3) ISCAS": _i("Salmão", 1, "kg"),
    "SALMÃO PORCIONADO (CÂMARA 3 / COZINHA)": _i("Salmão", 1, "kg"),
    "SALMÃO PREMIUM CHILENO (2,5 A 3 KG) KG (250 gr) C/10KG": _i("Salmão", 1, "kg"),
    "TRUTA FILÉ ESPALMADA 215gr a 280gr": _i("Truta", 1, "kg"),
    "TRUTA FILÉ ESPALMADA PORCIONADO ISCAS": _i("Truta", 1, "kg"),
    # LINGUIÇAS SPECIALLI / CANCIAN
    "LINGUIÇA CAMPERA (SPECIALY)": _i("Linguiça campeira", 0.5, "kg", "un"),
    "LINGUIÇA DE LIMAO SICILIANO (CANCIAN)": _i("Linguiça de limão siciliano", 1, "kg"),
    # A ficha técnica conta esta linguiça em unidade, e a planilha em kg.
    "LINGUIÇA SUÍNA COM PROVOLONE PCT 400G (ARTESANAL ZR)": _i("Linguiça provolone", 1, "un", "un"),
    "MIX DE LINGUIÇAS DO INTERIOR PCT 500G (CANCIAN)": _i("Mix de linguiças", 1, "kg"),
    # LEGUMES CONGELADOS
    "ALHO DESCASCADO CONGELADO KG": _i("Alho", 1, "kg"),
    "BATATA CANOA MCCAIN": _i("Batata canoa", 1, "kg"),
    "BATATA NOISETE MCCAIN": _i("Batata noisete", 1, "kg"),
    # MASSAS
    "MASSA FOLHADA AROSA 2KG": _i("Massa folhada", 2, "kg"),
    "LASANHA": _i("Lasanha", 1, "un"),
    # CONGELADOS FRUTAS SORVETES
    "AMORA PCT": _i("Amora", 1, "kg"),
    "FRAMBOESA PCT": _i("Framboesa", 1, "kg"),
    "MARACUJA C/ SEMENTE PCT": _i("Polpa de maracujá", 1, "kg"),
    "MIRTILIO PCT": _i("Mirtilo", 1, "pacote"),
    "MORANGO PCT": _i("Morango", 1, "kg"),
    "SORVETE DE FRUTAS VERMELHAS BRUNO ALVES 5L": _i("Sorvete", 5, "kg", "un"),
    "SORVETE DE PISTACHE BRUNO ALVES 5L": _i("Sorvete", 5, "kg", "un"),
    # PAES
    "MINI PÃO DE BRIOCHE ASSADO SEPARADO": _i("Pão de hambúrguer", 1, "un"),
    "MINI PAO ITALIANO": _i("Pão", 0.1, "kg"),
    "PAO BOLA": _i("Pão de hambúrguer", 1, "un"),
    "PAO ITALIANO COMPRIDO FILÃO UND": _i("Pão", 0.1, "kg"),
    "PAO FRANCES FUNCIONÁRIOS FDS Bao Vencida": _i("Pão francês", 1, "un"),
    "PAO DE FORMA": _i("Pão de forma", 1, "un"),
    # HORTIFRUITI
    "ABACAXI TIPO 8": _i("Abacaxi", 1, "un"),
    "ABOBORA CABOTIAN": _i("Abóbora", 3, "kg"),
    "ABOBRINHA ITALIANA KG (CX C/ 18KG)": _i("Abobrinha", 1, "kg"),
    "ACELGA": _i("Acelga", 1, "maço"),
    "ALECRIM MAÇO": _i("Alecrim", 0.2, "kg"),
    "ALFACE AMERICANA": _i("Alface", 0.1, "kg"),
    "ALFACE CRESPA": _i("Alface", 0.1, "kg"),
    "ALFACE ROXA": _i("Alface", 0.1, "kg"),
    "ALHO PORO UND": _i("Alho-poró", 0.15, "kg"),
    "ALHO ROXO": _i("Alho", 1, "kg"),
    "BANANA DA TERRA": _i("Banana-da-terra", 1, "caixa"),
    "BANANA NANICA DUZIA (VERDE)": _i("Banana", 20, "kg"),
    "BATATA ASTERIX KG PCT 25KG": _i("Batata asterix", 1, "kg"),
    "BATATA INGLESA PCT 25KG": _i("Batata inglesa", 1, "kg"),
    "BERINGELA": _i("Berinjela", 1, "kg"),
    "BETERRABA": _i("Beterraba", 1, "kg"),
    "BROCOLIS PORCIONADO": _i("Brócolis", 1, "kg"),
    "BROCOLIS NINJA": _i("Brócolis", 0.1, "kg"),
    "CEBOLA NORMAL 20KG": _i("Cebola", 1, "kg"),
    "CEBOLA PEROLA": _i("Cebola", 1, "kg"),
    "CEBOLA ROXA KG": _i("Cebola", 1, "kg"),
    "CEBOLINHA": _i("Cebolinha", 1, "maço"),
    "CENOURA PORCIONADA": _i("Cenoura", 1, "kg"),
    "CENOURA KG C/20": _i("Cenoura", 1, "kg"),
    "COGUMELO PARIS HOCHIBRA BDJ 200G CX C/ 40 BANDEJAS": _i("Cogumelo Paris", 0.2, "kg"),
    "COGUMELO PORTO BELO HOCHIBRA BDJ 200G CX C/ 40 BANDEJAS": _i("Cogumelo portobello", 0.2, "kg"),
    "COGUMELO SHITAKI HOCHIBRA BDJ 200G CX C/ 40 BANDEJAS": _i("Cogumelo shitake", 0.2, "kg"),
    "COUVE FLOR": _i("Couve-flor", 1, "un"),
    "COUVE MANTEIGA": _i("Couve", 1, "maço"),
    "FOLHA DE LORO": _i("Louro", 0.2, "kg"),
    "GENGIBRE": _i("Gengibre", 1, "kg"),
    "HORTELÃ": _i("Hortelã", 1, "maço"),
    "KIWI": _i("Kiwi", 1, "bandeja"),
    "LARANJA SACO (SACO 18 KG)": _i("Laranja", 18, "kg"),
    "LIMÃO SICILIANO KG": _i("Limão siciliano", 1, "kg"),
    "LIMÃO TAITI KG": _i("Limão", 15, "kg"),
    "MAÇÃ GALA": _i("Maçã", 1, "kg"),
    "MAÇA VERDE": _i("Maçã verde", 1, "kg"),
    "MANDIOQUINHA KG (CX C/ 18KG)": _i("Mandioquinha", 1, "kg"),
    "MANDIOQUINHA PORCIONADO PURÊ (CAMERA - 3)": _i("Mandioquinha", 1, "kg"),
    "MANGA (SEM FIAPO)": _i("Manga", 1, "kg"),
    "MANGA PURE PORCIONADO (CAMERA - 3)": _i("Manga", 1, "kg"),
    "MANJERICÃO MAÇO": _i("Manjericão", 0.2, "kg"),
    "MANJERICÃO ROXO": _i("Manjericão", 0.2, "kg"),
    "MELANCIA": _i("Melancia", 1, "un"),
    "MILHO VERDE": _i("Milho verde", 1, "bandeja"),
    "MORANGO CAIXA GRANDE COM 4 CAIXINHAS": _i("Morango", 0.5, "kg", "bandeja"),
    "OVOS BANDEJA C/ 30 UND (CX C/ 10 BDJ) - TAMANHO JUMBO/EXTRA": _i("Ovo", 300, "un"),
    "PEPINO JAPONÊS": _i("Pepino", 1, "kg"),
    "PIMENTÃO VERDE": _i("Pimentão", 1, "kg"),
    "PIMENTAO AMARELO": _i("Pimentão", 1, "kg"),
    "PIMENTAO VERMELHO": _i("Pimentão", 1, "kg"),
    "REPOLHO ROXO": _i("Repolho roxo", 1, "un"),
    "REPOLHO VERDE": _i("Repolho", 1, "un"),
    "RUCULA MAÇO": _i("Rúcula", 1, "maço"),
    "SALSA CRESPA": _i("Salsinha", 0.2, "kg"),
    "SALSÃO MAÇO": _i("Salsão", 0.2, "kg"),
    "SALSINHA MAÇO": _i("Salsinha", 0.2, "kg"),
    "SALVIA": _i("Sálvia", 1, "maço"),
    "TOMATE CEREJA VERMELHO": _i("Tomate cereja", 0.2, "kg"),
    "TOMATE DEBORA": _i("Tomate", 1, "kg"),
    "TOMATE P/ MOLHO ITALIANO MADURO KG (CX C/ 20KG)": _i("Tomate", 20, "kg"),
    "TOMILHO": _i("Tomilho", 0.2, "kg"),
    "UVA VERDE THOMPSON CX C/10 BDJ 500GR": _i("Uva", 5, "kg"),
    # BROTOS
    "BROTO CEROFOLIO": _i("Broto de cerefólio", 1, "bandeja"),
    "BROTO COENTRO": _i("Broto de coentro", 1, "bandeja"),
    "BROTO DE BETERRABA": _i("Broto de beterraba", 1, "bandeja"),
    "BROTO DE MANJERICAO PADMA": _i("Broto de manjericão", 1, "bandeja"),
    "BROTO MISTO": _i("Broto misto", 1, "bandeja"),
    "Molho dr pimenta": _i("Molho de pimenta da casa", 1, "bandeja"),
    # MOLHOS e PORÇÕES — preparos da própria cozinha. Os que a ficha
    # técnica já explode no ingrediente cru seguem NOMES_CANONICOS
    # (purê de batata é Batata inglesa); os outros são insumos à parte, que só
    # se movem pela contagem.
    "MOHO AO SUGO": _i("Molho ao sugo", 1, "kg"),
    "MOLHO ROTI": _i("Molho roti", 1, "kg"),
    "MOLHO DE MARACUJA": _i("Molho de maracujá", 1, "kg"),
    "MILHO PORCIONADO ( maracuja)": _i("Milho porcionado", 1, "kg"),
    "PURE DE BANANA NANICA": _i("Banana", 1, "kg"),
    "PESTO": _i("Pesto", 1, "kg"),
    "PURE DE MANDIOCA": _i("Purê de mandioca", 1, "kg"),
    "PURE DE BATATA (pesto berinjela)": _i("Batata inglesa", 1, "kg"),
    "CROQUETA COSTELA": _i("Croqueta de costela", 0.3, "kg"),
    "Bolinho de Pernil": _i("Bolinho de pernil", 1, "pacote"),
    "BOLINHO DE CAMARÃO": _i("Bolinho de camarão", 0.3, "kg"),
    "DADINHO DE TAPIOCA": _i("Dadinho de tapioca", 1, "pacote"),
    "BOLINHO DE ABOBORA C/ CARNE SECA": _i("Bolinho de abóbora com carne seca", 1, "pacote"),
    "Bolinho de bacalhau": _i("Bolinho de bacalhau", 1, "pacote"),
    "ISCA DE FRANGO": _i("Isca de frango", 1, "pacote"),
    "COGUMELO": _i("Cogumelo Paris", 1, "kg"),
}

# Bebidas que a cozinha usa como ingrediente: a garrafa da prateleira do
# bar é a mesma que a ficha técnica consome, então cai no insumo dela.
BEBIDAS_DA_COZINHA = {
    "CACHAÇA 51 - 965 ML (19 DS)": _i("Cachaça", 0.965, "l"),
    "CONHAQUE DOMEC - 1000 ML (20 DS)": _i("Conhaque", 1, "l"),
}

_ALIMENTOS = {chave(k): v for k, v in ALIMENTOS.items()}
_BEBIDAS_DA_COZINHA = {chave(k): v for k, v in BEBIDAS_DA_COZINHA.items()}


# ---------- Nome de bebida ----------

# Siglas que ficam em maiúscula e palavras que ficam em minúscula no meio.
SIGLAS = {"KS", "IPA", "DOC", "IGP", "VIP", "DV", "N07", "XO"}
MINUSCULAS = {"de", "da", "do", "das", "dos", "e", "com", "sem", "di", "del", "la", "el", "en"}


def _palavra(palavra: str, primeira: bool) -> str:
    if palavra.upper() in SIGLAS:
        return palavra.upper()
    if palavra in ("ml", "L"):
        return palavra
    if not primeira and palavra.lower() in MINUSCULAS:
        return palavra.lower()
    if any(c.isdigit() for c in palavra):
        return palavra
    return palavra[:1].upper() + palavra[1:].lower()


def nome_de_bebida(descricao: str) -> str:
    """'WHISKY JOHNNIE WALKER BLACK LABEL -1000 ML (15 DS)' → 'Whisky Johnnie Walker Black Label 1000 ml'.

    Sai o que é embalagem e não produto (quantas doses, quantas no fardo,
    "(CARDÁPIO)"), e o volume ganha uma grafia só.
    """
    texto = " ".join(descricao.split())
    texto = re.sub(r"\(\s*\d+\s*\)?\s*DS\s*\)?", " ", texto, flags=re.I)   # (15 DS), ( 15) DS, (14DS)
    texto = re.sub(r"\bC/\s*\d+\b", " ", texto, flags=re.I)                 # C/12, C/ 6
    texto = re.sub(r"\bCX\s*\d+\b", " ", texto, flags=re.I)                 # CX 24
    texto = re.sub(r"(?<![\d\s])\s*\b(GF|LT)\b", " ", texto)                # "GF 450ML", "UVA LT 290ML"
    texto = re.sub(r"\((CARD[AÁ]PIO|CONSIGINADOS|BONIFICA[CÇ][AÃ]O)\)", " ", texto, flags=re.I)
    texto = re.sub(r"(\d)\s*(ML)\b", r"\1 ml", texto, flags=re.I)
    texto = re.sub(r"(\d)\s*(LTS|LT|L)\b", r"\1 L", texto, flags=re.I)
    texto = re.sub(r"\s[-–]\s*|\s*[-–]\s", " ", texto)
    palavras = texto.replace("(", " ").replace(")", " ").split()
    return " ".join(_palavra(p, i == 0) for i, p in enumerate(palavras))


# ---------- Leitura da planilha ----------

def _eh_cabecalho(medida, coluna_c) -> bool:
    return str(medida or "").strip() == "Medida" or str(coluna_c or "").strip().upper() == "CONTAGEM"


def ler_planilha(arquivo) -> list[dict]:
    """As linhas de alimentos e bebidas da aba de contagem, na ordem da planilha.

    Devolve {'secao', 'ordem', 'descricao', 'medida', 'bebida'}. Uma
    descrição repetida em duas seções (as aparas de carne e a calabresa
    aparecem na cozinha e de novo em "proteínas funcionários") entra só
    na primeira: a mesma prateleira contada duas vezes dobraria o estoque.
    """
    livro = openpyxl.load_workbook(arquivo, data_only=True, read_only=True)
    if ABA not in livro.sheetnames:
        raise ValueError(f"A planilha não tem a aba '{ABA}'.")

    linhas, vistas = [], set()
    secao, bebida = None, True
    for numero, linha in enumerate(livro[ABA].iter_rows(values_only=True), 1):
        descricao, medida, coluna_c = (list(linha) + [None] * 3)[:3]
        descricao = " ".join(str(descricao or "").split())
        if not descricao:
            continue
        if _eh_cabecalho(medida, coluna_c):
            secao = descricao
            if chave(secao) == chave(PRIMEIRA_SECAO_DE_ALIMENTOS):
                bebida = False
            if any(chave(secao).startswith(chave(fora)) for fora in SECOES_FORA):
                break
            continue
        if secao is None or secao == "+":
            continue
        if chave(descricao) in vistas:
            continue
        vistas.add(chave(descricao))
        linhas.append({
            "secao": secao,
            "ordem": numero,
            "descricao": descricao,
            "medida": " ".join(str(medida or "").split()),
            "bebida": bebida,
        })
    livro.close()
    return linhas


# ---------- Plano ----------

def _unidade_de_contagem(medida: str) -> str:
    medida = medida.strip()
    return MEDIDAS.get(medida.upper(), MEDIDAS.get(medida, medida.lower() or "un"))


def montar_plano(linhas: list[dict]) -> dict:
    """O que a importação faria, sem gravar nada.

    Devolve:
    - 'itens': cada linha com insumo, unidade do insumo e fator;
    - 'insumos_novos': {nome: unidade} dos insumos que ainda não existem;
    - 'a_definir': linhas cujo fator depende de um peso que falta;
    - 'problemas': o que impede a importação (linha de alimento sem
      mapeamento, unidade que não bate com a do insumo já cadastrado);
    - 'unidades_a_corrigir': {insumo: (unidade atual, unidade nova)} dos
      insumos cuja unidade mudou na planilha e que ainda não têm nenhum
      histórico, então podem trocar de unidade sem estragar nada.
    """
    conn = get_connection()
    existentes = {
        linha["nome"]: linha["unidade_medida"]
        for linha in conn.execute("SELECT nome, unidade_medida FROM insumos").fetchall()
    }
    # Insumo com qualquer número gravado na unidade antiga — compra,
    # contagem, produção, ficha, fator de nota fiscal — não pode trocar de
    # unidade: 2 barris virariam 2 litros. Sem nada disso, a troca é só o
    # rótulo, e é o caso do chopp, que mudou de barril para litro antes de
    # o sistema entrar em uso.
    com_historico = {
        linha["nome"] for linha in conn.execute(
            """SELECT i.nome FROM insumos i WHERE
                   EXISTS (SELECT 1 FROM compras x WHERE x.insumo_id = i.id)
                OR EXISTS (SELECT 1 FROM contagens_fisicas x WHERE x.insumo_id = i.id)
                OR EXISTS (SELECT 1 FROM producoes x WHERE x.insumo_id = i.id)
                OR EXISTS (SELECT 1 FROM producoes_consumo x WHERE x.insumo_id = i.id)
                OR EXISTS (SELECT 1 FROM ficha_tecnica x WHERE x.insumo_id = i.id)
                OR EXISTS (SELECT 1 FROM ficha_producao x
                           WHERE x.insumo_id = i.id OR x.producao_id = i.id)
                OR EXISTS (SELECT 1 FROM mapeamento_produtos_nfe x WHERE x.insumo_id = i.id)"""
        ).fetchall()
    }
    conn.close()

    itens, novos, a_definir, problemas, ignoradas = [], {}, [], [], []
    a_corrigir = {}
    for linha in linhas:
        unidade_contagem = _unidade_de_contagem(linha["medida"])
        k = chave(linha["descricao"])

        if linha["bebida"]:
            destino = _BEBIDAS_DA_COZINHA.get(k) or (
                nome_de_bebida(linha["descricao"]), 1, unidade_contagem
            )
        else:
            destino = _ALIMENTOS.get(k)
            if destino == IGNORAR:
                ignoradas.append(linha["descricao"])
                continue
            if destino is None:
                problemas.append(
                    f"'{linha['descricao']}' ({linha['secao']}) não tem insumo definido "
                    "em contagem_import.ALIMENTOS."
                )
                continue

        insumo, fator, unidade, conta_em = (tuple(destino) + (None,))[:4]
        unidade_contagem = conta_em or unidade_contagem
        if insumo in existentes:
            if existentes[insumo] != unidade and insumo not in com_historico:
                anterior = a_corrigir.setdefault(insumo, (existentes[insumo], unidade))
                if anterior[1] != unidade:
                    problemas.append(
                        f"'{insumo}' aparece em '{anterior[1]}' e em '{unidade}' na planilha."
                    )
                    continue
            elif existentes[insumo] != unidade:
                problemas.append(
                    f"'{linha['descricao']}' vai para '{insumo}', que está cadastrado em "
                    f"'{existentes[insumo]}', mas o fator foi pensado em '{unidade}'."
                )
                continue
        else:
            anterior = novos.setdefault(insumo, unidade)
            if anterior != unidade:
                problemas.append(
                    f"'{insumo}' aparece em '{anterior}' e em '{unidade}' na planilha."
                )
                continue

        item = {
            **linha,
            "unidade_contagem": unidade_contagem,
            "insumo": insumo,
            "unidade_insumo": unidade,
            "fator": fator,
        }
        itens.append(item)
        if fator is None:
            a_definir.append(item)

    return {
        "itens": itens,
        "insumos_novos": novos,
        "a_definir": a_definir,
        "ignoradas": ignoradas,
        "problemas": problemas,
        "unidades_a_corrigir": a_corrigir,
    }


def aplicar_plano(plano: dict) -> dict:
    """Grava o plano: cria os insumos que faltam e os itens da contagem.

    Tudo ou nada. Reimportar a mesma planilha não duplica: o item é
    achado pela descrição e atualizado. Um fator que o usuário já
    preencheu no app **não** é apagado por um "a definir" daqui — o
    número digitado por quem conhece o produto vale mais que o branco.
    """
    if plano["problemas"]:
        raise ValueError("A planilha tem problemas a resolver antes de importar.")

    conn = get_connection()
    try:
        for nome, unidade in plano["insumos_novos"].items():
            conn.execute(
                "INSERT INTO insumos (nome, unidade_medida, estoque_minimo) VALUES (?, ?, 0)",
                (nome, unidade),
            )
        for nome, (_, unidade) in plano.get("unidades_a_corrigir", {}).items():
            conn.execute(
                "UPDATE insumos SET unidade_medida = ? WHERE nome = ?", (unidade, nome)
            )
        ids = {
            linha["nome"]: linha["id"]
            for linha in conn.execute("SELECT id, nome FROM insumos").fetchall()
        }

        criados = atualizados = 0
        for item in plano["itens"]:
            atual = conn.execute(
                "SELECT id, fator_conversao FROM itens_contagem WHERE descricao = ?",
                (item["descricao"],),
            ).fetchone()
            fator = item["fator"]
            if atual is None:
                conn.execute(
                    """INSERT INTO itens_contagem
                           (descricao, secao, ordem, unidade_contagem, insumo_id, fator_conversao)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (item["descricao"], item["secao"], item["ordem"],
                     item["unidade_contagem"], ids[item["insumo"]], fator),
                )
                criados += 1
            else:
                if fator is None:
                    fator = atual["fator_conversao"]
                conn.execute(
                    """UPDATE itens_contagem
                          SET secao = ?, ordem = ?, unidade_contagem = ?,
                              insumo_id = ?, fator_conversao = ?
                        WHERE id = ?""",
                    (item["secao"], item["ordem"], item["unidade_contagem"],
                     ids[item["insumo"]], fator, atual["id"]),
                )
                atualizados += 1
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return {
        "insumos_criados": len(plano["insumos_novos"]),
        "unidades_corrigidas": len(plano.get("unidades_a_corrigir", {})),
        "itens_criados": criados,
        "itens_atualizados": atualizados,
    }
