# Mercado Livre: guia para quem vai cuidar da integração

Este guia é para o Gustavo, que vai ser o dono do app do Mercado Livre neste projeto.
Não precisa ter acompanhado nada antes; tudo que importa está aqui.

## 1. O que é o projeto, em uma tela

- Um monitor que roda em `docker compose` (Postgres + um container Python) e avisa o grupo do
  Telegram **Gugu Automation Master Ultra** pelo bot `@GuguLindo_bot`.
- Hoje ele vigia **só a Copag Loja**: a cada 5 minutos pergunta se algum dos 8 produtos da coleção
  Pokémon TCG Celebração 30 Anos voltou ao estoque. Isso já funciona e já alertou de verdade.
- O **Mercado Livre** é a segunda fonte. A ideia é avisar quando alguém anunciar um desses produtos
  por preço **igual ou menor que o sugerido + R$ 1,00**. Essa parte está **desligada**, e é ela que
  fica com você.

## 2. Por que o ML está desligado

Teste feito em 23/09/2026, sem nenhuma credencial (detalhe em `docs/00-spike-acesso.md`):

| O que foi tentado | Resposta |
|---|---|
| `GET https://api.mercadolibre.com/products/MLB79395943` | 401 `authorization value not present` |
| `GET .../products/MLB79395943/items` | 403 `PolicyAgent` |
| `GET .../sites/MLB/search?q=...` | 403 `forbidden` |
| `GET .../items/{id}` | 403 `PolicyAgent` |
| Abrir a página do produto (`/p/MLB...`) | redireciona para verificação anti-robô |

Ou seja: **sem um app cadastrado no ML, não existe caminho legítimo**. Raspar o site passando pela
verificação anti-robô está fora de questão (viola os termos e bloqueia o IP).

Um alerta honesto: o 403 veio de um componente chamado `PolicyAgent`, que é regra de política, não
de login. **Não está provado que um token destrava.** O primeiro passo depois de criar o app é
justamente testar isso.

## 3. Criar o app (5 minutos, na sua conta do ML)

O app fica na **sua** conta. O Daniel não cria por você porque exige o seu login e o aceite dos
termos de desenvolvedor.

1. Acesse **developers.mercadolivre.com.br** e entre com a sua conta do Mercado Livre.
2. Procure **Criar aplicação** (fica no painel de aplicações / DevCenter).
3. Preencha:
   - **Nome:** `PokePriceAutomation` (se já existir, qualquer variação).
   - **Nome curto e descrição:** o que quiser, por exemplo "monitor pessoal de preço".
   - **Redirect URI:** `https://github.com/D4nRossi/PokePriceAutomation`
     (precisa ser https; é para onde o ML manda o código de autorização, e nós só copiamos
     o código da barra de endereço).
   - **Permissões / escopos:** só **leitura**. Se houver `offline_access`, marque: é o que permite
     renovar o token sem você entrar de novo.
   - **Notificações / tópicos:** nenhum.
4. Salve. O ML mostra o **App ID** (é o `client_id`) e a **Secret Key** (é o `client_secret`).

Os nomes exatos dos botões podem ter mudado; o que importa é sair com App ID e Secret Key.

## 4. Onde colocar as chaves

**Nunca** em mensagem de grupo, print, commit ou issue. O repositório é **público**.

Elas vão no arquivo `.env` da máquina que roda o monitor (o `.env` está no `.gitignore`):

```
ML_CLIENT_ID=<App ID>
ML_CLIENT_SECRET=<Secret Key>
ML_ACCESS_TOKEN=
```

Se for o Daniel que vai ligar a integração na máquina dele, combine com ele um jeito privado de
passar a Secret Key (mensagem direta que some, gerenciador de senha compartilhado). Se vazar, dá
para gerar outra no painel do app.

## 5. Como o token funciona (o que a gente espera, a confirmar)

Pela documentação pública do ML (não testado ainda neste projeto, por isso **[A CONFIRMAR]**):

1. Você abre no navegador, logado na sua conta:
   `https://auth.mercadolivre.com.br/authorization?response_type=code&client_id=<App ID>&redirect_uri=https://github.com/D4nRossi/PokePriceAutomation`
2. Autoriza. O navegador cai na página do GitHub com `?code=TG-...` no endereço. Esse código vale
   poucos minutos e uma vez só.
3. O monitor troca o código por um `access_token` em `POST https://api.mercadolibre.com/oauth/token`.
   O access token dura cerca de **6 horas**; o `refresh_token` (com `offline_access`) renova sem
   você precisar repetir o passo 1.
4. Se o refresh parar de funcionar (senha trocada, app revogado, meses sem uso), repete-se o passo 1.

Existe também um fluxo só com App ID + Secret Key, sem login (`client_credentials`). Se o ML
aceitar esse fluxo para as consultas que precisamos, você não precisa fazer o passo 1 nunca.
É a primeira coisa que vamos testar.

## 6. O que acontece depois que as chaves existirem

Em ordem, cada passo só avança se o anterior provar que funciona:

1. **Teste de acesso:** repetir as chamadas da seção 2 com token e registrar o status HTTP.
2. **Se der 200:** olhar a resposta real e só então escrever o coletor (nenhum campo de JSON é
   inventado antes de ver a resposta).
3. **Regra de casamento:** só vale oferta de **produto de catálogo** (`/p/MLB...`), **novo**,
   nacional. Carta avulsa, importado, lote e "compatível" ficam de fora.
4. **Ligar a fonte:** o ML entra no mesmo fluxo da Copag e manda para o mesmo grupo:
   `💰 DENTRO DO TETO` com preço, sugerido, teto, diferença em R$ e %, preço anterior e link.
5. **Se continuar 403 com token:** o ML fica fora do projeto e o grupo segue só com a Copag.
   Nada de scraping.

## 7. Produtos já mapeados no ML

Estão em `catalogo.json` (é o arquivo que manda; editou, `docker compose restart monitor`):

| Produto | Catálogo ML |
|---|---|
| Treinador Avançado (ETB) | `MLB79395943` |
| Box Coleção com Fichário | `MLB79396525` |
| Box ex Greninja | `MLB79396707` |
| Blister Triplo Exeggutor | `MLB79396270` |
| Blister Duplo com Moeda | `MLB77672147` |
| Blister Triplo Lucario, Box ex Sylveon, Box Coleção com Pôster | **faltam**: se achar a página `/p/MLB...` deles, é só adicionar |

## 8. O teto de preço

O alerta do ML depende do **preço sugerido** de cada produto (`preco_sugerido` no `catalogo.json`).
Enquanto estiver `null`, o ML **nunca** alerta, de propósito. A lista oficial ("LISTA DE PREÇO
OFICIAL SUGERIDO: POKÉMON TCG") ainda não foi cadastrada. Para referência, a Copag vende hoje a:

| Produto | Copag (23/09/2026) |
|---|---|
| Treinador Avançado (ETB) | R$ 399,99 |
| Box Coleção com Fichário | R$ 230,99 |
| Box ex Greninja | R$ 169,99 |
| Box ex Sylveon | R$ 169,99 |
| Box Coleção com Pôster | R$ 115,99 |
| Blister Triplo Lucario | R$ 99,99 |
| Blister Triplo Exeggutor | R$ 99,99 |
| Blister Duplo com Moeda | R$ 69,99 |

## 9. Se você também quiser rodar o monitor

Vale ter uma segunda máquina como **reserva**: se a do Daniel desligar, a sua assume os envios.

1. Instale o Docker Desktop e clone o repositório.
2. `copy .env.example .env` e preencha: o mesmo `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`
   (peça ao Daniel, em privado), **`LIDER=false`** e `MAQUINA=gustavo` (ou qualquer nome diferente).
3. `docker compose up -d --build`
4. `docker compose run --rm monitor python -m monitor.main --verificar` tem que mostrar tudo `[ok]`.

A sua máquina coleta e grava no seu banco, mas só envia se a do Daniel ficar 15 minutos sem sinal.
Quando assumir, o grupo recebe "🔁 gustavo assumiu os envios". O resto está no `README.md`.

## 10. Checklist do Gustavo

- [ ] App criado no ML, só leitura, redirect `https://github.com/D4nRossi/PokePriceAutomation`
- [ ] App ID e Secret Key entregues por canal privado (ou no `.env` da sua máquina)
- [ ] Teste de acesso com token feito e registrado (seção 6, passo 1)
- [ ] Lista de preço sugerido cadastrada no `catalogo.json`
- [ ] (opcional) Sua máquina rodando como reserva
