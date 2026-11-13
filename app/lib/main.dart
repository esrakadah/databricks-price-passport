import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:price_passport_app/price_page.dart';
import 'package:price_passport_app/prices.dart';

/// Where the API runs; empty means the origin the app itself was served from.
const _apiBaseUrl = String.fromEnvironment('API_BASE_URL');

void main() {
  final baseUri = _apiBaseUrl.isEmpty ? Uri.base.replace(path: '/', query: '') : Uri.parse(_apiBaseUrl);
  runApp(
    PricePassportApp(
      api: PriceApi(client: http.Client(), baseUri: baseUri),
      clock: DateTime.now,
    ),
  );
}

class PricePassportApp extends StatelessWidget {
  const PricePassportApp({required this.api, required this.clock, super.key});

  final PriceApi api;
  final DateTime Function() clock;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Price Passport',
      theme: ThemeData(colorSchemeSeed: const Color(0xFF0B6E4F)),
      home: PricePage(api: api, clock: clock),
    );
  }
}
