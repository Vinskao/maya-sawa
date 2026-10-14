-- Canonical candidate identity follows the Shioaji contract code. Futures
-- months are encoded in code; delivery_month remains display metadata only.
-- Do not expire historical candidate/source membership records automatically.

WITH candidate_rollup AS (
    SELECT code, MIN(first_seen_at) AS first_seen_at,
           MAX(last_seen_at) AS last_seen_at
    FROM public.maya_sawa_market_candidate GROUP BY code
), latest_candidate AS (
    SELECT DISTINCT ON (code) code, product_type, name, delivery_month
    FROM public.maya_sawa_market_candidate
    ORDER BY code, last_seen_at DESC, id DESC
), keep_candidate AS (
    SELECT DISTINCT ON (code) id, code
    FROM public.maya_sawa_market_candidate
    ORDER BY code, last_seen_at DESC, id DESC
)
UPDATE public.maya_sawa_market_candidate c
SET first_seen_at = r.first_seen_at,
    last_seen_at = r.last_seen_at,
    product_type = l.product_type,
    name = l.name,
    delivery_month = l.delivery_month,
    expires_at = NULL
FROM candidate_rollup r
JOIN latest_candidate l USING (code)
JOIN keep_candidate k USING (code)
WHERE c.id = k.id;

DELETE FROM public.maya_sawa_market_candidate c
USING (
    SELECT id, ROW_NUMBER() OVER (
        PARTITION BY code ORDER BY last_seen_at DESC, id DESC
    ) AS row_num
    FROM public.maya_sawa_market_candidate
) duplicates
WHERE c.id = duplicates.id AND duplicates.row_num > 1;

WITH source_rollup AS (
    SELECT source_key, code, MIN(first_seen_at) AS first_seen_at,
           MAX(last_seen_at) AS last_seen_at
    FROM public.maya_sawa_market_candidate_source GROUP BY source_key, code
), latest_source AS (
    SELECT DISTINCT ON (source_key, code)
           source_key, code, product_type, delivery_month
    FROM public.maya_sawa_market_candidate_source
    ORDER BY source_key, code, last_seen_at DESC, id DESC
), keep_source AS (
    SELECT DISTINCT ON (source_key, code) id, source_key, code
    FROM public.maya_sawa_market_candidate_source
    ORDER BY source_key, code, last_seen_at DESC, id DESC
)
UPDATE public.maya_sawa_market_candidate_source s
SET first_seen_at = r.first_seen_at,
    last_seen_at = r.last_seen_at,
    product_type = l.product_type,
    delivery_month = l.delivery_month,
    expires_at = NULL
FROM source_rollup r
JOIN latest_source l USING (source_key, code)
JOIN keep_source k USING (source_key, code)
WHERE s.id = k.id;

DELETE FROM public.maya_sawa_market_candidate_source s
USING (
    SELECT id, ROW_NUMBER() OVER (
        PARTITION BY source_key, code ORDER BY last_seen_at DESC, id DESC
    ) AS row_num
    FROM public.maya_sawa_market_candidate_source
) duplicates
WHERE s.id = duplicates.id AND duplicates.row_num > 1;

ALTER TABLE public.maya_sawa_market_candidate
    DROP CONSTRAINT IF EXISTS uq_market_candidate_identity;
ALTER TABLE public.maya_sawa_market_candidate
    ADD CONSTRAINT uq_market_candidate_identity UNIQUE (code);

ALTER TABLE public.maya_sawa_market_candidate_source
    DROP CONSTRAINT IF EXISTS uq_market_candidate_source_identity;
ALTER TABLE public.maya_sawa_market_candidate_source
    ADD CONSTRAINT uq_market_candidate_source_identity UNIQUE (source_key, code);

UPDATE public.maya_sawa_market_candidate SET expires_at = NULL;
UPDATE public.maya_sawa_market_candidate_source SET expires_at = NULL;
