-- Read-only checks after the TZS 500 live test (billing phase 1, §5.7). Prints no phone number (masked only),
-- no full Abliner id (shape only) and no secret.
-- Usage on the server (replace NOVA-XXXXXXXX with the reference test-payment printed):
--   docker exec -i nova-georisk-engine-postgres-1 sh -c 'psql -U "$POSTGRES_USER" -d nova_georisk_firris_2f1b2dc -At -F " | " -v ref=NOVA-XXXXXXXX' < abliner_test_checks.sql
begin read only;
\echo == payment intent
select status, purpose, amount, currency, phone_masked,
       case when abliner_tx_id ~* '^[0-9a-f-]{36}$' then 'uuid' when abliner_tx_id like 'tx\_%' then 'tx_' when abliner_tx_id is null then 'missing' else 'other' end as deposit_reply_id,
       case when abliner_event_tx_id ~* '^[0-9a-f-]{36}$' then 'uuid' when abliner_event_tx_id like 'tx\_%' then 'tx_' when abliner_event_tx_id is null then 'missing' else 'other' end as webhook_id,
       abliner_tx_id = abliner_event_tx_id as ids_equal, provider_reference is not null as provider_ref_set,
       failure_code, review_reason, payment_id is not null as has_payment, created_at, completed_at
from payment_intents where reference = :'ref';
\echo == webhook events for it
select left(webhook_id, 4) || '…' || right(webhook_id, 10) as webhook_id, event, remote_status, amount, currency, outcome, received_at
from abliner_webhook_events where customer_reference = :'ref' or intent_id = (select id from payment_intents where reference = :'ref') order by received_at;
\echo == payments on the test subscription (test, then reversal)
select purpose, amount, currency, method, left(note, 70) as note, reverses_payment_id is not null as is_reversal, created_at
from payments where subscription_id = '67cbdfac-acde-4de6-baee-f25de5aeb1c5' order by created_at;
\echo == receipts (a test payment gets series "test"; a reversal gets none)
select r.series, r.number, r.issued_at from payment_receipts r join payments p on p.id = r.payment_id
where p.subscription_id = '67cbdfac-acde-4de6-baee-f25de5aeb1c5' order by r.issued_at;
\echo == credit-ledger rows on the test subscription (must be 0)
select count(*) from credit_ledger_entries where subscription_id = '67cbdfac-acde-4de6-baee-f25de5aeb1c5';
\echo == audit on the test organization
select created_at, action, actor_label, left(reason, 90) from platform_audit
where organization_id = 'cc2ca7c9-5164-41a5-bd2c-19e26ef5f9ee' order by created_at;
\echo == Abliner integration status
select last_success_at, last_error_at, last_error_code, last_webhook_at, last_webhook_event, last_test_at, last_test_result
from integration_status where name = 'abliner';
\echo == nothing touched NOVAREX (both must be 0)
select (select count(*) from payment_intents where organization_id = '00000000-0000-0000-0000-000000000001'),
       (select count(*) from payments where organization_id = '00000000-0000-0000-0000-000000000001');
commit;
