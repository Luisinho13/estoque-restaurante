"""
bar_import.py
Lê as planilhas de fichas do bar e transforma cada aba em drink (prato do
setor bar) ou em preparo (produção do bar: caldas, xarope, espuma,
chocolate quente), no mesmo formato de plano da ficha da cozinha. A tela
de importação mostra a prévia e `ficha_import.aplicar_plano` grava.

São duas planilhas, e as duas passam por aqui:

- **"Ficha tecnica bar.xlsx"** (174 abas): drinks, doses e garrafas de
  destilado, cafés, sucos, jarras e combos. É a que vale (escolha do
  usuário em 02/10/2026): nos 18 drinks em que as duas divergem, a ficha
  importada por último substitui a outra, e esta é a mais nova.
- **"Preparos bar villa.xlsx"** (30/09/2026): os mesmos drinks, e a única
  com as caldas, o xarope, a espuma e o GT Morango.

Pedido do usuário em 30/09/2026: a saída do bar passa a seguir a ficha
técnica, como a da cozinha. O que muda em relação à cozinha:

1. **A dose está em litro, e a garrafa é contada em garrafa.** A planilha
   escreve "Kg" ou "ML" mas o número é litro (0,05 de gin = 50 ml). O
   estoque conta destilado em garrafa, refrigerante em lata. A conversão
   usa o volume escrito no nome do insumo ("Gin Bombay 750 ml" → 0,05 ÷
   0,75 = 0,067 garrafa). Onde o nome não diz o volume, a quantidade entra
   como está e vira aviso.

2. **Garrafa e combo vendem a garrafa inteira.** A aba "Nicks Gf" leva 1
   de gin: é 1 garrafa, e não 1 litro. Todo drink cujo nome termina em
   "garrafa" ou "combo" desconta a garrafa inteira. Item marcado como
   unidade ("Und", "Unidade") com 1 ou mais é contado em unidade: 6
   Heineken no balde são 6 garrafas.

3. **Os nomes são marcas.** "Gin Bombay", "Jack Daniel n07", "Tônica":
   INGREDIENTES traduz cada grafia para o insumo que a contagem já criou
   (um por produto). Onde a tradução é palpite meu, sai em `avisos`.

4. **A planilha tem sobras de cópia.** Abas repetidas ("Planilha5" é o
   "black label Ds"), a batata noisete na aba "Fresh Ginger", o
   rendimento 2,33 do modelo. Essas coisas são ignoradas e listadas, não
   lidas como verdade.

O plano também traz o que não vem da planilha:

- **Refrigerantes** (pedido do usuário em 02/10/2026): cada refrigerante,
  energético e tônica da folha de contagem vira um prato do bar que
  desconta 1 unidade. A Coca lata e a Coca Zero lata ficam de fora.
- **Mapeamento da Zig**: produto da Zig que hoje está sem prato e que é um
  desses pratos (pelo nome, ou por `ZIG`) passa a apontar para ele.
- **Conde de Campos**: não é mais vendido (02/10/2026). A produção
  "Conde de Campos (lote)", criada pela importação do Preparos, sai.
- **O que a importação antiga deixou** (a *Ficha tecnica bar* foi
  importada no real em 01/10 pelo importador de antes, que dava ao drink o
  nome da aba e criava um insumo em litro para cada grafia que não
  conhecia): o prato com nome de aba é **renomeado** para o nome novo, e
  fica com as vendas e o mapeamento da Zig dele; o de aba repetida sai,
  se não tiver venda nem Zig; e o insumo que nada mais usa depois da
  importação, sem histórico nenhum, sai também.

Nada aqui grava: `montar_plano()` devolve o que seria feito, e
`gravar_extras(conn, plano)` grava a parte que só o bar tem, dentro da
transação de `ficha_import.aplicar_plano`.
"""

import re

import openpyxl

from database import get_connection
from ficha_import import chave

SETOR = "bar"
DOSE = 0.05   # 1 dose de destilado, em litro

# Tudo o que a leitura procura numa aba fica nas primeiras linhas. As abas
# têm dois formatos (o da cozinha, com 17 linhas de ingrediente, e um curto,
# com as linhas que a receita usa) e metade delas está deslocada uma coluna:
# os campos são achados pelo rótulo, não pela posição.
LINHAS_LIDAS = 45
COLUNAS_LIDAS = 16
MAXIMO_DE_INGREDIENTES = 25
DESLOCA_UNIDADE = 2      # da coluna "Ingredientes" até a da unidade
DESLOCA_QUANTIDADE = 3   # e até a do peso líquido
RENDIMENTO_DO_MODELO = 2.33

# ---------- Abas que são preparo, não drink ----------
# Chave: aba por `chave()`. Valor: nome da produção no sistema e unidade.
PREPAROS = {
    "calda de amora": ("Calda de amora", "l"),
    "calda de framboesa": ("Calda de framboesa", "l"),
    "xarope simples": ("Xarope simples", "l"),
    "espuma de gengibre": ("Espuma de gengibre", "l"),
    # Panela de 25,7 kg que rende 128 xícaras de 0,2 kg.
    "chocolate": ("Chocolate quente", "kg"),
}

# Preparo que também é vendido sozinho: o prato desconta uma porção dele.
PREPAROS_VENDIDOS = {
    "chocolate": ("Chocolate Quente", 0.2),
}

# Produção que saiu do cardápio: a importação a exclui, com a receita.
PRODUCOES_QUE_SAIRAM = {
    "Conde de Campos (lote)": "o Conde de Campos não é mais vendido",
}

# Aba que não entra, e por quê. Cópia repetida vale a primeira.
ABAS_IGNORADAS = {
    "conde de campos": "não é mais vendido",
    "dark n stormy": "não é mais vendido (usuário, 02/10/2026)",
    "manhattan": "não é mais vendido (usuário, 02/10/2026)",
    "planilha12": "repete a aba 'Jack Fire'",
    "planilha5": "repete a aba 'black label Ds'",
    "gin tanqueray": "é uma cópia incompleta de 'Gin Tanqueray Tropical'",
    "aguaardente seleta": "repete a aba 'Seleta Ds'",
    "velho barreiro": "repete a aba 'Velho barreiro Ds'",
    "boazinha": "repete a aba 'Boazinha Ds'",
    "red label": "repete a aba 'Red Label DS'",
    "smirnoff vodka": "repete a aba 'Smirnorf Ds'",
    "steinhaeger ds": "repete a aba 'Schilite Ds'",
    "befeeter gf": "repete a aba 'Beefeter Gf'",
    "suco abacaxi": ("tem os números da 'JARRA ABACAXI' (0,6 kg de abacaxi) com o "
                     "nome do suco: parece cópia da jarra"),
}

# Nome do drink no sistema. Os 46 drinks que já existiam mantêm o nome que
# a importação do Preparos deu, para a ficha nova substituir a antiga em vez
# de criar outro prato. Aba que não está aqui fica com o próprio nome.
NOMES_DE_DRINK = {
    # drinks
    "gin tonica frutas vermelhas": "Gin Tônica Frutas Vermelhas",
    "gt morango": "Gin Tônica Morango",
    "gt bombay": "Gin Tônica Morango",
    "gt laranja": "Gin Tônica Laranja",
    "gin tonica": "Gin Tônica",
    "caipirinha de limao": "Caipirinha de Limão",
    "sex on the beach": "Sex on the Beach",
    "campari tonic": "Campari Tônica",
    "dark n stormy": "Dark N Stormy",
    "j'adore": "J'Adore",
    "clericot jarra": "Clericot Jarra",
    "sangria jarra": "Sangria Jarra",
    "aperol spritz": "Aperol Spritz",
    "jarra de aperol": "Aperol Spritz Jarra",
    "coquetel de frutas": "Coquetel de Frutas",
    "coquetel de frutas sem alcool": "Coquetel de Frutas sem Álcool",
    "gin tanqueray tropical": "Gin Tanqueray Tropical",
    "soda italiana": "Soda Italiana",
    "suco de tomate": "Suco de Tomate Temperado",
    "vinho do porto": "Vinho do Porto",
    "box suave": "Vinho Suave Taça",
    "balde heineken 6 und": "Balde Heineken 6 un",
    "chopp amstel promo": "Chopp Amstel Promo",
    "chopp heineken": "Chopp Heineken",
    # cafés e chocolate
    "cafe c petifour": "Café com Petit Four",
    "capuccino": "Cappuccino",
    "chocolate com conhaque": "Chocolate com Conhaque",
    # sucos e jarras (o nome é o da Zig)
    "suco de abacaxi c hortela": "Suco de Abacaxi com Hortelã",
    "suco de abacaxi": "Suco de Abacaxi",
    "suco de melancia": "Suco de Melancia",
    "suco de limao": "Suco de Limão",
    "suco de maracuja": "Suco de Maracujá",
    "suco de morango": "Suco de Morango",
    "suco de laranja": "Suco de Laranja",
    "suco de laranja c morango": "Suco de Laranja com Morango",
    "jarra suco de limao": "Jarra Suco de Limão",
    "jarra laranja": "Jarra Suco de Laranja",
    "jarra melancia": "Jarra Suco de Melancia",
    "jarra maracuja": "Jarra Suco de Maracujá",
    "jarra morango": "Jarra Suco de Morango",
    "jarra abacaxi": "Jarra Suco de Abacaxi com Hortelã",
    "planilha3": "Jarra Suco de Laranja com Morango",
    # doses, garrafas e combos
    "balena": "Licor Ballena dose",
    "balena gf": "Licor Ballena garrafa",
    "licor 43": "Licor 43 dose",
    "licor 43 gf": "Licor 43 garrafa",
    "licor bailys ds": "Licor Baileys dose",
    "bailys gf": "Licor Baileys garrafa",
    "amarula": "Licor Amarula dose",
    "amarula gf": "Licor Amarula garrafa",
    "tequila oro": "Tequila José Cuervo Ouro dose",
    "tequila oro gf": "Tequila José Cuervo Ouro garrafa",
    "tequila prata": "Tequila José Cuervo Prata dose",
    "tequila prata gf": "Tequila José Cuervo Prata garrafa",
    "don julio repousado": "Tequila Don Julio Reposado dose",
    "don julio gf": "Tequila Don Julio Reposado garrafa",
    "don julio prata": "Tequila Don Julio Prata dose",
    "don julio prata gf": "Tequila Don Julio Prata garrafa",
    "busca vida": "Cachaça Busca Vida dose",
    "busca vida gf": "Cachaça Busca Vida garrafa",
    "seleta ds": "Cachaça Seleta dose",
    "seleta gf": "Cachaça Seleta garrafa",
    "boazinha ds": "Cachaça Boazinha dose",
    "boazinha gf": "Cachaça Boazinha garrafa",
    "ypioca ds": "Cachaça Ypióca dose",
    "ypioca gf": "Cachaça Ypióca garrafa",
    "velho barreiro ds": "Cachaça Velho Barreiro dose",
    "velho barreiro gf": "Cachaça Velho Barreiro garrafa",
    "campari": "Campari dose",
    "campari gf": "Campari garrafa",
    "domeq ds": "Conhaque Domecq dose",
    "domeq gf": "Conhaque Domecq garrafa",
    "fundador (ds)": "Conhaque Fundador dose",
    "fundador gf": "Conhaque Fundador garrafa",
    "remy martin": "Conhaque Rémy Martin dose",
    "remy gf": "Conhaque Rémy Martin garrafa",
    "bombay ds": "Gin Bombay dose",
    "gin bombay combo": "Gin Bombay combo",
    "beefeater ds": "Gin Beefeater dose",
    "beefeter gf": "Gin Beefeater garrafa",
    "tanqueray ds": "Gin Tanqueray dose",
    "tanqueray combo": "Gin Tanqueray combo",
    "nicks ds": "Gin Nicks dose",
    "nicks gf": "Gin Nicks garrafa",
    "absolut ds": "Vodka Absolut dose",
    "absolut gf": "Vodka Absolut garrafa",
    "grey goose ds": "Vodka Grey Goose dose",
    "grey goose combo": "Vodka Grey Goose combo",
    "sky ds": "Vodka Sky dose",
    "sky gf": "Vodka Sky garrafa",
    "vodk sky gf": "Vodka Sky combo",
    "smirnorf ds": "Vodka Smirnoff dose",
    "smirnorf gf": "Vodka Smirnoff garrafa",
    "schilite ds": "Steinhaeger Schlichte dose",
    "schilite gf": "Steinhaeger Schlichte garrafa",
    "becosa": "Steinhaeger Becosa dose",
    "becosa gf": "Steinhaeger Becosa garrafa",
    "black label ds": "Whisky Black Label dose",
    "black label gf": "Whisky Black Label garrafa",
    "black label combo": "Whisky Black Label combo",
    "blond ds": "Whisky Blond dose",
    "blond gf": "Whisky Blond garrafa",
    "red label ds": "Whisky Red Label dose",
    "red label gf": "Whisky Red Label garrafa",
    "gold label ds": "Whisky Gold Label dose",
    "gold label gf": "Whisky Gold Label garrafa",
    "blue label": "Whisky Blue Label dose",
    "blue label gf": "Whisky Blue Label garrafa",
    "jack daniels 07": "Whisky Jack Daniel's dose",
    "jack daniels 07 gf": "Whisky Jack Daniel's garrafa",
    "jack honey.": "Whisky Jack Honey dose",
    "jack honey gf": "Whisky Jack Honey garrafa",
    "jack fire": "Whisky Jack Fire dose",
    "jack fire gf": "Whisky Jack Fire garrafa",
    "old parr ds": "Whisky Old Parr dose",
    "old par gf": "Whisky Old Parr garrafa",
    "buchanas ds": "Whisky Buchanan's dose",
    "buchanas gf": "Whisky Buchanan's garrafa",
    "chivas": "Whisky Chivas Regal dose",
    "chivas combo": "Whisky Chivas Regal combo",
    "dewars ds": "Whisky Dewar's dose",
    "dewars combo": "Whisky Dewar's combo",
}

# ---------- De grafia da planilha para insumo do sistema ----------
# Chave: o ingrediente como está escrito (comparado por `chave()`). Valor:
# o insumo no sistema, com o nome exato que a contagem criou. Os que são
# produção do bar apontam para o nome em PREPAROS.
INGREDIENTES = {
    # gin
    "gin bombay": "Gin Bombay 750 ml",
    "gin beefeater": "Gin Beefeater 750 ml",
    "gin befeeter": "Gin Beefeater 750 ml",
    "beefeater": "Gin Beefeater 750 ml",
    "gin nicks": "Gin Nicks 1000 ml",
    "gin tanqueray": "Gin Tanqueray 750 ml",
    "tanqueray": "Gin Tanqueray 750 ml",
    # vodka
    "vodka grey goose": "Vodka Grey Goose 750 ml",
    "grey goose": "Vodka Grey Goose 750 ml",
    "vodka absolut": "Vodka Absolut 1000 ml",
    "vodka smirnoff": "Vodka Smirnoff 1000 ml",
    "vodka smirnorf": "Vodka Smirnoff 1000 ml",
    "smirnoff": "Vodka Smirnoff 1000 ml",
    "vodka sky": "Vodka Sky 980 ml",
    # whisky
    "whisky jack daniels": "Whisky Jack Daniels N07 1000 ml",
    "jack daniels n07": "Whisky Jack Daniels N07 1000 ml",
    "jack daniel n07": "Whisky Jack Daniels N07 1000 ml",
    "jack daniel honey": "Whisky Jack Daniels Honey 1000 ml",
    "jack daniels fire": "Whisky Jack Daniels Fire 1000 ml",
    "black label": "Whisky Johnnie Walker Black Label 1000 ml",
    "whisky black label": "Whisky Johnnie Walker Black Label 1000 ml",
    "whisky blond": "Whisky Johnnie Walker Blond 1000 ml",
    "blond label": "Whisky Johnnie Walker Blond 1000 ml",
    "red label": "Whisky Johnnie Walker Red Label 1000 ml",
    "whisky red label": "Whisky Johnnie Walker Red Label 1000 ml",
    "whisky gold label": "Whisky Johnnie Walker Gold Label 1000 ml",
    "blue label": "Whisky Johnnie Walker Blue Label 1000 ml",
    "buchanans": "Whisky Buchanas 12 Anos",
    "buchanan's": "Whisky Buchanas 12 Anos",
    "old parr": "Whysky Old Par 1000 ml",
    "chivas": "Whisky Chivas Regal 12 Anos 1000 ml",
    "whisky dewars 12 anos": "Whisky Dewars 1000 ml",
    # cachaça, tequila, rum, conhaque, steinhaeger
    "cachaca": "Cachaça",
    "cachaca velho barreiro": "Cachaça Velho Barreiro 910 ml",
    "velho barreiro": "Cachaça Velho Barreiro 910 ml",
    "busca vida": "Cachaça Busca Vida 750 ml",
    "seleta": "Cachaça Seleta 1 Litro",
    "boazinha": "Cachaça Boazinha 600 ml",
    "ypioca": "Cachaça Ypioca 750 ml",
    "cachaca balsamo": "Cachaça Bálsamo",
    "tequila jose cuervo": "Tequila Prata Jose Cuervo 750 ml",
    "tequila prata": "Tequila Prata Jose Cuervo 750 ml",
    "tequila oro": "Tequila Ouro Jose Cuervo 750 ml",
    "tequila don julio prata": "Tequila Don Julio Prata 750 ml",
    "don julio prata": "Tequila Don Julio Prata 750 ml",
    "don julio repousado": "Tequila Don Julio Ouro 750 ml",
    "rum": "Rum Bacardi Ouro 980 ml",
    "rum bacardi": "Rum Bacardi Carta Blanca Prata 980 ml",
    "rum bacardi prata": "Rum Bacardi Carta Blanca Prata 980 ml",
    "rum carta blanca": "Rum Bacardi Carta Blanca Prata 980 ml",
    "conhaque remi martin": "Conhaque Remi Martin 700 ml",
    "remy martin": "Conhaque Remi Martin 700 ml",
    "conhaque fundador": "Conhaque Fundador 750 ml",
    # O Domecq é o conhaque que a cozinha também usa (contagem_import).
    "domeq": "Conhaque",
    "steinhaeger schlite": "Steinhaeger Importado 700 ml",
    "schilite": "Steinhaeger Importado 700 ml",
    "becosa": "Steinhaeger Becosa 980 ml",
    # licores, vermutes, bitters, vinhos
    "campari": "Campari 900 ml",
    "drambuie": "Licor Drambui 750 ml",
    "ramazotti": "Ramazzoti Amaro 700 ml",
    "ramazotti rosato": "Ramazzoti Rosato 700 ml",
    "lilliet blanc": "Licor Liliet Blanc 750 ml",
    "lillet blanc": "Licor Liliet Blanc 750 ml",
    "lilliet": "Licor Liliet Blanc 750 ml",
    "triple sec": "Licor Cointreau 700 ml",
    "cointreau": "Licor Cointreau 700 ml",
    "punt e mes": "Put e Mes 750 ml",
    "dry martini": "Martini Dry 750 ml",
    "amarula": "Licor Amarula 750 ml",
    "balena": "Licor Ballena 750 ml",
    "licor 43": "Licor 43 700 ml",
    "licor bailys": "Licor Baileys 750 ml",
    "aperol": "Licor Aperol 750 ml",
    "saque azuma kirin seco": "Saque Azuma Kirin Seco 740 ml",
    "monin gengibre": "Licor Monin Gengibre 700 ml",
    "monin framboesa": "Licor Monin Framboesa 700 ml",
    "monin grapefruit": "Licor Monin Grapefruit 700 ml",
    "monin granadine": "Licor Monin Granadine 700 ml",
    "monin morango": "Licor Monin Morango 700 ml",
    "stock peach": "Stock Peach 720 ml",
    "angostura": "Agostura Tradicional 200 ml",
    "angostura laranja": "Agostura Orange Bitters 100 ml",
    "bitter laranja": "Agostura Orange Bitters 100 ml",
    "jotape suave box 3lt": "Vinho Jotapê Suave Box 3 L",
    "jota pe box suave": "Vinho Jotapê Suave Box 3 L",
    "vinho braco ceia farta": "Box Ceia Farta Branco 3 L",
    "espumante primicias": "Primicias Demi Sec",
    "cave santa marta": "Cave de Santa Marta Porto Rubi 750 ml",
    # chopp e cerveja
    "chopp amstel": "Chopp Amstel",
    "chopp heineken": "Chopp Heineken",
    "heineken 330ml": "Heineken Lager 330 ml",
    # refrigerantes, águas e sucos
    "tonica": "Tonica Schweppes Original Lata 350 ml",
    "sprite": "Sprite Lata 350 ml",
    "citrus": "Schweppes Citrus Original Lata 350 ml",
    "monster mango loco": "Monster Mango Loco Lata 473 ml",
    "agua com gas": "Água com Gás Cristal 350 ml VIP",
    "agua c gas": "Água com Gás Cristal 350 ml VIP",
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
    "abacaxi": "Abacaxi",
    "melancia": "Melancia",
    "maracuja": "Polpa de maracujá",
    "maca": "Maçã",
    "laranja": "Laranja",
    "laranja bahia": "Laranja",
    "laranja fatia": "Laranja",
    "fatia laranja": "Laranja",
    "rodela laranja": "Laranja",
    "twist de laranja": "Laranja",
    "zest de laranja": "Laranja",
    "limao": "Limão",
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
    "canela em po": "Canela",
    "cravo": "Cravo",
    "gengibre": "Gengibre",
    "zimbro": "Zimbro",
    "sal": "Sal",
    "azeitona": "Azeitona",
    "tabasco": "Molho de pimenta",
    "pimenta tabasco": "Molho de pimenta",
    "molho ingles": "Molho inglês",
    "raspas de chocolate": "Chocolate",
    "chocolate 30%": "Chocolate",
    "chocolate 70%": "Chocolate",
    "creme de leite": "Creme de leite",
    "leite integral": "Leite",
    "semente de cumaru": "Cumaru",
    "cafe": "Café",
    "cafe expresso": "Café",
    "cafe capsula": "Cápsula de café expresso",
    "capuccino": "Cápsula de cappuccino",
    "cha frutas vermelhas": "Chá de frutas vermelhas",
    "hibisco": "Hibisco",
    "emulsificante para sorvete": "Emulsificante",
    # preparos do bar
    "xarope": "Xarope simples",
    "xarope acucar": "Xarope simples",
    "xarope de acucar": "Xarope simples",
    "xarope de framboesa": "Calda de framboesa",
    "xarope frutas vermelhas": "Calda de framboesa",
    "calda de amora": "Calda de amora",
    "espuma de gengibre": "Espuma de gengibre",
    "espuma moscow mule": "Espuma de gengibre",
    "chocolate": "Chocolate quente",
}
_INGREDIENTES = {chave(k): v for k, v in INGREDIENTES.items()}

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
# Buchanan's e Primicias: 750 ml (usuário, 02/10/2026).
VOLUMES = {
    "Vinho Jotapê Suave Box 3 L": 3.0,
    "Whisky Buchanas 12 Anos": 0.75,
    "Primicias Demi Sec": 0.75,
}

# Peso médio de 1 unidade (ou 1 maço), em kg, do que a contagem conta por
# unidade e a ficha do bar pesa em kg (usuário, 02/10/2026). 0,25 kg de
# abacaxi no suco é meio abacaxi; 15 g de hortelã são 0,15 maço.
PESOS_POR_UNIDADE = {
    "Abacaxi": 0.5,
    "Melancia": 15.0,
    "Hortelã": 0.1,
}

# Dose fixa por drink, em litro, que vale qualquer que seja o número da
# planilha. A planilha punha a Angostura em ml de dose (20 a 30 ml, 10% a
# 15% da garrafa por drink); são gotas: 2 ml por drink (usuário, 02/10/2026).
DOSES_FIXAS = {
    "angostura": 0.002,
    "angostura laranja": 0.002,
    "bitter laranja": 0.002,
}

# Insumo contado em embalagem, vendido por unidade: 1 cápsula é 1/10 da
# caixa de 10.
UNIDADES_POR_EMBALAGEM = {
    "Cápsula de café expresso": 10,
    "Cápsula de cappuccino": 10,
}

# Multiplicador para insumo contado por unidade: 1 dose da planilha em litro
# vira quantas unidades. O café expresso vem como 0,03 (30 ml); no estoque,
# café é contado por unidade (uma dose). "1 UND" de chocolate é uma xícara,
# 0,2 kg da panela de chocolate quente.
FATORES_POR_UNIDADE = {
    "cafe expresso": 1 / 0.03,
    "chocolate": 0.2,
}

# Linha que não é da receita: sobra de cópia de outra ficha.
LINHAS_IGNORADAS = {
    ("fresh ginger", "batata noisete"):
        "a linha de 0,2 kg de batata noisete da aba 'Fresh Ginger' é sobra de cópia "
        "da ficha da cozinha e foi ignorada",
}

# Quantidade que a planilha escreveu errado, com a correção e o motivo.
QUANTIDADES_CORRIGIDAS = {
    ("nicks ds", "gin nicks"): (
        0.05, "'Nicks Ds' diz 0,005 L de gin (5 ml) e o peso bruto da mesma linha diz "
              "0,05: usei a dose de 50 ml"),
    ("tanqueray ds", "gin tanqueray"): (
        0.05, "'Tanqueray Ds' diz 0,005 L de gin (5 ml); a dose das outras abas é "
              "0,05: usei 50 ml"),
}

SEM_ESTOQUE = {"agua quente", "agua filtrada"}
# O que a receita cita e não é um insumo só: fica de fora da ficha.
FORA_DA_FICHA = {
    "frutas": "a fruta varia",
    "frutas total": "a fruta varia",
    "monin sabores": "o sabor do xarope varia",
    "energetico": "o energético é o que o cliente escolhe",
    "energetico red bull": "o sabor do Red Bull é o que o cliente escolhe",
    "energetico monster": "o sabor do Monster é o que o cliente escolhe",
    "petifour": "o petit four não é item de estoque",
}

# Traduções que são interpretação minha, não leitura. Viram aviso.
MAPEAMENTOS_ASSUMIDOS = {
    "triple sec": "o triple sec é o Cointreau (não há outro na contagem)",
    "rum": "o rum sem marca do Dark N Stormy é o Bacardi Ouro",
    "tequila jose cuervo": "a tequila José Cuervo da margarita é a prata",
    "agua com gas": "a água com gás é a Cristal 350 ml",
    "agua c gas": "a água com gás é a Cristal 350 ml",
    "soda": "a soda é a água com gás Cristal 350 ml",
    "ginger": "'Ginger' é ginger ale, que não está na contagem: entrou como insumo novo",
    "xarope de framboesa": "o xarope de framboesa é a calda de framboesa feita no bar",
    "xarope frutas vermelhas": ("o xarope de frutas vermelhas da gin tônica é a calda de "
                                "framboesa feita no bar"),
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
    "don julio repousado": "o Don Julio Reposado é o Don Julio Ouro da contagem",
    "steinhaeger schlite": "o steinhaeger Schlichte é o 'Steinhaeger Importado' da contagem",
    "schilite": "o steinhaeger Schlichte é o 'Steinhaeger Importado' da contagem",
    "espumante primicias": "o espumante do Aperol é o Primicias Demi Sec",
    "cafe capsula": "o café do 'Café com Petit Four' é a cápsula de expresso",
}

# Um drink que usa bem mais de um insumo que os outros drinks (4× a
# mediana, com ao menos 3 drinks usando) provavelmente tem erro de digitação.
FOLGA_DA_MEDIANA = 4

# Bitter vai em gotas. Acima disto (em litro, por drink) a planilha
# provavelmente escreveu ml onde queria gotas.
BITTER_MAXIMO_POR_DRINK = 0.01

# O que a leitura das abas, uma a uma, encontrou de estranho e que a regra
# geral não pega. É leitura minha da receita, não correção: a ficha entra
# como a planilha diz, e isto aparece para conferência.
AVISOS_DE_ABA = {
    "espuma de gengibre": "'Espuma de gengibre' leva 1 kg de emulsificante e 1 L de citrus "
                          "por receita: confira se o emulsificante não é em gramas.",
    "chocolate com conhaque": "'Chocolate com Conhaque' leva 1 xícara de chocolate quente: "
                              "usei a porção de 0,2 kg da aba 'CHOCOLATE'.",
}

# ---------- Refrigerantes e Zig ----------

# Seções da folha de contagem cujas linhas viram prato que desconta 1
# unidade, e linhas avulsas de outras seções (as tônicas ficam nas águas).
SECOES_DE_REFRIGERANTE = ("refrigerante",)
LINHAS_DE_REFRIGERANTE = ("tonica schweppes",)

# Nome do produto na Zig → prato, quando não é o mesmo nome. Os outros
# produtos sem prato são ligados se o nome for igual ao de um prato do bar.
ZIG = {
    "Coca-Cola Perfeita Original": "Coca Cola KS 250 ml",
    "Coca-Cola Perfeita Original S/ Açúcar": "Coca Cola KS sem Açucar 250 ml",
    "Fanta Guaraná": "Fanta Guaraná Lata 350 ml",
    "Fanta Guaraná Zero Açúcar": "Fanta Guaraná Zero Lata 350 ml",
    "Fanta Laranja": "Fanta Laranja Lata 350 ml",
    "Fanta Laranja Zero Açúcar": "Fanta Laranja Zero Lata 350 ml",
    "Fanta Maracujá": "Fanta Maracujá Lata 350 ml",
    "Fanta Uva": "Fanta Uva Lata 350 ml",
    "Sprite": "Sprite Lata 350 ml",
    "Sprite Zero Açúcar": "Sprite Zero Lata 350 ml",
    "Sprite Lemon Fresh": "Sprite Lemon Fresch 510 ml",
    "Schweppes Citrus Original": "Schweppes Citrus Original Lata 350 ml",
    "Schweppes Citrus Leve": "Schweppes Citrus Leve sem Açucar Lata 350 ml",
    "Schweppes Tônica": "Tonica Schweppes Original Lata 350 ml",
    "Schweppes Tônica Sem Açucar": "Tonica Schweppes sem Açucar Lata 350 ml",
    "Monster Green zero 473 ml": "Monster Juice Green Lata 473 ml Zero",
    "Sangria Taça": "Sangria",
    "Aperol Spritz Taça": "Aperol Spritz",
    "Coquetel de Frutas s/ Álcool": "Coquetel de Frutas sem Álcool",
    "Jarra Abacaxi c/ Hortelã": "Jarra Suco de Abacaxi com Hortelã",
    "Licor 43 (DS)": "Licor 43 dose",
}
_ZIG = {chave(k): v for k, v in ZIG.items()}


def _limpa(valor) -> str | None:
    if valor is None:
        return None
    texto = " ".join(str(valor).split()).strip()
    return texto or None


def _numero(valor) -> float | None:
    if isinstance(valor, bool):
        return None
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
    linhas = [list(linha) + [None] * COLUNAS_LIDAS for linha in ws.iter_rows(
        min_row=1, max_row=LINHAS_LIDAS, max_col=COLUNAS_LIDAS, values_only=True)]

    def achar(teste):
        """(linha, coluna) da primeira célula de texto que passa no teste."""
        for i, linha in enumerate(linhas):
            for j, celula in enumerate(linha):
                texto = _limpa(celula)
                if texto and teste(texto):
                    return i, j
        return None

    def depois_de(posicao, numero=False):
        """O primeiro valor à direita do rótulo, na mesma linha."""
        if posicao is None:
            return None
        i, j = posicao
        for celula in linhas[i][j + 1:]:
            valor = _numero(celula) if numero else _limpa(celula)
            if valor is not None:
                return valor
        return None

    cabecalho = achar(lambda t: t == "Ingredientes")
    if cabecalho is None:
        return None
    topo, base = cabecalho

    ingredientes = []
    for linha in linhas[topo + 1: topo + 1 + MAXIMO_DE_INGREDIENTES]:
        item = _limpa(linha[base])
        if not item:
            continue
        if item.lower().startswith("unidade:"):
            break
        quantidade = _numero(linha[base + DESLOCA_QUANTIDADE])
        if quantidade is None or quantidade <= 0:
            continue
        ingredientes.append({
            "nome": item,
            "unidade_declarada": _limpa(linha[base + DESLOCA_UNIDADE]),
            "quantidade": quantidade,
        })
    if not ingredientes:
        return None

    porcoes = achar(lambda t: t.startswith("Nº de Porç"))
    abaixo = None
    if porcoes is not None and porcoes[0] + 1 < len(linhas):
        abaixo = _numero(linhas[porcoes[0] + 1][porcoes[1]])

    aba = ws.title.strip()
    return {
        "aba": aba,
        "nome": depois_de(achar(lambda t: t.startswith("Nome Técnico"))) or aba,
        "nome_venda": depois_de(achar(lambda t: t.startswith("Nome de Venda"))) or aba,
        "rendimento": depois_de(achar(lambda t: t.startswith("RENDIMENTO DA RECEITA")), True),
        "porcoes": abaixo or 1.0,
        "ingredientes": ingredientes,
    }


# ---------- Montagem do plano ----------

def e_preparo(receita: dict) -> bool:
    return chave(receita["aba"]) in PREPAROS


def nome_do_drink(receita: dict) -> str:
    return NOMES_DE_DRINK.get(chave(receita["aba"]), receita["aba"].strip())


def vende_a_garrafa(prato: str) -> bool:
    """O drink é a garrafa inteira (garrafa, combo), e não uma dose."""
    return prato.endswith((" garrafa", " combo"))


def montar_plano(receitas: list[dict]) -> dict:
    """O plano de gravação, no formato de `ficha_import.montar_plano`.

    Drinks viram pratos do setor bar; preparos viram produções do bar.
    Toda quantidade sai na unidade do insumo no estoque. Além do formato da
    cozinha, o plano traz 'zig' (produtos da Zig a ligar) e 'remover'
    (produções que saíram do cardápio), que `gravar_extras` grava.
    """
    avisos = []
    # Insumo cuja quantidade não deu para converter: {(insumo, unidade): [(aba, q)]}.
    # Vira um aviso por insumo, não um por drink.
    sem_conversao = {}
    doses_fixadas = []   # bitter da planilha trocado pela dose do bar
    conn = get_connection()
    existentes = {
        d["nome"]: {"unidade": d["unidade_medida"], "tipo": d["tipo"]}
        for d in conn.execute("SELECT nome, unidade_medida, tipo FROM insumos").fetchall()
    }
    ja_tem_prato = {d["nome"] for d in conn.execute("SELECT nome FROM pratos").fetchall()}
    por_chave = {}
    for nome in sorted(existentes):
        por_chave.setdefault(chave(nome), nome)
    do_bar = {
        d["nome"]: dict(d) for d in conn.execute(
            """SELECT p.nome,
                      EXISTS (SELECT 1 FROM ficha_tecnica x WHERE x.prato_id = p.id) AS ficha,
                      EXISTS (SELECT 1 FROM vendas_diarias x WHERE x.prato_id = p.id) AS venda,
                      EXISTS (SELECT 1 FROM mapeamento_produtos_zig x WHERE x.prato_id = p.id)
                          AS zig
                 FROM pratos p WHERE p.setor = 'bar'"""
        ).fetchall()
    }
    citados_por = {}
    for d in conn.execute(
        """SELECT i.nome AS insumo, p.nome AS prato
             FROM ficha_tecnica f
             JOIN insumos i ON i.id = f.insumo_id JOIN pratos p ON p.id = f.prato_id"""
    ).fetchall():
        citados_por.setdefault(d["insumo"], set()).add(d["prato"])
    sem_historico = {
        d["nome"] for d in conn.execute(
            """SELECT i.nome FROM insumos i WHERE NOT (
                   EXISTS (SELECT 1 FROM compras x WHERE x.insumo_id = i.id)
                OR EXISTS (SELECT 1 FROM contagens_fisicas x WHERE x.insumo_id = i.id)
                OR EXISTS (SELECT 1 FROM producoes x WHERE x.insumo_id = i.id)
                OR EXISTS (SELECT 1 FROM producoes_consumo x WHERE x.insumo_id = i.id)
                OR EXISTS (SELECT 1 FROM ficha_producao x
                           WHERE x.producao_id = i.id OR x.insumo_id = i.id)
                OR EXISTS (SELECT 1 FROM mapeamento_produtos_nfe x WHERE x.insumo_id = i.id)
                OR EXISTS (SELECT 1 FROM baixas x WHERE x.insumo_id = i.id)
                OR EXISTS (SELECT 1 FROM itens_contagem x WHERE x.insumo_id = i.id))"""
        ).fetchall()
    }
    refrigerantes = _refrigerantes(conn)
    sem_prato_na_zig = [dict(d) for d in conn.execute(
        """SELECT sku, nome_produto FROM mapeamento_produtos_zig
            WHERE prato_id IS NULL ORDER BY nome_produto"""
    ).fetchall()]
    conn.close()

    todas = receitas
    ignoradas = [r for r in receitas if chave(r["aba"]) in ABAS_IGNORADAS]
    receitas = [r for r in receitas if chave(r["aba"]) not in ABAS_IGNORADAS]
    for receita in ignoradas:
        avisos.append(
            f"A aba '{receita['aba']}' ficou de fora: {ABAS_IGNORADAS[chave(receita['aba'])]}."
        )

    insumos, tipos = {}, {}
    for receita in receitas:
        if e_preparo(receita):
            nome, unidade = PREPAROS[chave(receita["aba"])]
            insumos[nome] = existentes.get(nome, {}).get("unidade", unidade)
            tipos[nome] = "producao"

    def resolver(item, receita, prato):
        """(insumo, quantidade na unidade dele), ou None para pular a linha."""
        nome = chave(item["nome"])
        aba = chave(receita["aba"])
        if (aba, nome) in LINHAS_IGNORADAS:
            avisos.append(LINHAS_IGNORADAS[(aba, nome)].capitalize() + ".")
            return None
        if nome in SEM_ESTOQUE:
            return None
        if nome in FORA_DA_FICHA:
            avisos.append(
                f"'{receita['aba']}' leva '{item['nome']}' ({item['quantidade']:g}), que "
                f"ficou fora da ficha: {FORA_DA_FICHA[nome]}. Se for sempre o mesmo, "
                "acrescente na tela Ficha Técnica."
            )
            return None

        insumo = _INGREDIENTES.get(nome)
        if insumo is None:
            insumo = item["nome"].strip().capitalize()
            avisos.append(
                f"'{item['nome']}' ({receita['aba']}) não está na lista de ingredientes "
                f"do bar; entrou como '{insumo}', em litro."
            )
        elif nome in MAPEAMENTOS_ASSUMIDOS:
            # Pelo texto, não pela grafia: "Suco de limão" e "Suco de Limão
            # Taiti" são a mesma suposição e viram um aviso só.
            avisos.append(f"Suposição: {MAPEAMENTOS_ASSUMIDOS[nome]}.")

        quantidade = item["quantidade"]
        if nome in DOSES_FIXAS and quantidade != DOSES_FIXAS[nome]:
            doses_fixadas.append(f"{receita['aba']} {quantidade * 1000:g} ml")
            quantidade = DOSES_FIXAS[nome]
        corrigida = QUANTIDADES_CORRIGIDAS.get((aba, nome))
        if corrigida and corrigida[0] != quantidade:
            avisos.append(corrigida[1] + ".")
            quantidade = corrigida[0]
        item = {**item, "quantidade": quantidade}

        if insumo not in existentes and chave(insumo) in por_chave:
            # O mesmo insumo com outra caixa ("Chopp heineken"): usa o que existe.
            insumo = por_chave[chave(insumo)]

        if tipos.get(insumo) == "producao":
            if _contavel(item) and nome in FATORES_POR_UNIDADE:
                return insumo, quantidade * FATORES_POR_UNIDADE[nome]
            return insumo, quantidade

        if insumo in existentes:
            unidade = existentes[insumo]["unidade"]
        else:
            unidade = NOVOS.get(insumo, "l")
            if insumo not in NOVOS and _INGREDIENTES.get(nome):
                avisos.append(
                    f"'{insumo}' não existe no estoque (esperava que a contagem o "
                    "tivesse criado); entrou como insumo novo."
                )
        insumos[insumo] = unidade
        tipos[insumo] = existentes.get(insumo, {}).get("tipo", "cru")
        return insumo, _converter(item, insumo, unidade, nome, receita, prato,
                                  sem_conversao, avisos)

    producoes, fichas = [], []
    montados = {}   # prato → aba que o montou, para pegar aba repetida
    com_rendimento_do_modelo = []
    for receita in receitas:
        aba = chave(receita["aba"])
        if aba in AVISOS_DE_ABA:
            avisos.append(AVISOS_DE_ABA[aba])
        prato = None if e_preparo(receita) else nome_do_drink(receita)
        if prato is not None:
            if chave(prato) in montados:
                avisos.append(
                    f"As abas '{montados[chave(prato)]}' e '{receita['aba']}' viram o "
                    f"mesmo drink ('{prato}'). Usei a primeira e ignorei a segunda."
                )
                continue
            montados[chave(prato)] = receita["aba"]

        consumo = {}
        for item in receita["ingredientes"]:
            resolvido = resolver(item, receita, prato or "")
            if resolvido is None:
                continue
            insumo, quantidade = resolvido
            consumo[insumo] = consumo.get(insumo, 0.0) + quantidade

        if prato is None:
            nome, _ = PREPAROS[aba]
            soma = sum(
                i["quantidade"] for i in receita["ingredientes"]
                if chave(i["nome"]) not in FORA_DA_FICHA
            )
            # O 2,33 da planilha é o valor do modelo, repetido em quase toda
            # aba. Nele, a soma dos ingredientes (água incluída) é um ponto
            # de partida melhor, e quem lança corrige o que rendeu.
            rendimento = receita["rendimento"]
            if not rendimento or abs(rendimento - RENDIMENTO_DO_MODELO) < 1e-9:
                rendimento = round(soma, 3)
                com_rendimento_do_modelo.append(receita["aba"])
            producoes.append({
                "nome": nome,
                "aba": receita["aba"],
                "unidade": insumos[nome],
                "rendimento": rendimento,
                "itens": [
                    {"insumo": i, "quantidade": round(q, 6)}
                    for i, q in sorted(consumo.items())
                ],
            })
            if aba in PREPAROS_VENDIDOS:
                vendido, porcao = PREPAROS_VENDIDOS[aba]
                fichas.append({"prato": vendido, "insumo": nome,
                               "quantidade": porcao, "aba": receita["aba"]})
            continue

        porcoes = receita["porcoes"] or 1.0
        for insumo, quantidade in consumo.items():
            fichas.append({
                "prato": prato,
                "insumo": insumo,
                "quantidade": round(quantidade / porcoes, 6),
                "aba": receita["aba"],
            })

    # Refrigerantes: 1 unidade por venda, um prato por linha da contagem.
    for refrigerante in refrigerantes:
        if chave(refrigerante["insumo"]) in montados:
            continue
        montados[chave(refrigerante["insumo"])] = refrigerante["secao"]
        insumos[refrigerante["insumo"]] = refrigerante["unidade"]
        tipos[refrigerante["insumo"]] = existentes[refrigerante["insumo"]]["tipo"]
        fichas.append({"prato": refrigerante["insumo"], "insumo": refrigerante["insumo"],
                       "quantidade": 1.0, "aba": f"contagem: {refrigerante['secao']}"})

    if com_rendimento_do_modelo:
        avisos.append(
            f"O rendimento de {', '.join(com_rendimento_do_modelo)} é 2,33, o valor do "
            "modelo da planilha. Usei a soma dos ingredientes como rendimento de 1 "
            "receita; corrija o 'quanto rendeu' ao lançar a produção."
        )
    avisos.extend(_quantidades_fora_da_curva(fichas, insumos))
    avisos.extend(_bitter_demais(fichas))
    if doses_fixadas:
        avisos.append(
            f"Angostura em {len(doses_fixadas)} drink(s) vinha em ml de dose "
            f"({', '.join(doses_fixadas)}): usei 2 ml por drink, a dose do bar."
        )
    for (insumo, unidade), usos in sorted(sem_conversao.items()):
        lista = ", ".join(f"{aba} {q:g}" for aba, q in usos)
        if unidade in ("garrafa", "lata", "caixa"):
            motivo = f"o nome não diz o volume de 1 {unidade}"
        else:
            motivo = (f"a ficha do bar pensa em kg ou litro e não se sabe quanto pesa "
                      f"1 {unidade}")
        avisos.append(
            f"'{insumo}' é contado em {unidade} e {motivo}. Entrou o número da "
            f"planilha como {unidade}, em {len(usos)} drink(s): {lista}. Acerte na "
            "tela Ficha Técnica."
        )

    pratos = sorted({f["prato"] for f in fichas})
    remover = [nome for nome in PRODUCOES_QUE_SAIRAM if nome in existentes]

    # Prato que a importação antiga criou com o nome da aba.
    destino_da_aba = {}
    for receita in todas:
        aba = chave(receita["aba"])
        if aba in ABAS_IGNORADAS:
            # Sai o prato com o nome da aba e o com o nome que o sistema
            # deu ao drink ("Dark N Stormy"), se não tiver venda nem Zig.
            destino_da_aba[receita["aba"].strip()] = None
            if aba in NOMES_DE_DRINK:
                destino_da_aba[NOMES_DE_DRINK[aba]] = None
        elif aba in PREPAROS:
            destino_da_aba[receita["aba"].strip()] = PREPAROS_VENDIDOS.get(aba, (None,))[0]
        else:
            destino_da_aba[receita["aba"].strip()] = nome_do_drink(receita)
    renomear_pratos, pratos_que_saem, pratos_que_ficam = [], [], []
    tomados = set(ja_tem_prato)
    for antigo, novo in sorted(destino_da_aba.items()):
        if antigo not in do_bar or antigo == novo:
            continue
        if novo and novo in pratos and novo not in tomados:
            renomear_pratos.append({"de": antigo, "para": novo})
            tomados.add(novo)
        elif not do_bar[antigo]["venda"] and not do_bar[antigo]["zig"]:
            pratos_que_saem.append(antigo)
        else:
            pratos_que_ficam.append(antigo)
    for antigo in pratos_que_ficam:
        avisos.append(
            f"O prato '{antigo}', da importação antiga, tem venda ou produto da Zig e "
            "ficou como está (com a ficha antiga). Ligue o produto da Zig ao prato "
            "novo e apague-o quando não precisar mais."
        )
    renomeados = {r["para"] for r in renomear_pratos}

    # Prato do bar sem ficha, sem venda e sem Zig, que nenhuma aba gera:
    # feito à mão e não usado. Só sai se quem importa marcar.
    afetados = set(pratos) | {r["de"] for r in renomear_pratos} | set(pratos_que_saem)
    vazios = sorted(
        nome for nome, d in do_bar.items()
        if nome not in afetados and not d["ficha"] and not d["venda"] and not d["zig"]
    )

    # Insumo sem histórico que, depois da importação, nenhuma ficha cita.
    insumos_que_saem = sorted(
        nome for nome in sem_historico
        if nome not in insumos and nome not in remover and nome in citados_por
        and citados_por[nome] <= afetados
    )
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
        "pratos_novos": sorted(p for p in pratos if p not in ja_tem_prato and p not in renomeados),
        "renomear_pratos": renomear_pratos,
        "pratos_que_saem": pratos_que_saem,
        "pratos_vazios": vazios,
        "insumos_que_saem": insumos_que_saem,
        "fichas": sorted(fichas, key=lambda f: (f["prato"], f["insumo"])),
        # A planilha do bar não cobre a cozinha: os insumos e pratos que ela
        # não cita não são órfãos, são de outro setor.
        "orfaos": [],
        "unidades_divergentes": [],
        "pratos_sem_ficha": [],
        "refrigerantes": [r["insumo"] for r in refrigerantes],
        "zig": _ligacoes_da_zig(sem_prato_na_zig, pratos),
        "remover": [
            {"nome": nome, "motivo": PRODUCOES_QUE_SAIRAM[nome]} for nome in remover
        ],
        "avisos": sorted(set(avisos)),
    }


def _refrigerantes(conn) -> list[dict]:
    """Os refrigerantes, energéticos e tônicas da folha de contagem."""
    from contagem_import import BEBIDAS_FORA

    fora = {chave(d) for d in BEBIDAS_FORA}
    linhas = conn.execute(
        """SELECT ic.descricao, ic.secao, ic.ordem, i.nome AS insumo,
                  i.unidade_medida AS unidade
             FROM itens_contagem ic JOIN insumos i ON i.id = ic.insumo_id
            ORDER BY ic.ordem"""
    ).fetchall()
    vistos, saida = set(), []
    for linha in linhas:
        descricao, secao = chave(linha["descricao"]), chave(linha["secao"])
        e_refrigerante = (secao.startswith(SECOES_DE_REFRIGERANTE)
                          or descricao.startswith(LINHAS_DE_REFRIGERANTE))
        if not e_refrigerante or descricao in fora or linha["insumo"] in vistos:
            continue
        vistos.add(linha["insumo"])
        saida.append({"insumo": linha["insumo"], "unidade": linha["unidade"],
                      "secao": linha["secao"]})
    return saida


def _ligacoes_da_zig(sem_prato: list[dict], pratos: list[str]) -> list[dict]:
    """Produtos da Zig sem prato que viram um prato deste plano."""
    por_chave = {chave(p): p for p in pratos}
    ligacoes = []
    for produto in sem_prato:
        nome = chave(produto["nome_produto"])
        alvo = _ZIG.get(nome)
        prato = por_chave.get(chave(alvo)) if alvo else por_chave.get(nome)
        if prato:
            ligacoes.append({"sku": produto["sku"], "nome_produto": produto["nome_produto"],
                             "prato": prato})
    return ligacoes


def renomear_pratos(conn, plano: dict) -> int:
    """Antes de gravar a ficha: o prato com nome de aba ganha o nome novo,
    para a importação achar o prato (com as vendas e a Zig dele) em vez de
    criar outro."""
    for troca in plano.get("renomear_pratos", []):
        conn.execute("UPDATE pratos SET nome = ? WHERE nome = ?", (troca["para"], troca["de"]))
    return len(plano.get("renomear_pratos", []))


def gravar_extras(conn, plano: dict, apagar_vazios: bool = False) -> dict:
    """O que só o bar grava, na transação de `ficha_import.aplicar_plano`:
    os produtos da Zig ligados aos pratos, as produções que saíram, e o que
    a importação antiga deixou (pratos de aba repetida, insumos sem uso)."""
    from crud import _atualizar_linhas, _excluir_insumo

    pratos = {d["nome"]: d["id"] for d in conn.execute("SELECT id, nome FROM pratos").fetchall()}
    por_sku = {
        d["sku"]: d["id"]
        for d in conn.execute("SELECT id, sku FROM mapeamento_produtos_zig").fetchall()
    }
    ligar = {
        por_sku[z["sku"]]: (pratos[z["prato"]], 0)
        for z in plano.get("zig", []) if z["sku"] in por_sku and z["prato"] in pratos
    }
    _atualizar_linhas(conn, "mapeamento_produtos_zig",
                      {"prato_id": "INTEGER", "ignorar": "INTEGER"}, ligar)

    insumos = {d["nome"]: d["id"] for d in conn.execute("SELECT id, nome FROM insumos").fetchall()}
    removidos = 0
    for producao in plano.get("remover", []):
        if producao["nome"] in insumos:
            _excluir_insumo(conn, insumos[producao["nome"]])
            removidos += 1

    # Prato sai só sem venda e sem Zig (o plano conferiu, e o banco recusa
    # pela chave estrangeira se algo apareceu desde a prévia).
    saem = list(plano.get("pratos_que_saem", []))
    if apagar_vazios:
        saem += plano.get("pratos_vazios", [])
    pratos_apagados = 0
    for nome in saem:
        if nome in pratos:
            conn.execute("DELETE FROM ficha_tecnica WHERE prato_id = ?", (pratos[nome],))
            conn.execute("DELETE FROM pratos WHERE id = ?", (pratos[nome],))
            pratos_apagados += 1
    insumos_apagados = 0
    for nome in plano.get("insumos_que_saem", []):
        if nome in insumos:
            citado = conn.execute(
                "SELECT 1 FROM ficha_tecnica WHERE insumo_id = ?", (insumos[nome],)
            ).fetchone()
            if not citado:
                _excluir_insumo(conn, insumos[nome])
                insumos_apagados += 1
    return {"zig": len(ligar), "removidos": removidos,
            "pratos_apagados": pratos_apagados, "insumos_apagados": insumos_apagados}


def _contavel(item) -> bool:
    """A planilha marcou o item como unidade e a quantidade é de unidades."""
    declarada = chave(item.get("unidade_declarada") or "")
    return declarada in ("und", "un", "unid", "unidade") and item["quantidade"] >= 1


def _converter(item, insumo, unidade, nome, receita, prato, sem_conversao, avisos) -> float:
    """A quantidade da planilha (litro, kg ou unidade) na unidade do insumo.

    Sem como converter, devolve o número da planilha e anota em
    `sem_conversao` — não chuta peso de maço nem volume de garrafa.
    """
    quantidade = item["quantidade"]
    declarada = chave(item.get("unidade_declarada") or "")
    if declarada == "ds":
        quantidade *= DOSE    # "1 DS" de conhaque é uma dose

    if vende_a_garrafa(prato) and unidade == "garrafa":
        # A garrafa inteira, qualquer que seja o número da planilha.
        if quantidade != 1:
            avisos.append(
                f"'{receita['aba']}' vende a garrafa, e a planilha diz {quantidade:g} "
                f"de '{item['nome']}': usei 1 garrafa."
            )
        return 1.0
    if _contavel(item) and unidade in ("garrafa", "lata", "caixa", "un"):
        return quantidade / UNIDADES_POR_EMBALAGEM.get(insumo, 1)
    if unidade in ("l", "kg"):
        return quantidade
    if unidade in ("garrafa", "lata", "caixa"):
        volume = volume_do_nome(insumo)
        if volume:
            return quantidade / volume
    elif unidade == "un" and nome in FATORES_POR_UNIDADE:
        return quantidade * FATORES_POR_UNIDADE[nome]
    elif unidade in ("un", "maço") and insumo in PESOS_POR_UNIDADE:
        return quantidade / PESOS_POR_UNIDADE[insumo]
    elif unidade == "un" and declarada not in ("kg", "gr", "g", "lt", "l", "ml"):
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
    """Aviso para o drink que gasta muito mais de um insumo que os outros.

    Garrafa, combo, suco e jarra ficam de fora da conta: gastam mais que um
    drink de propósito.
    """
    por_insumo = {}
    for ficha in fichas:
        nome = chave(ficha["prato"])
        if vende_a_garrafa(ficha["prato"]) or nome.startswith(("suco", "jarra")):
            continue
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
