#!/usr/bin/env bash

set -Eeuo pipefail

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

api_url="${API_URL:-http://localhost:8000}"
admin_password="${ADMIN_PASSWORD:?set ADMIN_PASSWORD or create .env from .env.example}"
run_id="$(date +%s)-$$"
product_id="33333333-3333-4333-8333-333333333333"
warehouse_id="22222222-2222-4222-8222-222222222222"

for attempt in {1..40}; do
  if curl --fail --silent "${api_url}/api/v1/health/ready" >/dev/null; then
    break
  fi
  if [[ "${attempt}" -eq 40 ]]; then
    echo "Orders API did not become ready" >&2
    exit 1
  fi
  sleep 2
done

token="$(
  curl --fail-with-body --silent --show-error \
    --request POST "${api_url}/api/v1/auth/token" \
    --header "Content-Type: application/json" \
    --data "$(jq -n --arg password "${admin_password}" \
      '{email: "admin@retailflow.local", password: $password}')" |
    jq --exit-status --raw-output '.accessToken'
)"

create_payload="$(
  jq -n \
    --arg warehouseId "${warehouse_id}" \
    --arg productId "${product_id}" \
    '{warehouseId: $warehouseId, lines: [{productId: $productId, quantity: 2}]}'
)"
order="$(
  curl --fail-with-body --silent --show-error \
    --request POST "${api_url}/api/v1/orders" \
    --header "Authorization: Bearer ${token}" \
    --header "Idempotency-Key: smoke-create-${run_id}" \
    --header "Content-Type: application/json" \
    --data "${create_payload}"
)"
order_id="$(jq --exit-status --raw-output '.id' <<<"${order}")"

replayed_id="$(
  curl --fail-with-body --silent --show-error \
    --request POST "${api_url}/api/v1/orders" \
    --header "Authorization: Bearer ${token}" \
    --header "Idempotency-Key: smoke-create-${run_id}" \
    --header "Content-Type: application/json" \
    --data "${create_payload}" |
    jq --exit-status --raw-output '.id'
)"
[[ "${replayed_id}" == "${order_id}" ]]

curl --fail-with-body --silent --show-error \
  --request POST "${api_url}/api/v1/orders/${order_id}/checkout" \
  --header "Authorization: Bearer ${token}" \
  --header "Idempotency-Key: smoke-checkout-${run_id}" \
  --header "Content-Type: application/json" \
  --data '{"paymentMethod":"pm_demo_approved"}' |
  jq --exit-status \
    '.status == "CONFIRMED" and (.paymentReference | startswith("pay_"))' >/dev/null

declined_order_id="$(
  curl --fail-with-body --silent --show-error \
    --request POST "${api_url}/api/v1/orders" \
    --header "Authorization: Bearer ${token}" \
    --header "Idempotency-Key: smoke-declined-${run_id}" \
    --header "Content-Type: application/json" \
    --data "${create_payload}" |
    jq --exit-status --raw-output '.id'
)"
curl --fail-with-body --silent --show-error \
  --request POST "${api_url}/api/v1/orders/${declined_order_id}/checkout" \
  --header "Authorization: Bearer ${token}" \
  --header "Idempotency-Key: smoke-declined-checkout-${run_id}" \
  --header "Content-Type: application/json" \
  --data '{"paymentMethod":"pm_demo_declined"}' |
  jq --exit-status '.status == "CANCELLED"' >/dev/null

for attempt in {1..20}; do
  kafka_events="$(
    docker compose exec -T kafka \
      /opt/kafka/bin/kafka-console-consumer.sh \
      --bootstrap-server kafka:9092 \
      --topic retailflow.order-events.v1 \
      --from-beginning \
      --timeout-ms 3000 2>/dev/null || true
  )"
  if jq --slurp --exit-status --arg orderId "${order_id}" \
    'any(.[]; .aggregateId == $orderId and .data.status == "CONFIRMED")' \
    <<<"${kafka_events}" >/dev/null 2>&1; then
    echo "Smoke test passed: auth, idempotency, checkout saga, compensation, and Kafka outbox"
    exit 0
  fi
  sleep 2
done

echo "Confirmed order event was not observed in Kafka" >&2
exit 1
