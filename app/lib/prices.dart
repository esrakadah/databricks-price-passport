import 'dart:convert';

import 'package:http/http.dart' as http;

/// One hour of the day-ahead price, as the API sends it.
class HourPrice {
  const HourPrice({required this.hourStart, required this.priceEurMwh, required this.complete});

  factory HourPrice.fromJson(Map<String, dynamic> json) => HourPrice(
    hourStart: DateTime.parse(json['hour_start'] as String).toUtc(),
    priceEurMwh: (json['price_eur_mwh'] as num).toDouble(),
    complete: json['complete'] as bool,
  );

  final DateTime hourStart;
  final double priceEurMwh;
  final bool complete;

  /// 1 EUR/MWh is 0.1 ct/kWh.
  static const _eurPerMwhPerCentPerKwh = 10;

  double get priceCentPerKwh => priceEurMwh / _eurPerMwhPerCentPerKwh;
}

/// A delivery day and whether it was read live or from the stored snapshot.
class DayPrices {
  const DayPrices({required this.deliveryDay, required this.source, required this.fetchedAt, required this.hours});

  factory DayPrices.fromJson(Map<String, dynamic> json) => DayPrices(
    deliveryDay: json['delivery_day'] as String,
    source: json['source'] as String,
    fetchedAt: DateTime.parse(json['fetched_at'] as String).toUtc(),
    hours: [for (final hour in json['hours'] as List<dynamic>) HourPrice.fromJson(hour as Map<String, dynamic>)],
  );

  final String deliveryDay;
  final String source;
  final DateTime fetchedAt;
  final List<HourPrice> hours;

  bool get isLive => source == 'live';
}

class PriceApiException implements Exception {
  const PriceApiException(this.message);

  final String message;

  @override
  String toString() => message;
}

class PriceApi {
  PriceApi({required this._client, required this._baseUri});

  final http.Client _client;
  final Uri _baseUri;

  Future<DayPrices> day(String deliveryDay) async {
    final response = await _client.get(_baseUri.replace(path: '/prices', queryParameters: {'day': deliveryDay}));
    if (response.statusCode != 200) {
      throw PriceApiException('Prices for $deliveryDay are not available right now.');
    }
    return DayPrices.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }
}
