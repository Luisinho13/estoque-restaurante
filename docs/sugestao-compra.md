# 🛒 Previsão de demanda e sugestão de compra no WhatsApp

Segundo projeto em cima do [sistema de estoque](../README.md). O estoque
responde *quanto tem*; este responde **quanto comprar**: toda segunda às
13h chega no WhatsApp do comprador a previsão da semana e a lista de
compra, com a quantidade de cada item e o dia em que ele acaba.

```
🛒 Sugestão de compra — seg 19/10

📈 Previsão de seg 19/10 a dom 25/10: ~2226 pratos e drinks (semana passada: 2220)
Base: 4 semana(s) de vendas do PDV, por dia da semana, peso maior na mais recente
Mais pedidos: Cerveja long neck 614, Refrigerante 364, Executivo do dia 257, ...
Dia mais cheio: sáb 24/10 (~438)

Hortifruti São João
• Alho — 4,4 kg (acaba qui 22/10)

Pescados Litoral
• Camarão — 16 kg (acaba sex 23/10)
...
⚠️ Dias sem venda lançada, fora da previsão: qua 14/10.
```

*(exemplo com os dados fictícios da demonstração)*

## Por que um projeto em cima do outro

A sugestão de compra precisa de quatro coisas que o sistema de estoque
já tem, conferidas no uso diário: o que o PDV vendeu (`vendas_diarias`,
pela importação da Zig ou pelo lançamento do dia), a ficha técnica de
cada prato, a receita de cada molho e porcionado, e o estoque de agora.
Começar do zero seria reconstruir tudo isso. O projeto novo é um módulo
(`sugestao_compra.py`), uma tela no app e um bot que roda fora dele.

## Como a conta é feita

**1. Previsão de demanda, prato a prato, dia a dia.** Restaurante vende
por dia da semana: o sábado não se parece com a terça. A previsão de cada
prato para o próximo sábado é a média dos últimos sábados, com peso maior
para o mais recente (4, 3, 2 e 1 nas últimas quatro semanas). Com uma
semana só de histórico, a previsão é a própria semana passada.

- Dia **sem venda lançada não conta como zero**: fica fora da média e
  aparece como aviso. Zero ali seria esquecimento, não demanda.
- Dia marcado como "o restaurante não abriu" conta como zero, porque é.

**2. Da demanda para o cru.** A previsão passa pela ficha do prato e,
quando a ficha cita um molho ou um porcionado, pela receita dele
(quantidade por receita ÷ rendimento), até chegar no que se compra. No
cálculo do estoque é diferente (a venda tira o molho e o tomate só sai
quando a produção é lançada), mas para prever compra isso não serve:
produção esquecida faria o tomate sumir da lista.

**3. O que já está pronto desconta.** Se a câmara tem 30 kg de alcatra
porcionada, a necessidade de porcionado é abatida antes de descer para a
peça. É a conta clássica de MRP: o que desce para o nível de baixo é a
necessidade *líquida* do nível de cima.

**4. A compra.**

```
comprar = previsão dos dias cobertos + estoque mínimo − estoque atual
```

arredondada para cima (kg e litro em uma casa; garrafa, lata, caixa e
pacote em inteiro). Estoque negativo conta como zero: na prateleira não
há menos que nada. Baixas (quebra, consumo da equipe) entram pela média
diária.

**5. Quando acaba.** O estoque de hoje vai sendo consumido pela previsão
de cada dia (o sábado gasta mais), e o primeiro dia em que ele não chega
é o "acaba". Se só acaba depois da semana coberta, o item está na lista
para repor o mínimo.

Só entram na lista os itens comprados que a previsão movimenta. Os
parados abaixo do mínimo ficam fora da mensagem (com quase todo mínimo
em 5, a lista viraria o catálogo inteiro) e são contados no fim, para
olhar no app.

## As peças

| Arquivo | O que faz |
|---|---|
| `sugestao_compra.py` | previsão, descida até o cru, compra, texto da mensagem e envio pelo CallMeBot |
| `bot_compras.py` | o bot: calcula e manda (`--previa` só mostra) |
| `.github/workflows/sugestao-compra.yml` | agenda o bot toda segunda, 13h de Brasília |
| `app.py` → *Sugestão de Compra* | a mesma conta na tela, com os dias e as semanas ajustáveis, a previsão por dia e por prato, CSV e botão de mandar agora |

O bot só precisa de `psycopg` e `tzdata`. O Streamlit e o pandas ficam
na tela.

## Como ligar

### 1. Chave do CallMeBot (5 minutos)

1. Salve o número **+34 644 31 95 65** nos contatos do celular.
2. Mande para ele, pelo WhatsApp: `I allow callmebot to send me messages`.
3. Em até 2 minutos chega a resposta com a sua **apikey**.

O CallMeBot gratuito só manda para o **próprio número** que ativou, e é
para uso pessoal. Mandar para a equipe, para um grupo ou para fornecedor
pede a API oficial do WhatsApp (próximos passos).

### 2. Secrets no GitHub

No repositório, *Settings → Secrets and variables → Actions → New
repository secret*, ou pelo terminal:

```
gh secret set DATABASE_URL         # a mesma URL do Neon que está nos secrets do app
gh secret set CALLMEBOT_TELEFONE   # +55 DDD número, ex.: +5511999998888
gh secret set CALLMEBOT_CHAVE      # a apikey da etapa 1
```

Os secrets ficam cifrados no GitHub e não aparecem nos logs, mesmo com o
repositório público.

### 3. Testar

Na aba *Actions* → *Sugestão de compra no WhatsApp* → *Run workflow*.
Marcando "Só mostrar no log", a mensagem aparece no log sem ir para o
WhatsApp. Desmarcado, ela chega no celular.

No computador, com a URL do banco na variável de ambiente:

```
python bot_compras.py --previa             # mostra, não manda
python bot_compras.py --dias 4 --semanas 2 # outra janela
```

### 4. (Opcional) Botão "Mandar agora" no app

Nos secrets do app no Streamlit Cloud:

```toml
[callmebot]
telefone = "+5511999998888"
chave = "123456"
```

Sem isso, a tela mostra a mensagem para copiar e o envio fica só com o bot.

## Cuidados que já estão no código

- **Sem banco, não manda.** Sem `DATABASE_URL`, o `database.py` cairia no
  SQLite local e o restaurante receberia uma lista calculada sobre um
  banco vazio, sem erro nenhum. O bot recusa e sai com erro (o GitHub
  manda e-mail quando um workflow falha).
- **O Neon dormindo.** A conexão já tenta três vezes, com espera
  crescente (é a mesma do app).
- **Mensagem longa** é cortada em partes de até 1.200 caracteres, sempre
  entre linhas, numeradas (1/3, 2/3...), com 6 s entre elas.
- **Data de Brasília** (`crud.hoje()`), mesmo o Actions rodando em UTC.
- **Demo nunca manda**: o botão some em modo demonstração.

## Limites conhecidos

- A previsão é tão boa quanto o lançamento de venda. Dia esquecido sai
  da média e vira aviso. Prato vendido sem ficha não vira compra (aviso).
- Não sabe de feriado, evento nem tempo. Uma semana fora do normal pesa
  na seguinte; com 4 semanas de base, pesa menos.
- O agendamento do GitHub pode atrasar alguns minutos. E, em repositório
  público, o GitHub **desliga o agendamento depois de 60 dias sem
  commit**: se a mensagem parar de chegar, é ali que se religa.
- A quantidade sai na unidade do insumo (kg, garrafa), não na de compra
  do fornecedor (caixa com 12, fardo).

## Próximos passos

1. **Unidade de compra**: converter para caixa e fardo usando o fator do
   mapeamento da NF-e (`mapeamento_produtos_nfe.fator_conversao`), que já
   sabe que a caixa do fornecedor tem 12 un.
2. **Prazo por fornecedor**: hortifrúti todo dia, carne duas vezes na
   semana, bebida uma vez. Hoje é uma compra por semana para todos.
3. **Medir o erro da previsão**: comparar o previsto com o vendido de
   cada semana e mostrar o acerto na tela (é o número que diz se 4
   semanas é a janela certa).
4. **Preço**: com o valor da NF-e, a mensagem diz quanto a compra deve custar.
5. **API oficial do WhatsApp** para mandar à equipe ou ao fornecedor, e
   responder "ok" para virar pedido.
