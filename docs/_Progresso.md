# Progresso: monitor Pokémon TCG Celebração 30 Anos

Prompt de origem: `C:\Users\Daniel\Downloads\prompt-monitor-pokemon-30-anos.md`. Daniel liberou "gohorse mode".

## Estado em 23/09/2026, 18h

- v2 NO AR nesta máquina (DESKTOP-VPRVBHA, `LIDER=true`): `docker compose` com `db` (postgres 16) e `monitor`.
  23 testes verdes. Primeiro ciclo real alertou o Blister Duplo (18:01) e ele esgotou às 18:03.
- Telegram LIGADO às 22:08: bot @GuguLindo_bot, grupo "Gugu Automation Master Ultra" (-1004489152513), admin com fixar;
  estado compartilhado na mensagem fixada 6. Antes disso (18h-22h) só log: Duplo 18:01 e Pôster 18:14 ficaram disponíveis 1-2 ciclos.
- v1 (script + tarefa agendada) em `legado/`; tarefa `MonitorPokemon30Anos` REMOVIDA do Windows.
- Mercado Livre desligado até existir app/token (links já no `catalogo.json`).

## Desenho (decisões)

- Estado compartilhado entre máquinas = mensagem fixada do bot no grupo (JSON). Descartado: banco na nuvem
  (custa e contradiz "roda local"); todas enviando (duplica).
- Líder por flag `LIDER`; reserva assume após `FAILOVER_MINUTOS` sem sinal, continua enquanto for a última
  a escrever, devolve quando o líder escreve de novo.
- Alerta só marca como dado se o Telegram aceitou; senão tenta no próximo ciclo.
- Copag: modo "estoque" (preço de tabela). ML: modo "teto" (sugerido + tolerância, inclusivo).

## Fatos provados (não reverificar sem motivo)

- Copag é VTEX. Categoria 30 Anos = `fq=C:/35741/106254/`, 8 produtos, SKUs 2602 a 2609, seller `1`.
- Estoque confiável: `POST /api/checkout/pub/orderForms/simulation?sc=1` → `items[].availability`, preço em centavos em `sellingPrice`.
- Catálogo tem cache de 300 s e divergiu da simulação.
- ML: tudo 401/403 sem token; página `/p/` cai em verificação anti-robô.

## Pendências

- Lista de preço sugerido oficial → `catalogo.json`.
- App do ML (developers.mercadolivre.com.br) → testar `/products/{id}/items` com token antes de escrever coletor.
- IDs de catálogo ML de Lucario, Sylveon e Pôster.
