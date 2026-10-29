import 'package:price_passport_api/src/databricks_sql.dart';

/// One hour of the day-ahead price as silver holds it (decisions section 4).
class HourlyPrice {
  const HourlyPrice({required this.hourStart, required this.priceEurMwh, required this.isComplete});

  factory HourlyPrice.fromRecord(Map<String, String?> record) => HourlyPrice(
    hourStart: DateTime.parse(record['hour_start']!).toUtc(),
    priceEurMwh: double.parse(record['price_eur_mwh']!),
    isComplete: record['is_complete'] == 'true',
  );

  final DateTime hourStart;
  final double priceEurMwh;
  final bool isComplete;

  Map<String, Object> toJson() => {
    'hour_start': hourStart.toIso8601String(),
    'price_eur_mwh': priceEurMwh,
    'complete': isComplete,
  };
}

/// Prices of one local delivery day, and when and where they were read.
class DeliveryDayPrices {
  const DeliveryDayPrices({
    required this.deliveryDay,
    required this.hours,
    required this.fetchedAt,
    required this.source,
  });

  final String deliveryDay;
  final List<HourlyPrice> hours;
  final DateTime fetchedAt;
  final String source;

  Map<String, Object> toJson() => {
    'delivery_day': deliveryDay,
    'source': source,
    'fetched_at': fetchedAt.toIso8601String(),
    'hours': [for (final hour in hours) hour.toJson()],
  };
}

/// Looks up one delivery day. The live lookup is Databricks; the nightly snapshot follows once the export job exists.
typedef PriceLookup = Future<DeliveryDayPrices> Function(String deliveryDay);

/// A plain SQL identifier, so a configured catalog or schema can go into a statement safely.
final _identifier = RegExp(r'^[A-Za-z_][A-Za-z0-9_]*$');

/// Reads silver directly through the read-only service principal. The day is a bound parameter, never spliced in.
class DatabricksPriceSource {
  DatabricksPriceSource(this._sql, {required String catalog, required String schema, required this._clock})
    : _table = '${_checked(catalog)}.${_checked(schema)}.silver_price_hourly';

  final SqlStatementClient _sql;
  final String _table;
  final Clock _clock;

  static String _checked(String name) {
    if (!_identifier.hasMatch(name)) throw ArgumentError.value(name, 'name', 'not a plain SQL identifier');
    return name;
  }

  Future<DeliveryDayPrices> deliveryDay(String day) async {
    final result = await _sql.execute(
      'SELECT hour_start, price_eur_mwh, is_complete FROM $_table WHERE delivery_day = :day ORDER BY hour_start',
      parameters: {'day': day},
    );
    return DeliveryDayPrices(
      deliveryDay: day,
      hours: [for (final record in result.records) HourlyPrice.fromRecord(record)],
      fetchedAt: _clock().toUtc(),
      source: 'live',
    );
  }
}

/// Keeps each day's prices for an hour (decisions section 5), so most requests never wake the warehouse.
class CachedPriceSource {
  CachedPriceSource(this._inner, {required this._clock, this.timeToLive = const Duration(hours: 1)});

  final PriceLookup _inner;
  final Clock _clock;
  final Duration timeToLive;
  final _entries = <String, DeliveryDayPrices>{};

  Future<DeliveryDayPrices> deliveryDay(String day) async {
    final cached = _entries[day];
    if (cached != null && _clock().difference(cached.fetchedAt) < timeToLive) return cached;
    final fresh = await _inner(day);
    _entries[day] = fresh;
    return fresh;
  }
}
