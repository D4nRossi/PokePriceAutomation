# Fase 0: spike de acesso (23/09/2026, ~20h40)

Todas as chamadas feitas com `curl`, sem login, sem token, uma requisição por teste.
Respostas brutas da Copag em `docs/evidencias/`.

## Resultado por fonte

| Fonte | Método | Status | Evidência | Classe |
|---|---|---|---|---|
| Copag | `GET /api/catalog_system/pub/products/search?fq=C:/35741/106254/` | 200, 8 produtos | `evidencias/copag-catalogo-search-2026-09-23.json` | amarelo (ver abaixo) |
| Copag | `POST /api/checkout/pub/orderForms/simulation?sc=1` | 200, `Cache-Control: no-store` | `evidencias/copag-simulation-*.json` | **verde** |
| Copag | `GET /api/io/_v/api/intelligent-search/product_search/...` | 404 | não está publicado nesta loja | descartado |
| ML | `GET /products/MLB79395943` sem token | 401 `authorization value not present` | | vermelho sem token |
| ML | `GET /products/MLB79395943/items` sem token | 403 `PolicyAgent PA_UNAUTHORIZED_RESULT_FROM_POLICIES` | | vermelho sem token |
| ML | `GET /sites/MLB/search?q=...` e `?product_id=` sem token | 403 `forbidden` | confirma o relato de 2025 | vermelho sem token |
| ML | `GET /items/{id}` e `/items?ids=` sem token | 403 / 401 | | vermelho sem token |
| ML | HTML da página `/p/MLB79395943` | 200 depois de redirecionar para `/gz/account-verification` | página de verificação anti-robô, sem preço | vermelho (burlar = regra 3) |
| ML | Qualquer endpoint **com token de app** | não testado | depende de você criar o app | [A CONFIRMAR] |

## Copag: qual campo diz "voltou ao estoque"

A catálogo e a simulação **discordaram entre si no mesmo minuto**, nos dois sentidos:

| SKU | Produto | Catálogo (`IsAvailable` / `AvailableQuantity`) | Simulação (`items[].availability`) |
|---|---|---|---|
| 2603 | Blister Triplo Lucario | `true` / 1 | `withoutStock` |
| 2602 | Blister Duplo com Moeda | `false` / 0 | **`available`** (6 opções de frete para CEP 01310-100) |

Trecho real da simulação:

```
('2602', 'available', 6999), ('2603', 'withoutStock', 9999), ... ('2609', 'withoutStock', 16999)
messages: {'code': 'withoutStock', 'text': 'O item ... Treinador Avançado não tem estoque', ...}
```

Por quê: o catálogo vem com `Cache-Control: s-maxage=300` e `X-VTEX-ApiCache-Time: 300`, ou seja, até
5 minutos de atraso no CDN. A simulação é `no-store` e é a mesma checagem que o checkout faz.
**Decisão proposta:** estoque = `availability == "available"` na simulação. O catálogo serve só para
descobrir SKUs novos da categoria (ex.: Sylveon e Pôster, que não estavam na sua lista).

A simulação não cria carrinho nem `orderForm` (não manda `orderFormId`); é consulta pura. Regra 4 preservada.

## Copag: os 8 produtos (não 6)

| SKU | Produto | Preço Copag | EAN |
|---|---|---|---|
| 2605 | Treinador Avançado (ETB) | 399,99 | 0196214156319 |
| 2607 | Box Coleção com Fichário | 230,99 | 0196214158689 |
| 2608 | Box ex Greninja | 169,99 | 7896192380326 |
| 2609 | Box ex Sylveon (**fora da sua lista**) | 169,99 | 7896192380333 |
| 2606 | Box Coleção com Pôster (**fora da sua lista**) | 115,99 | 0196214165502 |
| 2603 | Blister Triplo Lucario | 99,99 | 7896192380302 |
| 2604 | Blister Triplo Exeggutor | 99,99 | 7896192380319 |
| 2602 | Blister Duplo com Moeda | 69,99 | 0196214159884 |

O preço da Copag **não é** o "preço sugerido oficial". Não usei esses valores na tabela de teto porque
a lista oficial não foi vista. [A CONFIRMAR] com a lista.

## Mercado Livre: para onde apontam os `meli.la`

Todos redirecionam (301) para a página de afiliado `/social/bcfebadgh92936?matt_word=clubeoraculo&ref=...`,
com o produto destacado cifrado no `ref`. O produto de catálogo foi identificado pelo ID mais
repetido na página (17 ocorrências cada):

| Link | Produto de catálogo |
|---|---|
| `1TkNofq` | ETB `/p/MLB79395943` |
| `1VW87VF` | Blister Duplo + moeda `/p/MLB77672147` |
| `23RSzoj` | Blister Triplo Exeggutor `/p/MLB79396270` |
| `2eKYGgW` | Box Greninja ex `/p/MLB79396707` |
| `2Pk1CqJ` | Coleção c/ Fichário `/p/MLB79396525` |
| `2cKhGob` ("Todos") | lista do afiliado, sem produto único |

Faltam no ML: Lucario, Sylveon, Pôster. [A CONFIRMAR] os IDs de catálogo deles.

## Recomendação por fonte

- **Copag: seguir.** Simulação para estoque e preço, catálogo a cada N ciclos para descobrir SKU novo.
  Modo de falha: a Copag pode fechar a simulação pública ou mudar o campo; a Fase 3 trata "campo ausente"
  como erro, não como "sem estoque".
- **Mercado Livre: inviável sem token.** Com token de app, `/products/{id}/items` é o caminho certo
  (menor oferta entre vendedores do mesmo produto de catálogo), mas o 403 veio de `PolicyAgent`,
  que é política, não autenticação; **não sei** se o token destrava. Scraping está fora: o site
  responde com verificação anti-robô, e passar por ela cruza a regra 3.
  Seguindo o protocolo: **proponho entregar só a Copag primeiro** e testar o ML com token em paralelo.

## O que eu acho que ainda está faltando

1. A lista de preço sugerido oficial. Sem ela o teto do ML não existe.
2. Se o `AvailableQuantity: 1` do Lucario no catálogo foi estoque real que acabou ou resíduo de cache.
   Não dá para saber com uma amostra.
3. Limite de taxa da simulação: não vi cabeçalho de rate limit. Uma chamada com 8 SKUs a cada 5 min é
   educado; mais agressivo que isso não testei.
4. Se a Copag muda de seller (`seller: "1"`) em lançamento. Hoje todos são seller 1.
5. Se o estoque é regional: com e sem CEP deu o mesmo resultado hoje, mas só testei um CEP.
