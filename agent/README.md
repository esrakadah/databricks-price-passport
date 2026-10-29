# Price Passport agent

A Genkit Dart agent that explains a price. It knows the prices only through one MCP tool, `lookup_day_prices`, which
reads a delivery day from the Price Passport API and hands the model the hours in Berlin time together with the mean,
the cheapest and dearest hour, negative and incomplete hours, and whether the numbers are live or from a snapshot.
The system prompt allows only those numbers, and forbids claiming a model version or training data until the
passport carries them.

```text
POST /explainPrice ──> Genkit flow `explainPrice` ──> Gemini (tool calling, structured output)
                              └──> MCP client ──HTTP──> price-passport MCP server ──> lookup_day_prices ──> API /prices
```

| Variable | Value |
|---|---|
| `PRICE_PASSPORT_API_URL` | the API, for example the Cloud Run URL |
| `GEMINI_API_KEY` | on Cloud Run, from Secret Manager |
| `GEMINI_MODEL` | optional, defaults to `gemini-3.5-flash-lite` |
| `ALLOWED_ORIGINS` | origins the web app calls from, comma separated |

```bash
dart pub get
dart run build_runner build
dart test
PRICE_PASSPORT_API_URL=http://localhost:8080 GEMINI_API_KEY=... dart run bin/server.dart
curl -X POST http://localhost:8081/explainPrice -H 'Content-Type: application/json' \
  -d '{"data": {"question": "Why is 18:00 tomorrow so expensive?"}}'
```

Not yet: the passport (model version and training data per price, now in `current_prices`) and overrides behind an
approval gate.
