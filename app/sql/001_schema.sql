-- Idempotente: roda a cada start do monitor.

CREATE TABLE IF NOT EXISTS fonte (
    codigo  text PRIMARY KEY,
    nome    text NOT NULL
);

CREATE TABLE IF NOT EXISTS produto (
    id              serial PRIMARY KEY,
    codigo          text NOT NULL UNIQUE,
    nome            text NOT NULL,
    ean             text,
    preco_sugerido  numeric(10,2),          -- null = não cadastrado, sem teto
    ativo           boolean NOT NULL DEFAULT true,
    atualizado_em   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS link (
    id          serial PRIMARY KEY,
    produto_id  int NOT NULL REFERENCES produto(id),
    fonte       text NOT NULL REFERENCES fonte(codigo),
    id_externo  text NOT NULL,              -- SKU na Copag, MLB... no ML
    url         text NOT NULL,
    ativo       boolean NOT NULL DEFAULT true,
    UNIQUE (fonte, id_externo)
);

-- Uma linha por link por ciclo. É daqui que sai o "report de diferença".
CREATE TABLE IF NOT EXISTS observacao (
    id            bigserial PRIMARY KEY,
    link_id       int NOT NULL REFERENCES link(id),
    observado_em  timestamptz NOT NULL DEFAULT now(),
    disponivel    boolean NOT NULL,
    status        text NOT NULL,            -- valor cru da fonte (available, withoutStock, ...)
    preco         numeric(10,2),
    frete         numeric(10,2),
    vendedor      text,
    maquina       text NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_observacao_link_data ON observacao (link_id, observado_em DESC);

CREATE TABLE IF NOT EXISTS alerta_enviado (
    id          bigserial PRIMARY KEY,
    link_id     int REFERENCES link(id),    -- null para alerta de sistema
    tipo        text NOT NULL,
    mensagem    text NOT NULL,
    enviado     boolean NOT NULL,
    erro        text,
    maquina     text NOT NULL,
    enviado_em  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS falha_fonte (
    fonte          text PRIMARY KEY REFERENCES fonte(codigo),
    consecutivas   int NOT NULL DEFAULT 0,
    ultimo_erro    text,
    cego_avisado   boolean NOT NULL DEFAULT false,
    atualizado_em  timestamptz NOT NULL DEFAULT now()
);

-- Estado de alertas quando não há Telegram (o Telegram guarda o compartilhado).
CREATE TABLE IF NOT EXISTS estado_local (
    id     int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    dados  jsonb NOT NULL
);

CREATE OR REPLACE VIEW vw_ultimo_estado AS
SELECT DISTINCT ON (l.id)
       p.nome AS produto, l.fonte, o.disponivel, o.status, o.preco, p.preco_sugerido,
       o.preco - p.preco_sugerido AS diferenca, o.observado_em, o.maquina, l.url
FROM link l
JOIN produto p ON p.id = l.produto_id
JOIN observacao o ON o.link_id = l.id
ORDER BY l.id, o.observado_em DESC;
