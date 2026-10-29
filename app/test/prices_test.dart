import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:price_passport_app/prices.dart';

const Map<String, Object> _dayJson = {
  'delivery_day': '2026-10-28',
  'source': 'snapshot',
  'fetched_at': '2026-10-28T09:00:00.000Z',
  'hours': [
    {'hour_start': '2026-10-27T23:00:00.000Z', 'price_eur_mwh': -12.5, 'complete': true},
  ],
};

void main() {
  test('a day from the API keeps its source, fetch time and prices', () {
    final day = DayPrices.fromJson(_dayJson);

    expect(day.isLive, isFalse);
    expect(day.fetchedAt, DateTime.utc(2026, 10, 28, 9));
    expect(day.hours.single.priceEurMwh, -12.5);
    expect(day.hours.single.priceCentPerKwh, -1.25);
  });

  test('the client asks for one delivery day and reports a failure plainly', () async {
    final requested = <Uri>[];
    final api = PriceApi(
      client: MockClient((request) async {
        requested.add(request.url);
        return request.url.queryParameters['day'] == '2026-10-28'
            ? http.Response(jsonEncode(_dayJson), 200)
            : http.Response('{"error": "unavailable"}', 503);
      }),
      baseUri: Uri.parse('https://api.example'),
    );

    expect((await api.day('2026-10-28')).deliveryDay, '2026-10-28');
    expect(requested.single.path, '/prices');
    await expectLater(api.day('2026-10-29'), throwsA(isA<PriceApiException>()));
  });
}
