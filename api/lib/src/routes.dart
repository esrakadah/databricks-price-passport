import 'dart:convert';
import 'dart:io';

import 'package:logging/logging.dart';
import 'package:price_passport_api/src/prices.dart';
import 'package:shelf/shelf.dart';
import 'package:shelf_router/shelf_router.dart';

final _log = Logger('routes');
final _isoDay = RegExp(r'^\d{4}-\d{2}-\d{2}$');
const _json = {'Content-Type': 'application/json'};

/// `DateTime.tryParse` rolls 2026-13-45 over into a real date, so a day only counts if it reads back unchanged.
bool _isCalendarDay(String day) =>
    _isoDay.hasMatch(day) && (DateTime.tryParse(day)?.toIso8601String().startsWith(day) ?? false);

/// `GET /prices?day=YYYY-MM-DD` returns one local delivery day; `GET /health` answers for Cloud Run. Not `/healthz`:
/// Cloud Run's front end reserves paths ending in "z" and never forwards them to the container.
Router priceRoutes(PriceLookup prices) => Router()
  ..get('/health', (Request _) => Response.ok('ok'))
  ..get('/prices', (Request request) async {
    final day = request.url.queryParameters['day'];
    if (day == null || !_isCalendarDay(day)) {
      return Response.badRequest(body: jsonEncode({'error': 'pass day=YYYY-MM-DD'}), headers: _json);
    }
    try {
      final result = await prices(day);
      return Response.ok(jsonEncode(result.toJson()), headers: _json);
    } on Exception catch (error) {
      _log.warning('prices for $day failed', error);
      return Response(
        HttpStatus.serviceUnavailable,
        body: jsonEncode({'error': 'prices are unavailable right now'}),
        headers: _json,
      );
    }
  });
