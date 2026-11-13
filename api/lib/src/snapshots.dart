import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:logging/logging.dart';
import 'package:price_passport_api/src/databricks_sql.dart';
import 'package:price_passport_api/src/prices.dart';

final _log = Logger('snapshots');

/// Tokens of the Cloud Run service account, from the metadata server that every Cloud Run instance has.
class MetadataTokenSource {
  MetadataTokenSource({required this._client, required this._clock});

  static final Uri _tokenUrl = Uri.parse(
    'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
  );
  static const refreshMargin = Duration(minutes: 5);

  final http.Client _client;
  final Clock _clock;
  String? _token;
  DateTime? _expiresAt;

  Future<String> token() async {
    final cached = _token;
    final expiresAt = _expiresAt;
    if (cached != null && expiresAt != null && _clock().isBefore(expiresAt.subtract(refreshMargin))) {
      return cached;
    }
    final response = await _client.get(
      _tokenUrl,
      headers: {'Metadata-Flavor': 'Google'},
    );
    if (response.statusCode != 200) {
      throw StateError(
        'metadata token request failed with HTTP ${response.statusCode}',
      );
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    final token = body['access_token'] as String;
    _token = token;
    _expiresAt = _clock().add(
      Duration(seconds: (body['expires_in'] as num).toInt()),
    );
    return token;
  }
}

/// The last good answer for each delivery day, kept in a private Cloud Storage bucket (decisions section 5). Reading it
/// needs no Databricks, so it still works when the Free Edition quota has shut compute down.
class CloudStorageSnapshots {
  CloudStorageSnapshots({
    required this._bucket,
    required this._client,
    required this._token,
  });

  final String _bucket;
  final http.Client _client;
  final Future<String> Function() _token;

  String _objectName(String day) => 'prices/$day.json';

  Future<void> save(DeliveryDayPrices prices) async {
    final uri = Uri.https(
      'storage.googleapis.com',
      '/upload/storage/v1/b/$_bucket/o',
      {'uploadType': 'media', 'name': _objectName(prices.deliveryDay)},
    );
    final response = await _client.post(
      uri,
      headers: {
        'Authorization': 'Bearer ${await _token()}',
        'Content-Type': 'application/json',
      },
      body: jsonEncode(prices.toJson()),
    );
    if (response.statusCode != 200) {
      throw StateError(
        'snapshot upload failed with HTTP ${response.statusCode}',
      );
    }
  }

  /// The stored day, or null if there is none.
  Future<DeliveryDayPrices?> load(String day) async {
    final uri = Uri.https(
      'storage.googleapis.com',
      '/storage/v1/b/$_bucket/o/${Uri.encodeComponent(_objectName(day))}',
      {'alt': 'media'},
    );
    final response = await _client.get(
      uri,
      headers: {'Authorization': 'Bearer ${await _token()}'},
    );
    if (response.statusCode == HttpStatus.notFound) return null;
    if (response.statusCode != 200) {
      throw StateError(
        'snapshot download failed with HTTP ${response.statusCode}',
      );
    }
    return DeliveryDayPrices.fromJson(
      jsonDecode(response.body) as Map<String, dynamic>,
      source: 'snapshot',
    );
  }
}

/// Live first; every live answer is also stored, and a failed live read is answered from the store if it has the day.
/// A failed upload is logged and never fails the request, because the live answer is still good.
PriceLookup withSnapshotFallback(
  PriceLookup live,
  CloudStorageSnapshots snapshots,
) => (day) async {
  try {
    final fresh = await live(day);
    try {
      await snapshots.save(fresh);
    } on Object catch (error) {
      _log.warning('snapshot of $day not saved', error);
    }
    return fresh;
  } on Exception catch (liveError) {
    final stored = await snapshots.load(day);
    if (stored == null) rethrow;
    _log.warning(
      'serving the snapshot of $day because the live read failed',
      liveError,
    );
    return stored;
  }
};
