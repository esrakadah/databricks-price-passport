import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:price_passport_app/main.dart';
import 'package:price_passport_app/prices.dart';

final _now = DateTime.utc(2026, 10, 29, 12);

Map<String, Object> _day(String day, String source, {List<double>? prices}) => {
  'delivery_day': day,
  'source': source,
  'fetched_at': '2026-10-29T09:00:00.000Z',
  'hours': [
    for (final (index, price) in (prices ?? List<double>.generate(24, (hour) => hour * 10.0 - 50)).indexed)
      {
        'hour_start': DateTime.utc(2026, 10, 29, 23).add(Duration(hours: index)).toIso8601String(),
        'price_eur_mwh': price,
        'complete': true,
      },
  ],
};

PricePassportApp _app(Map<String, Map<String, Object>?> days) => PricePassportApp(
  api: PriceApi(
    client: MockClient((request) async {
      final day = days[request.url.queryParameters['day']];
      return day == null ? http.Response('{"error": "unavailable"}', 503) : http.Response(jsonEncode(day), 200);
    }),
    baseUri: Uri.parse('https://api.example'),
  ),
  clock: () => _now,
);

void main() {
  testWidgets('tomorrow is shown first, live, with a chart that can be read out', (tester) async {
    await tester.pumpWidget(_app({'2026-10-30': _day('2026-10-30', 'live')}));
    await tester.pumpAndSettle();

    expect(find.text('Live from Databricks'), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp('24 hourly prices from -50.00 to 180.00 EUR per MWh')), findsOneWidget);
  });

  testWidgets('a snapshot says how old it is', (tester) async {
    await tester.pumpWidget(_app({'2026-10-30': _day('2026-10-30', 'snapshot')}));
    await tester.pumpAndSettle();

    expect(find.textContaining('3 h old'), findsOneWidget);
  });

  testWidgets('tapping a bar shows that hour in Berlin time', (tester) async {
    await tester.pumpWidget(_app({'2026-10-30': _day('2026-10-30', 'live')}));
    await tester.pumpAndSettle();

    await tester.tapAt(tester.getTopLeft(find.byType(CustomPaint).last) + const Offset(2, 100));
    await tester.pump();

    expect(find.text('00:00 to 01:00 Berlin time'), findsOneWidget);
  });

  testWidgets('switching to today asks for today, and an outage is said plainly', (tester) async {
    await tester.pumpWidget(_app({'2026-10-30': _day('2026-10-30', 'live')}));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Today'));
    await tester.pumpAndSettle();

    expect(find.text('Prices for 2026-10-29 are not available right now.'), findsOneWidget);
  });
}
