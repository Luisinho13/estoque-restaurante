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
- `app.py` — interface Streamlit com as telas (Painel, Cadastros,
  Ficha Técnica, Lançar Compra, Importar Nota Fiscal, Lançar Venda,
  Contagem Física)
- `nfe_import.py` — lê XML de NF-e e lança compras automaticamente,
  usando uma tabela de mapeamento (produto do fornecedor → insumo)
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

- Vendas são lançadas manualmente por prato (usuário digita quantos
  pratos vendeu no dia, olhando o PDV). O restaurante usa a
  plataforma **Zig** como PDV/POS, mas não há API pública documentada
  — a integração direta com a Zig ficou pendente (usuário ia verificar
  exportação de relatório de vendas).
- Compras podem ser lançadas manualmente OU importadas automaticamente
  via XML de NF-e (já implementado e testado).
- Exclusão de insumo é permitida, mas apaga também ficha técnica,
  compras e contagens físicas ligadas a ele (é definitivo).

## Bug conhecido / pendente de investigação

O usuário relatou que uma venda estava descontando -3 do estoque em
vez do -1 esperado (ficha técnica com quantidade 1, apenas 1 venda
registrada). Foi criado um `diagnostico.py` (não commitado) para
inspecionar dados duplicados, mas o resultado ainda não foi analisado.
Se esse bug for mencionado, vale investigar dados de teste antigos no
banco (vendas ou fichas técnicas duplicadas) antes de suspeitar de
lógica de código.

## Próximos passos possíveis

- Resolver o bug do -3 acima
- Migrar lançamento de vendas pra importação automática, se a Zig
  liberar exportação/API
- Publicar o projeto no LinkedIn (repositório já está público no
  GitHub em `Luisinho13/estoque-restaurante`)
