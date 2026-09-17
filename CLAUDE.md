# Contexto do Projeto — Sistema de Estoque para Restaurante

## Sobre o projeto

Sistema que substitui a contagem manual semanal de estoque (feita em
planilha, toda segunda-feira) por um cálculo automático de estoque
teórico, baseado em compras e vendas. A contagem física manual passa a
ser necessária apenas 1x por mês, para reconciliar.

Esse é um projeto pessoal do usuário (comprador de um restaurante),
pensado também para virar um post no LinkedIn mostrando a solução.

## Stack

- Python
- SQLite (arquivo `estoque.db`, ignorado no git)
- Streamlit (interface em `app.py`)

## Estrutura de arquivos

- `database.py` — cria as tabelas (insumos, pratos, ficha_tecnica,
  compras, vendas_diarias, contagens_fisicas, mapeamento_produtos_nfe)
- `crud.py` — toda a lógica de negócio: cadastros, lançamentos,
  exclusão de insumo, e o cálculo do estoque teórico
- `app.py` — interface Streamlit. Navegação por `st.navigation`, com as
  telas agrupadas em Visão geral (Dashboard, Painel de Estoque),
  Cadastros (Insumos, Pratos, Ficha Técnica) e Lançamentos (Compra,
  Importar Nota Fiscal, Venda do Dia, Contagem Física)
- `nfe_import.py` — lê XML de NF-e e lança compras automaticamente,
  usando uma tabela de mapeamento (produto do fornecedor → insumo)
- `seed_demo.py` — gera `estoque_demo.db` com 60 dias de dados fictícios
  (para demonstração e prints). O app aceita a variável de ambiente
  `ESTOQUE_DB` para apontar para outro banco sem tocar no real.
- `requirements.txt`, `README.md`, `.gitignore`

## Lógica central (não mexer sem entender bem)

```
estoque atual = última contagem física
              + compras registradas a partir dessa data (inclusive)
              − consumo (vendas × ficha técnica) a partir dessa data (inclusive)
```

Importante: a comparação de datas usa `>=` (não `>`) de propósito —
já tivemos um bug em que vendas no mesmo dia da contagem física não
eram descontadas por usar `>`. Ver histórico de commits.

## Decisões já tomadas

- Vendas podem ser lançadas manualmente por prato OU importadas da
  planilha de vendas exportada da **Zig** (PDV do restaurante). Não há
  API pública documentada; a integração é via export em Excel.
  A planilha vem item a item, com uma linha por produto em cada comanda.
  Colunas que importam: `SKU` (identificador do produto, **sensível a
  maiúsculas** — `Fe` e `FE` são produtos diferentes), `Nome do Produto`,
  `Quantidade`, `Tipo da Transação` (só `Normal` conta; o resto é
  cancelamento/estorno) e `Data do Evento` (dia operacional — uma venda
  às 2h pertence ao movimento da noite anterior, por isso é ela que vale
  e não a coluna `Data`).
  A importação **substitui** as vendas do dia em vez de somar, então
  reimportar o mesmo relatório corrige o dia sem duplicar.
- Compras podem ser lançadas manualmente OU importadas automaticamente
  via XML de NF-e (já implementado e testado).
- Exclusão de insumo é permitida, mas apaga também ficha técnica,
  compras e contagens físicas ligadas a ele (é definitivo).

## Bug do -3 (investigado, não reproduzível)

O usuário relatou que uma venda descontava -3 do estoque em vez de -1.
Em 17/09/2026 o banco real foi inspecionado e estava consistente
(1 insumo, 1 prato, ficha técnica de 0,25, 1 venda, contagem de 10 kg →
estoque 9,8 kg, correto). A causa mais provável eram linhas duplicadas
em `vendas_diarias` vindas de submissões repetidas do formulário, e não
erro na lógica de cálculo — as tabelas têm `UNIQUE(prato_id, insumo_id)`
na ficha técnica, o que descarta ficha duplicada.
Duas proteções já existem: a confirmação antes de somar venda repetida
no mesmo dia, e a importação da Zig, que substitui o dia em vez de somar.
Se reaparecer, conferir primeiro se há várias linhas em `vendas_diarias`
para o mesmo prato e data.

## Próximos passos possíveis

- Resolver o bug do -3 acima
- Migrar lançamento de vendas pra importação automática, se a Zig
  liberar exportação/API
- Publicar o projeto no LinkedIn (repositório já está público no
  GitHub em `Luisinho13/estoque-restaurante`)
