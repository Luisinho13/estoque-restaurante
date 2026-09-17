# 📦 Controle de Estoque para Restaurante

Substitui a contagem manual semanal de estoque por um cálculo automático
a partir de compras e vendas. A contagem física deixa de ser a rotina de
toda segunda-feira e vira uma conferência mensal.

Projeto pessoal, criado para um problema real do restaurante onde
trabalho como comprador.

![Dashboard do sistema](docs/dashboard.png)

> As telas deste README usam o banco de demonstração gerado por
> `seed_demo.py`, com dados fictícios.

## O problema

O controle era uma planilha e uma contagem física toda semana: alguém
percorria o estoque item por item, anotava tudo e digitava. Demorado,
repetitivo e fácil de errar — e, no fim, respondia "quanto eu tenho",
quando a pergunta que importa para comprar é **"o que vai acabar
primeiro"**.

## A ideia

Se eu sei o que entrou e o que saiu, eu sei o que sobrou. Não preciso
contar toda semana.

```
estoque atual = última contagem física
              + compras registradas a partir dessa data (inclusive)
              − consumo (vendas × ficha técnica), também a partir
                dessa data (inclusive)
```

A ficha técnica de cada prato diz quanto de cada insumo é consumido por
unidade vendida. Com as vendas do dia lançadas, o sistema já sabe quanto
saiu de cada ingrediente.

A contagem física continua existindo, **1x por mês**, com outro papel:
ela é o ponto de partida do cálculo e a forma de medir perda, quebra e
desperdício — a diferença entre o teórico e o real.

> A última contagem é sempre a base. Uma venda ou compra anterior a ela
> é considerada já refletida naquela contagem e não entra na conta de
> novo. Por isso a contagem precisa ser lançada com a data real em que
> foi feita, nunca retroativa.

## O que o sistema faz

**Entradas de estoque**
- Lançamento manual de compras
- Importação por **XML de NF-e**: cada produto do fornecedor é mapeado
  uma vez para um insumo, com fator de conversão quando a unidade da
  nota não bate com a unidade controlada (caixa → unidade, por exemplo).
  Nas próximas notas do mesmo fornecedor, o produto é reconhecido sozinho

**Saídas de estoque**
- Importação das vendas do **PDV (Zig)** a partir da planilha exportada:
  as linhas item a item são somadas por produto e por dia, e cada SKU é
  ligado uma vez a um prato — ou marcado como "não controlar", no caso de
  couvert, bebida e itens de loja
- Lançamento manual por prato, com confirmação antes de somar um segundo
  lançamento do mesmo prato no mesmo dia

**Conferência**
- **Dashboard** com indicadores do período, consumo por insumo, curva de
  vendas por dia, ranking de pratos e movimentações recentes
- **"O que acaba primeiro"**: estimativa de em quantos dias cada insumo
  acaba (estoque ÷ consumo médio diário), com semáforo de status. É a
  tela que responde o que precisa ser comprado antes de faltar
- Registro da contagem física mensal, que vira a nova base do cálculo

![Tela "O que acaba primeiro"](docs/o-que-acaba-primeiro.png)

## Decisões que valem nota

Quatro detalhes que não são óbvios e custaram tempo:

**SKU é identificador, não texto.** Na Zig, os códigos de produto
diferenciam maiúsculas: `Fe` é Arroz Extra e `FE` é Pão Extra. O
instinto de normalizar tudo para maiúscula faria um sobrescrever o
outro silenciosamente, sem erro nenhum — o sistema seguiria rodando,
descontando pão quando alguém pedisse arroz.

**A data certa não é a óbvia.** A planilha traz o horário da transação
e o dia operacional. Uma venda às 2h da manhã pertence ao movimento da
noite anterior, então é o dia operacional que vale — usar o outro joga
o consumo para o dia seguinte.

**Importar substitui, não soma.** Reimportar o mesmo relatório corrige
o dia em vez de duplicar os lançamentos. Isso veio de um bug real: um
prato descontava 3 em vez de 1, e a causa eram três cliques no botão
gerando três registros idênticos. O erro estava nos dados, não na conta.

**A comparação de datas usa `>=`, não `>`.** Vendas feitas no mesmo dia
da contagem física precisam ser descontadas. Com `>` elas sumiam da
conta — outro bug que já aconteceu.

## Como rodar

```bash
pip install -r requirements.txt
streamlit run app.py
```

O app abre em `http://localhost:8501`.

### Ver com dados de exemplo

Para conhecer o sistema sem cadastrar nada, e sem tocar em nenhum dado
real, gere um banco de demonstração com 60 dias de vendas, compras e
contagens:

```bash
python seed_demo.py
ESTOQUE_DB=estoque_demo.db streamlit run app.py
```

A variável `ESTOQUE_DB` aponta o app para outro arquivo de banco. Sem
ela, o app usa o `estoque.db` padrão.

### Primeiros passos num banco vazio

A ordem importa, porque cada etapa depende da anterior:

1. Cadastre os **insumos** que você controla, com unidade e estoque mínimo
2. Cadastre os **pratos** e monte a **ficha técnica** de cada um
3. Registre uma **contagem física** — sem ela o cálculo parte do zero e
   o estoque fica negativo
4. A partir daí, lance compras e vendas normalmente

## Estrutura

```
estoque-restaurante/
├── app.py            # interface Streamlit (dashboard e telas)
├── crud.py           # regras de negócio e cálculo do estoque teórico
├── database.py       # esquema do banco
├── nfe_import.py     # leitura de XML de NF-e → compras
├── zig_import.py     # leitura da planilha do PDV → vendas
├── seed_demo.py      # gera um banco de demonstração
├── diagnostico.py    # inspeção de dados de um prato ou insumo
└── requirements.txt
```

Python, SQLite (arquivo local, sem servidor) e Streamlit.

## Próximos passos

- Histórico de perdas por reconciliação (diferença entre o teórico e a
  contagem física)
- Exportação de relatórios mensais
- Sugestão de compra a partir dos dias de estoque restantes
