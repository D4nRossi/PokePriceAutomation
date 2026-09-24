# Monitor Pokémon TCG Celebração 30 Anos

Vigia a Copag Loja (e, quando houver token, o Mercado Livre), grava tudo num Postgres local
e avisa um grupo do Telegram com um relatório de diferença. Várias máquinas podem rodar
apontando para o mesmo grupo sem duplicar alerta.

> **Não é dev?** Abra `docs/manual-gustavo.html` no navegador: o manual explica tudo sem precisar programar.

## Subir

```
copy .env.example .env      # preencha; veja "Telegram" abaixo
docker compose up -d --build
docker compose logs -f monitor
```

O Docker Desktop precisa estar aberto. Os containers voltam sozinhos depois de reiniciar o PC
(`restart: unless-stopped`), desde que o Docker Desktop inicie com o Windows.

## Telegram, do zero

1. No Telegram, abra conversa com **@BotFather** → `/newbot` → dê um nome e um usuário terminado em `bot`.
   Ele devolve o token (`123456:ABC...`). Coloque em `TELEGRAM_BOT_TOKEN` no `.env`.
2. Crie o grupo e adicione o bot como membro.
3. No grupo: Configurações do grupo → Administradores → adicione o bot, com **Fixar mensagens** ligado.
4. Mande qualquer mensagem no grupo e rode:
   `docker compose run --rm monitor python -m monitor.main --descobrir-chat`
   Copie a linha `TELEGRAM_CHAT_ID=-100...` para o `.env`.
5. `docker compose run --rm monitor python -m monitor.main --verificar` tem que mostrar tudo `[ok]`.
6. `docker compose run --rm monitor python -m monitor.main --teste-telegram`
7. `docker compose up -d` para o monitor pegar o `.env` novo.

## Várias máquinas

- Em **uma** máquina: `LIDER=true`. Nas outras: `LIDER=false` (padrão). `MAQUINA` diferente em cada uma.
- Todas coletam e gravam no próprio banco. Só quem está "atuando" envia.
- O estado do grupo (o que já foi avisado + sinal de vida do líder) fica numa **mensagem fixada** pelo bot.
  Não apague nem desafixe. Se sumir, o bot recria e pode repetir no máximo um alerta por produto.
- Reserva assume se o líder ficar `FAILOVER_MINUTOS` (15) sem sinal, avisa "🔁 assumiu" e devolve
  quando o líder volta.
- Modo de falha conhecido: duas reservas assumindo no mesmo ciclo podem mandar um alerta em dobro.

## O que é avisado

| Evento | Quando |
|---|---|
| 🟢 Voltou ao estoque (Copag) | indisponível → disponível, uma vez |
| 📉 Preço caiu (Copag) | continuou disponível e o preço baixou |
| 💰 Dentro do teto (ML, quando existir) | oferta ≤ sugerido + `TOLERANCIA_REAIS` |
| 🔴 Monitor cego | fonte falhou `FALHAS_PARA_ALERTA_CEGO` vezes seguidas; ✅ quando volta |
| 🆕 Produto novo | SKU novo na categoria 30 Anos da Copag (checado a cada 1 h) |
| 💓 Monitor vivo | uma vez por dia depois de `HORA_HEARTBEAT` |

O relatório traz preço, sugerido, teto e diferença, preço anterior, menor preço já visto,
desde quando estava indisponível, última vez disponível, link e máquina.

## Produtos, links e preço sugerido

Tudo em `catalogo.json`. `preco_sugerido: null` = sem teto. Editou: `docker compose restart monitor`.

## Banco

`localhost:5433`, banco/usuário `pokemon`, senha do `.env`. Atalho:

```
docker compose exec db psql -U pokemon -d pokemon -c "select * from vw_ultimo_estado"
```

Tabelas: `produto`, `fonte`, `link`, `observacao` (uma linha por link por ciclo),
`alerta_enviado`, `falha_fonte`, `estado_local` (estado quando não há Telegram).

## Testes

```
docker compose run --rm --no-deps monitor python -m unittest discover -s tests -v
```

## Limites

- Mercado Livre desligado: sem token a API responde 401/403 e o site pede verificação anti-robô
  (`docs/00-spike-acesso.md`). O coletor só será escrito depois de ver resposta real com token.
  Passo a passo para criar o app e ligar a fonte: **`docs/mercado-livre-guia.md`**.
- Intervalo mínimo de 5 min por fonte, por regra; valores menores no `.env` são ignorados.
- `legado/` guarda a v1 (script + tarefa agendada do Windows, já removida).
