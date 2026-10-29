import 'dart:io';

import 'package:price_passport_api/price_passport_api.dart';
import 'package:shelf/shelf.dart';
import 'package:test/test.dart';

Future<DeliveryDayPrices> _prices(String day) async =>
    DeliveryDayPrices(deliveryDay: day, hours: const [], fetchedAt: DateTime.utc(2026, 10, 29), source: 'live');

void main() {
  late Directory webRoot;

  setUp(() async {
    webRoot = await Directory.systemTemp.createTemp('web_app_test');
    await File('${webRoot.path}/index.html').writeAsString('<title>Price Passport</title>');
  });

  tearDown(() => webRoot.delete(recursive: true));

  Future<Response> get(Handler handler, String path) =>
      Future.value(handler(Request('GET', Uri.parse('http://localhost$path'))));

  test('the app is served at the root and the API keeps its routes', () async {
    final handler = appAndApi(_prices, webRoot: webRoot.path);

    expect(await (await get(handler, '/')).readAsString(), contains('Price Passport'));
    expect((await get(handler, '/prices?day=2026-10-28')).headers['content-type'], 'application/json');
    expect(await (await get(handler, '/health')).readAsString(), 'ok');
  });

  test('without a built app the API still answers and unknown paths are 404', () async {
    final handler = appAndApi(_prices, webRoot: '${webRoot.path}/missing');

    expect((await get(handler, '/')).statusCode, HttpStatus.notFound);
    expect(await (await get(handler, '/health')).readAsString(), 'ok');
  });
}
