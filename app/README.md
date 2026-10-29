# Price Passport web app

Shows today's and tomorrow's hourly prices from the Price Passport API in Berlin time, with a badge that says whether
the numbers were read live from Databricks or come from the stored snapshot, and how old they are.

```bash
flutter pub get
flutter test
flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8080
```

Without `API_BASE_URL` the app calls the API on its own origin.
