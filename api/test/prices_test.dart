import 'dart:convert';

import 'package:http/testing.dart';
import 'package:price_passport_api/price_passport_api.dart';
import 'package:shelf/shelf.dart';
import 'package:test/test.dart';

class _CountingSource {
  _CountingSource(this._clock, {this.fails = false});

  final DateTime Function() _clock;
  final bool fails;
  int calls = 0;

  Future<DeliveryDayPrices> call(String day) async {
    calls++;
    if (fails) throw Exception('warehouse unavailable');
    return DeliveryDayPrices(
      deliveryDay: day,
      hours: [HourlyPrice(hourStart: DateTime.utc(2026, 10, 27, 23), priceEurMwh: 120.5, isComplete: true)],
      fetchedAt: _clock(),
      source: 'live',
    );
  }
}

void main() {
  late DateTime now;
  DateTime clock() => now;
  setUp(() => now = DateTime.utc(2026, 10, 29, 12));

  test('a record from the statement API becomes an hourly price in UTC', () {
    final price = HourlyPrice.fromRecord({
      'hour_start': '2026-10-27T23:00:00.000Z',
      'price_eur_mwh': '-12.25',
      'is_complete': 'true',
    });

    expect(price.hourStart, DateTime.utc(2026, 10, 27, 23));
    expect(price.priceEurMwh, -12.25);
    expect(price.isComplete, isTrue);
  });

  test('a cached day is served for an hour, then read again', () async {
    final live = _CountingSource(clock);
    final cached = CachedPriceSource(live.call, clock: clock);

    await cached.deliveryDay('2026-10-28');
    now = now.add(const Duration(minutes: 59));
    await cached.deliveryDay('2026-10-28');
    expect(live.calls, 1);

    now = now.add(const Duration(minutes: 2));
    await cached.deliveryDay('2026-10-28');
    expect(live.calls, 2);
  });

  test('names that are not plain identifiers never reach the SQL', () {
    expect(
      () => DatabricksPriceSource(_unusedClient, catalog: 'workspace', schema: 'x; DROP TABLE y', clock: clock),
      throwsArgumentError,
    );
  });

  group('routes', () {
    Future<Response> get(_CountingSource source, String path) =>
        priceRoutes(source.call).call(Request('GET', Uri.parse('http://localhost$path')));

    test('GET /prices returns the day with its source and fetch time', () async {
      final response = await get(_CountingSource(clock), '/prices?day=2026-10-28');

      expect(response.statusCode, 200);
      final body = jsonDecode(await response.readAsString()) as Map<String, dynamic>;
      expect(body['delivery_day'], '2026-10-28');
      expect(body['source'], 'live');
      expect(body['fetched_at'], '2026-10-29T12:00:00.000Z');
      expect((body['hours'] as List<dynamic>).single, {
        'hour_start': '2026-10-27T23:00:00.000Z',
        'price_eur_mwh': 120.5,
        'complete': true,
      });
    });

    for (final query in ['', '?day=yesterday', '?day=2026-13-45']) {
      test('GET /prices$query is refused as a bad request', () async {
        final response = await get(_CountingSource(clock), '/prices$query');

        expect(response.statusCode, 400);
      });
    }

    test('a failing source answers 503 without leaking the error', () async {
      final response = await get(_CountingSource(clock, fails: true), '/prices?day=2026-10-28');

      expect(response.statusCode, 503);
      expect(await response.readAsString(), isNot(contains('warehouse')));
    });

    test('GET /health answers ok', () async {
      final response = await get(_CountingSource(clock), '/health');

      expect(await response.readAsString(), 'ok');
    });
  });
}

final _unusedClient = SqlStatementClient(
  host: Uri.parse('https://workspace.example'),
  warehouseId: 'unused',
  tokens: OAuthTokenSource(
    ServicePrincipal(host: Uri.parse('https://workspace.example'), clientId: 'unused', clientSecret: 'unused'),
    client: MockClient((_) => throw StateError('the SQL client must not be called')),
    clock: DateTime.now,
  ),
  client: MockClient((_) => throw StateError('the SQL client must not be called')),
  clock: DateTime.now,
);
